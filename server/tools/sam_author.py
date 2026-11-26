"""Build new `.sam` animation sections from keyframes and clips of existing ones.

A `Timeline` holds one display list per frame (depth -> item). Fill it with
`track` (keyframed sprites), `copy_clip` (frames of an existing section, moved and
scaled, started at any frame) and `set_item`; then `compile_section` turns it into
place/remove/show/anchor tags and `replace_section` swaps those into a `Sam`.

Matrices here are the real 2D affine `(a, b, c, d, tx, ty)`: x' = a x + c y + tx,
y' = b x + d y + ty (y down, parts rotate around their centre). The tags keep the
shipped order `(a, d, -b, -c, tx, ty)`; `to_tag` and `from_tag` convert.
"""

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from tools import sam

Affine = Tuple[float, float, float, float, float, float]
IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
OPAQUE = 256


@dataclass(frozen=True)
class Item:
    char_id: int
    z: int
    matrix: Affine
    alpha: int = OPAQUE            # 256 is fully visible
    color: Optional[sam.ColorForm] = None


def from_tag(m) -> Affine:
    a, d, mb, mc, tx, ty = m
    return (a, -mb, -mc, d, tx, ty)


def to_tag(m: Affine):
    a, b, c, d, tx, ty = m
    return (a, d, -b, -c, tx, ty)


def compose(outer: Affine, inner: Affine) -> Affine:
    """`outer` applied after `inner`."""
    a1, b1, c1, d1, x1, y1 = outer
    a2, b2, c2, d2, x2, y2 = inner
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * x2 + c1 * y2 + x1, b1 * x2 + d1 * y2 + y1)


def make(x=0.0, y=0.0, sx=1.0, sy=None, rot=0.0) -> Affine:
    """Scale, then rotate by `rot` degrees (clockwise on screen), then move."""
    sy = sx if sy is None else sy
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return (sx * c, sx * s, -sy * s, sy * c, x, y)


def about(pivot: Tuple[float, float], matrix: Affine) -> Affine:
    """`matrix` applied around `pivot` instead of the origin."""
    return compose(make(pivot[0], pivot[1]), compose(matrix, make(-pivot[0], -pivot[1])))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_in(t: float) -> float:
    return t * t


def ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_both(t: float) -> float:
    return t * t * (3 - 2 * t)


def linear(t: float) -> float:
    return t


class Timeline:
    def __init__(self, frames: int):
        self.frames: List[Dict[int, Item]] = [dict() for _ in range(frames)]
        self.anchors: Dict[int, List[str]] = {}

    def __len__(self):
        return len(self.frames)

    def set_item(self, frame: int, depth: int, item: Item):
        if 0 <= frame < len(self.frames):
            self.frames[frame][depth] = item

    def anchor(self, frame: int, text: str):
        self.anchors.setdefault(frame, []).append(text)

    def track(self, depth: int, char_id: int, z: int, keys: Dict[int, dict],
              ease: Callable[[float], float] = ease_both):
        """A sprite keyed at some frames; between keys x, y, sx, sy, rot and alpha are interpolated.

        Each key is a dict with any of x, y, sx, sy, rot, alpha; missing ones keep the previous key's value.
        The sprite exists from the first key to the last key, both included."""
        frames = sorted(keys)
        state = {"x": 0.0, "y": 0.0, "sx": 1.0, "sy": None, "rot": 0.0, "alpha": float(OPAQUE)}
        resolved = []
        for frame in frames:
            state = {**state, **keys[frame]}
            resolved.append(dict(state))
        for index in range(len(frames) - 1):
            f0, f1, k0, k1 = frames[index], frames[index + 1], resolved[index], resolved[index + 1]
            last = index == len(frames) - 2
            for frame in range(f0, f1 + (1 if last else 0)):
                t = ease((frame - f0) / (f1 - f0))
                sy0 = k0["sx"] if k0["sy"] is None else k0["sy"]
                sy1 = k1["sx"] if k1["sy"] is None else k1["sy"]
                matrix = make(lerp(k0["x"], k1["x"], t), lerp(k0["y"], k1["y"], t), lerp(k0["sx"], k1["sx"], t),
                              lerp(sy0, sy1, t), lerp(k0["rot"], k1["rot"], t))
                self.set_item(frame, depth, Item(char_id, z, matrix, round(lerp(k0["alpha"], k1["alpha"], t))))

    def copy_clip(self, displays, first: int, last: int, start: int, transform: Affine = IDENTITY,
                  depth_base: int = 0, keep: Callable[[int, Item], bool] = lambda depth, item: True,
                  fade_from: Optional[int] = None):
        """Copy frames first..last of existing display lists to start at `start`, moved by `transform`.

        `displays` is `sam_render.frame_states(...)` as a list; depths are shifted by `depth_base`.
        From the timeline frame `fade_from` on, the alpha ramps down to 0 at the section's last frame."""
        for offset, source in enumerate(displays[first:last + 1]):
            frame = start + offset
            for depth, (char_id, z, matrix, color) in source.items():
                item = Item(char_id, z + depth_base,
                            compose(transform, from_tag(matrix)) if matrix else transform, OPAQUE, color)
                if not keep(depth, item):
                    continue
                if fade_from is not None and frame >= fade_from:
                    span = max(1, len(self.frames) - 1 - fade_from)
                    item = Item(item.char_id, item.z, item.matrix,
                                round(OPAQUE * max(0.0, 1 - (frame - fade_from) / span)), item.color)
                self.set_item(frame, depth + depth_base, item)

    def move_all(self, depths, frame_fn: Callable[[int], Affine]):
        """Apply `frame_fn(frame)` on top of the matrix of the given depths on every frame."""
        for frame, display in enumerate(self.frames):
            for depth in depths:
                if depth in display:
                    item = display[depth]
                    display[depth] = Item(item.char_id, item.z, compose(frame_fn(frame), item.matrix),
                                          item.alpha, item.color)


def _color_for(item: Item) -> Optional[sam.ColorForm]:
    if item.alpha >= OPAQUE:
        return item.color
    base = item.color.mult if item.color and item.color.mult else (OPAQUE,) * 4
    mult = (base[0], base[1], base[2], max(0, min(OPAQUE, round(base[3] * item.alpha / OPAQUE))))
    return sam.ColorForm(mult=mult, add=item.color.add if item.color else None)


NEUTRAL_COLOR = sam.ColorForm(mult=(OPAQUE,) * 4)


def _color_change(before: Optional[sam.ColorForm], after: Optional[sam.ColorForm]) -> Optional[sam.ColorForm]:
    """What a move must carry so the client ends up with `after`: a move without a color form keeps
    the old one, so going back to no tint needs an explicit neutral form."""
    if after == before:
        return None
    return after if after is not None else NEUTRAL_COLOR


def compile_section(label: str, timeline: Timeline, initial_depths=()) -> List[sam.Tag]:
    """Tags for the section: a full place when a depth appears, a move when it only changes.

    `initial_depths` are the depths still on the display list when the section starts (the last state
    of the section before it); the first frame removes the ones the new section does not use."""
    tags: List[sam.Tag] = [sam.Label(label)]
    shown: Dict[int, Item] = {depth: Item(0, 0, IDENTITY) for depth in initial_depths}
    for frame, display in enumerate(timeline.frames):
        for depth in sorted(set(shown) - set(display)):
            tags.append(sam.Remove(depth))
            del shown[depth]
        for depth in sorted(display):
            item, before = display[depth], shown.get(depth)
            color = _color_for(item)
            if before is None or before.char_id != item.char_id:
                tags.append(sam.Place(char_id=item.char_id, depth=depth, z=item.z, matrix=to_tag(item.matrix),
                                      color=color))
            elif before != item:
                tags.append(sam.Place(char_id=0, depth=depth, z=item.z, matrix=to_tag(item.matrix),
                                      color=_color_change(_color_for(before), color)))
            shown[depth] = item
        tags.extend(sam.Anchor(text) for text in timeline.anchors.get(frame, []))
        tags.append(sam.Show())
    return tags


def replace_section(animation: sam.Sam, label: str, tags: List[sam.Tag]) -> sam.Sam:
    """A copy of `animation` where the section `label` (up to the next label) is replaced by `tags`.

    Image definitions that sat inside the old section stay (the loader reads them all up front)
    and so does a closing End tag."""
    old = animation.tags
    start = next(i for i, t in enumerate(old) if isinstance(t, sam.Label) and t.name == label)
    end = next((i for i in range(start + 1, len(old)) if isinstance(old[i], sam.Label)), len(old))
    inside = old[start:end]
    keep = [t for t in inside if isinstance(t, (sam.Image, sam.End))]
    images = [t for t in keep if isinstance(t, sam.Image)]
    closing = [t for t in keep if isinstance(t, sam.End)]
    return sam.Sam(old[:start] + images + tags + closing + old[end:])


def image_ids(animation: sam.Sam) -> Dict[str, int]:
    """Part file name -> the first image id that names it."""
    ids: Dict[str, int] = {}
    for tag in animation.tags:
        if isinstance(tag, sam.Image):
            ids.setdefault(tag.name, tag.id)
    return ids


def frame_count(tags: List[sam.Tag]) -> int:
    return sum(isinstance(t, sam.Show) for t in tags)
