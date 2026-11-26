"""Render a `.sam` animation section to a GIF or one frame to a PNG.

    python3 -m tools.sam_render ironman daiji build/ironman_daiji.gif
    python3 -m tools.sam_render ironman gongji1 build/f.png --frame 5
    python3 -m tools.sam_render ironman list

Placement rules (verified by eye on ironman: the parts assemble into the hero):
the canvas is the handle's width x height in pixels, y points down; a part image
is drawn at its own pixel size, rotated around its centre by the place matrix
`(a, d, -b, -c, tx, ty)` and moved so the centre lands on (tx, ty); parts are
sorted by `z`; a color form multiplies (256 is 1.0) and then adds.
"""

import argparse
import os
import sys
from pathlib import Path

from PIL import Image

from tools import sam

DECOMPILED = Path(os.environ.get("SAHHT_DECOMPILED", Path(__file__).resolve().parents[2] / "decompiled"))
ANIM_DIR = DECOMPILED / "apk" / "assets" / "iphonehd" / "anim"
PARTS_DIR = DECOMPILED / "characters"
BACKGROUND = (60, 60, 60, 255)
PAD = 120  # canvas pixels kept around the handle box: attacks reach outside it
WINDOW = None  # (left, top, right, bottom) in canvas pixels; None: the handle box plus PAD


def frame_states(animation: sam.Sam):
    """Yield, per frame, the display list: depth -> (char_id, z, matrix, color)."""
    state = {}
    for tag in animation.tags:
        if isinstance(tag, sam.Place):
            if tag.char_id > 0:
                state[tag.depth] = (tag.char_id, tag.z, tag.matrix, tag.color)
            elif tag.depth in state:
                char_id, _z, matrix, color = state[tag.depth]
                state[tag.depth] = (char_id, tag.z, tag.matrix or matrix, tag.color or color)
        elif isinstance(tag, sam.Remove):
            state.pop(tag.depth, None)
        elif isinstance(tag, sam.Show):
            yield dict(state)


def _tint(layer: Image.Image, color: sam.ColorForm) -> Image.Image:
    mult = color.mult or (256, 256, 256, 256)
    add = color.add or (0, 0, 0, 0)
    out = [band.point(lambda v, m=m, a=a: max(0, min(255, (v * m >> 8) + a)))
           for band, m, a in zip(layer.split(), mult, add)]
    return Image.merge("RGBA", out)


def _place(part: Image.Image, matrix, size, scale, origin=(PAD, PAD)):
    a, d, mb, mc, tx, ty = matrix
    b, c = -mb, -mc
    w, h = part.size
    fwd = [a * scale, c * scale, 0.0, b * scale, d * scale, 0.0]
    tx, ty = tx + origin[0], ty + origin[1]
    fwd[2] = tx * scale - (fwd[0] * w / 2 + fwd[1] * h / 2)
    fwd[5] = ty * scale - (fwd[3] * w / 2 + fwd[4] * h / 2)
    det = fwd[0] * fwd[4] - fwd[1] * fwd[3]
    if abs(det) < 1e-9:
        return None
    inv = [fwd[4] / det, -fwd[1] / det, 0.0, -fwd[3] / det, fwd[0] / det, 0.0]
    inv[2] = -(inv[0] * fwd[2] + inv[1] * fwd[5])
    inv[5] = -(inv[3] * fwd[2] + inv[4] * fwd[5])
    return part.transform(size, Image.AFFINE, tuple(inv), resample=Image.BICUBIC)


def render_frame(animation: sam.Sam, display, parts_dir: Path, scale: float = 2.0,
                 window=None) -> Image.Image:
    handle = animation.tags[0]
    left, top, right, bottom = window or (-PAD, -PAD, handle.width + PAD, handle.height + PAD)
    size = (int((right - left) * scale), int((bottom - top) * scale))
    names = animation.images()
    canvas = Image.new("RGBA", size, BACKGROUND)
    for char_id, _z, matrix, color in sorted(display.values(), key=lambda v: v[1]):
        if matrix is None or char_id not in names:
            continue
        path = parts_dir / names[char_id]
        if not path.exists():  # the client skips frames missing from the atlas too
            continue
        with Image.open(path) as image:
            part = image.convert("RGBA")
        if color is not None:
            part = _tint(part, color)
        layer = _place(part, matrix, size, scale, (-left, -top))
        if layer is not None:
            canvas.alpha_composite(layer)
    return canvas


def render_section(name: str, section: str, anim_dir: Path = ANIM_DIR, parts_dir: Path = PARTS_DIR,
                   scale: float = 2.0, parts: Path = None, window=None):
    animation = sam.load(str(anim_dir / (name + ".swf.sam")))
    ranges = animation.sections()
    if section not in ranges:
        raise SystemExit("no section %r in %s; has: %s" % (section, name, ", ".join(ranges)))
    first, last = ranges[section]
    displays = list(frame_states(animation))
    frames = [render_frame(animation, displays[i], parts or parts_dir / name, scale, window) for i in range(first, last + 1)]
    return frames, animation.tags[0].fps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", help="animation name, e.g. ironman")
    ap.add_argument("section", help="section name, e.g. daiji, or 'list'")
    ap.add_argument("out", nargs="?", help=".gif for the whole section, .png for one frame")
    ap.add_argument("--frame", type=int, default=0, help="frame inside the section for .png")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--window", help="left,top,right,bottom in canvas pixels, e.g. -300,-450,900,220")
    ap.add_argument("--parts", type=Path, help="folder of part PNGs to use instead of the shipped ones")
    args = ap.parse_args(argv)
    if args.section == "list":
        ranges = sam.load(str(ANIM_DIR / (args.name + ".swf.sam"))).sections()
        for key, (a, b) in ranges.items():
            print("%-12s frames %d-%d (%d)" % (key, a, b, b - a + 1))
        return 0
    if not args.out:
        ap.error("out is required")
    frames, fps = render_section(args.name, args.section, scale=args.scale, parts=args.parts,
                                  window=tuple(int(v) for v in args.window.split(",")) if args.window else None)
    if args.out.endswith(".png"):
        frames[args.frame].save(args.out)
    else:
        rgb = [f.convert("RGB") for f in frames]
        rgb[0].save(args.out, save_all=True, append_images=rgb[1:], loop=0, duration=int(1000 / fps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
