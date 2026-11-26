"""Iron Man's new ultimate (skill 3830): a rain of missiles on every enemy.

It replaces the section `gongji4` of `ironman.swf.sam` (the old one lifts a giant bomb). The hero
moves through five key poses an image AI drew (crouch, rise, charge, fire, descend), fading from one
to the next with squash and stretch; nine missiles leave the shoulder pods, arc up and dive on a 3x3
grid of targets, each one ends in a six-frame explosion. The section keeps the old length and the
old hit anchors (the sounds, the screen shake, `beiji` and the three `bao` damage ticks at frames 50,
53 and 56), so the Lua script `ironman_s3` and the server need no change.

    python3 -m tools.ironman_missile_rain build/ironman_rain \\
        --sprites build/ironman_skill_sprites --parts build/ironman_new/ironman

writes `<out>/ironman.swf.sam`, `<out>/parts/` (every part PNG, the new sprites included, named
`ironman.swf<N>.png` like the atlas frames), `<out>/new_frames.json`, `<out>/preview.gif` and
`<out>/frame_impact.png`.
"""

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Dict, List

from PIL import Image

from tools import art_kit, sam, sam_author as au, sam_render, skill_sprites

SECTION = "gongji4"
FIRST_NEW_FRAME = 301          # new sprites are named ironman.swf301.png, 302, ...
FIRST_NEW_IMAGE_ID = 1001
SUPERSAMPLE = skill_sprites.POSE_SUPERSAMPLE

# the hero's layers, from back to front (z)
SHADOW_DEPTH, FLAME_DEPTH, GLOW_DEPTH = 1, 36, 37
POSE_DEPTH = {"crouch": 31, "rise": 32, "charge": 33, "fire": 34, "descend": 35}
MISSILE_DEPTH, PUFF_DEPTH, EXPLOSION_DEPTH = 40, 60, 100
FLAME_PART, GLOW_PART = "ironman.swf69.png", "ironman.swf138.png"

HOVER = -190.0                 # how high the hero rises, in canvas pixels
# when each layer is visible: (frame, alpha 0-256) keys, linear in between
# a pose stays fully visible until the next one is fully in, so two never show half through each other
PARTS_ALPHA = [(0, 256), (5, 256), (7, 0), (59, 0), (62, 256)]
POSE_ALPHA = {
    "crouch": [(2, 0), (5, 256), (10, 256), (12, 0)],
    "rise": [(7, 0), (10, 256), (20, 256), (22, 0)],
    "charge": [(17, 0), (20, 256), (27, 256), (29, 0)],
    "fire": [(24, 0), (27, 256), (45, 256), (47, 0)],
    "descend": [(42, 0), (45, 256), (62, 256), (64, 0)],
}
LIFT = [(0, 0), (6, 0), (16, HOVER), (42, HOVER), (58, 0), (64, 0)]
FIRE_TILT = -4.0               # degrees, leaning back from the recoil

LAUNCH_FIRST, LAUNCH_STEP, FLIGHT = 24, 2, 14
POD_OFFSETS = ((-45.0, -46.0), (42.0, -52.0))     # left and right pod, from the centre of the fire pose
APEX = (110.0, -190.0)         # the arc's control point, from the pod
# target of launch i; the centre one (BIG_IMPACT) lands on frame 50, the heavy hit
TARGETS = [(360, 150), (680, 228), (520, 150), (360, 228), (680, 150), (360, 190), (520, 190), (680, 190), (520, 228)]
BIG_IMPACT = 6
MISSILE_SCALE = 0.6
BLAST_SCALE, BIG_BLAST_SCALE = 0.45, 0.9
BLAST_DURATIONS = [1, 2, 2, 2, 2, 2]              # frames each explosion picture stays
PUFF_SCALE = 0.8
SOUND = '{"type":"wav","res":"%s"}'
DROPPED_ANCHORS = {SOUND % "lunren"}              # the old blade-wheel sound has no place in a missile barrage


def ramp(keys):
    """Piecewise-linear value of (frame, value) keys, flat before the first and after the last."""
    def at(frame):
        if frame <= keys[0][0]:
            return keys[0][1]
        for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
            if frame <= f1:
                return au.lerp(v0, v1, (frame - f0) / (f1 - f0))
        return keys[-1][1]
    return at


def _smooth(keys):
    """Like `ramp` but eased between keys."""
    def at(frame):
        if frame <= keys[0][0]:
            return keys[0][1]
        for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
            if frame <= f1:
                return au.lerp(v0, v1, au.ease_both((frame - f0) / (f1 - f0)))
        return keys[-1][1]
    return at


def add_sprites(animation: sam.Sam, sprites_dir: Path, parts_dir: Path, out_parts: Path):
    """Copy the part PNGs and the new sprites to `out_parts`, name the sprites like atlas frames and
    register them in `animation`. Returns (animation, {sprite: (image id, width, height, pivot)})."""
    info = json.loads((sprites_dir / "sprites.json").read_text())["sprites"]
    out_parts.mkdir(parents=True, exist_ok=True)
    for path in parts_dir.glob("*.swf*.png"):
        shutil.copyfile(path, out_parts / path.name)
    registered, tags = {}, []
    for offset, name in enumerate(sorted(info)):
        frame_name = "ironman.swf%d.png" % (FIRST_NEW_FRAME + offset)
        shutil.copyfile(sprites_dir / info[name]["file"], out_parts / frame_name)
        image_id = FIRST_NEW_IMAGE_ID + offset
        tags.append(sam.Image(image_id, frame_name))
        registered[name] = (image_id, info[name]["width"], info[name]["height"], tuple(info[name]["pivot"]), frame_name)
    start = next(i for i, t in enumerate(animation.tags) if isinstance(t, sam.Label))
    return sam.Sam(animation.tags[:start] + tags + animation.tags[start:]), registered


def _hero_box(parts_dir: Path):
    """The idle hero's armor box in canvas pixels: left, top, right, bottom."""
    box = skill_sprites.idle_box(parts_dir)
    return tuple(v - sam_render.PAD for v in box)


def _place(sprite, x, y, scale, rot=0.0, sy=None):
    """Matrix that puts the sprite's pivot at (x, y); the game rotates and scales around the image centre."""
    _id, width, height, pivot, _name = sprite
    sy = scale if sy is None else sy
    dx, dy = (pivot[0] - width / 2) * scale, (pivot[1] - height / 2) * sy
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return au.make(x - (dx * c - dy * s), y - (dx * s + dy * c), scale, sy, rot)


def _add_hero(timeline, idle, names, body, sprites, box, launches):
    lift = _smooth(LIFT)
    left, top, right, bottom = box
    hero_x = (left + right) / 2

    def height(frame):
        bob = 3 * math.sin((frame - 20) * 0.55) if 20 <= frame <= 42 else 0.0
        return lift(frame) + bob

    def pulse(frame):
        return sum(math.exp(-(frame - launch) / 1.6) for launch in launches if frame >= launch)

    parts_alpha = ramp(PARTS_ALPHA)
    for depth, (char_id, z, matrix, _color) in idle.items():
        if depth == SHADOW_DEPTH or names[char_id] not in body:
            continue
        for frame in range(len(timeline)):
            alpha = round(parts_alpha(frame))
            if alpha > 2:
                timeline.set_item(frame, depth, au.Item(char_id, z, au.compose(au.make(0, height(frame)),
                                                                             au.from_tag(matrix)), alpha))
    for pose, keys in POSE_ALPHA.items():
        fade, sprite = ramp(keys), sprites["pose_" + pose]
        for frame in range(len(timeline)):
            alpha = round(fade(frame))
            if alpha <= 2:
                continue
            squash = {"crouch": 0.94, "rise": au.lerp(1.1, 1.0, min(1, max(0, (frame - 9) / 7))),
                      "charge": 1.0, "fire": 1.0 - 0.05 * pulse(frame), "descend": 1.0}[pose]
            widen = {"crouch": 1.04}.get(pose, 1.0 + 0.03 * pulse(frame) if pose == "fire" else 1.0)
            tilt = {"charge": 3 * math.sin(frame * 0.3), "fire": FIRE_TILT * min(1.0, 0.5 + pulse(frame)),
                    "descend": 3 * (1 - (frame - 50) / 14)}.get(pose, 0.0)
            scale = 1.0 / SUPERSAMPLE
            feet = bottom + height(frame)
            center_y = feet - sprite[2] * scale * squash / 2
            timeline.set_item(frame, POSE_DEPTH[pose], au.Item(
                sprite[0], 10 + POSE_DEPTH[pose],
                _place(sprite, hero_x, center_y, scale * widen, tilt, scale * squash), alpha))
    return hero_x, height


def _add_shadow_and_flame(timeline, idle, names, ids, height, box):
    left, top, right, bottom = box
    shadow_id, shadow_z, shadow_matrix, _ = idle[SHADOW_DEPTH]
    base = au.from_tag(shadow_matrix)
    flame = next((item for item in idle.values() if names[item[0]] == FLAME_PART), None)
    for frame in range(len(timeline)):
        rise = min(1.0, max(0.0, -height(frame) / -HOVER))
        matrix = au.compose(au.about((base[4], base[5]), au.make(sx=1 - 0.45 * rise)), base)
        timeline.set_item(frame, SHADOW_DEPTH, au.Item(shadow_id, shadow_z, matrix, round(au.OPAQUE * (1 - 0.35 * rise))))
        if flame is not None:
            airborne = ramp([(5, 0), (8, 256), (58, 256), (62, 0)])(frame)
            if airborne > 2:
                size = 1.0 + 0.6 * rise
                timeline.set_item(frame, FLAME_DEPTH, au.Item(
                    flame[0], FLAME_DEPTH, au.make((left + right) / 2, bottom + height(frame) + 14 * size, 1.0, size),
                    round(airborne)))


def _add_charge_glow(timeline, ids, hero_x, height, box):
    char = ids.get(GLOW_PART)
    if char is None:
        return
    bottom = box[3]
    for frame in range(18, 27):
        strength = math.sin((frame - 18) / 8 * math.pi)
        timeline.set_item(frame, GLOW_DEPTH, au.Item(
            char, GLOW_DEPTH, au.make(hero_x, bottom + height(frame) - 95, 0.35 + 0.5 * strength), round(256 * strength)))


def _missile_path(index, hero_x, height_at_launch, box):
    pod_x, pod_y = POD_OFFSETS[index % 2]
    bottom, top = box[3], box[1]
    center_y = bottom + height_at_launch - (bottom - top) / 2
    start = (hero_x + pod_x, center_y + pod_y)
    target = TARGETS[index]
    control = (start[0] + APEX[0] + 14 * (index % 3), start[1] + APEX[1] - 8 * (index % 3))
    return start, control, target


def _bezier(p0, p1, p2, t):
    u = 1 - t
    point = (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])
    slope = (2 * u * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0]), 2 * u * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1]))
    return point, math.degrees(math.atan2(slope[1], slope[0]))


def _add_missile(timeline, index, sprite, hero_x, height, box):
    launch = LAUNCH_FIRST + LAUNCH_STEP * index
    start, control, target = _missile_path(index, hero_x, height(launch), box)
    depth = MISSILE_DEPTH + index
    for step in range(FLIGHT):
        t = (step / (FLIGHT - 1)) ** 1.35
        (x, y), angle = _bezier(start, control, target, t)
        grow = MISSILE_SCALE * (0.55 + 0.45 * min(1.0, step / 3) + 0.25 * t)
        fade = min(256, round(256 * (step + 1) / 2))
        timeline.set_item(launch + step, depth, au.Item(sprite[0], depth, _place(sprite, x, y, grow, angle), fade))
    return launch + FLIGHT


def _add_puffs(timeline, index, puffs, hero_x, height, box):
    launch = LAUNCH_FIRST + LAUNCH_STEP * index
    start, _control, _target = _missile_path(index, hero_x, height(launch), box)
    for number, (first, last) in enumerate([(0, 1), (2, 3), (4, 6)]):
        sprite = puffs[number]
        for frame in range(launch + first, launch + last + 1):
            timeline.set_item(frame, PUFF_DEPTH + index, au.Item(
                sprite[0], PUFF_DEPTH + index, _place(sprite, start[0], start[1], PUFF_SCALE), 256 if number < 2 else 190))


def _add_explosion(timeline, index, frames, arrive):
    tx, ty = TARGETS[index]
    scale = BIG_BLAST_SCALE if index == BIG_IMPACT else BLAST_SCALE
    start = arrive
    for number, duration in enumerate(BLAST_DURATIONS):
        sprite = frames[number]
        end = start + duration - 1
        for frame in range(start - 1, end + 2):
            alpha = 256 if start <= frame <= end else 110
            timeline.set_item(frame, EXPLOSION_DEPTH + 10 * index + number, au.Item(
                sprite[0], EXPLOSION_DEPTH + ty + number, _place(sprite, tx, ty, scale), alpha))
        start = end + 1


def _anchors(animation, label):
    """The old section's anchors as (frame, text), frame counted inside the section."""
    out, frame, inside = [], 0, False
    for tag in animation.tags:
        if isinstance(tag, sam.Label):
            inside, frame = tag.name == label, 0
        elif inside and isinstance(tag, sam.Show):
            frame += 1
        elif inside and isinstance(tag, sam.Anchor):
            out.append((frame, tag.name))
    return out


def build(animation: sam.Sam, sprites: Dict[str, tuple], parts_dir: Path) -> sam.Sam:
    """The animation with `gongji4` replaced. `sprites` comes from `add_sprites`, which `animation` already went through."""
    first, last = animation.sections()[SECTION]
    length = last - first + 1
    displays = list(sam_render.frame_states(animation))
    names, ids = animation.images(), au.image_ids(animation)
    idle = displays[animation.sections()["daiji"][0]]
    body = art_kit.body_parts("ironman", parts_dir)
    box = _hero_box(parts_dir)
    timeline = au.Timeline(length)
    launches = [LAUNCH_FIRST + LAUNCH_STEP * i for i in range(len(TARGETS))]
    hero_x, height = _add_hero(timeline, idle, names, body, sprites, box, launches)
    _add_shadow_and_flame(timeline, idle, names, ids, height, box)
    _add_charge_glow(timeline, ids, hero_x, height, box)
    puffs = [sprites["puff_%d" % n] for n in (1, 2, 3)]
    blast = [sprites["explosion_%d" % n] for n in range(1, 7)]
    for index in range(len(TARGETS)):
        arrive = _add_missile(timeline, index, sprites["missile"], hero_x, height, box)
        _add_puffs(timeline, index, puffs, hero_x, height, box)
        _add_explosion(timeline, index, blast, arrive)
    for frame, text in _anchors(animation, SECTION):
        if text not in DROPPED_ANCHORS:
            timeline.anchor(frame, text)
    for frame in launches[::2]:
        timeline.anchor(frame, SOUND % "qiangsheng")
    for frame in (44, 47, 52, 55):
        timeline.anchor(frame, SOUND % "bao")
    tags = au.compile_section(SECTION, timeline, initial_depths=displays[first - 1])
    if au.frame_count(tags) != length:
        raise SystemExit("section length changed: %d != %d" % (au.frame_count(tags), length))
    return au.replace_section(animation, SECTION, tags)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--sprites", type=Path, default=Path("build/ironman_skill_sprites"))
    ap.add_argument("--parts", type=Path, default=Path("build/ironman_new/ironman"),
                    help="folder of the hero's part PNGs (the redrawn armor)")
    ap.add_argument("--scale", type=float, default=0.5)
    args = ap.parse_args(argv)
    shipped = sam.load(str(sam_render.ANIM_DIR / "ironman.swf.sam"))
    out_parts = args.out / "parts"
    prepared, sprites = add_sprites(shipped, args.sprites, args.parts, out_parts)
    animation = build(prepared, sprites, args.parts)
    args.out.mkdir(parents=True, exist_ok=True)
    sam.save(animation, str(args.out / "ironman.swf.sam"))
    (args.out / "new_frames.json").write_text(json.dumps({name: sprite[4] for name, sprite in sprites.items()}, indent=1))
    frames = sam_render.render_frames(animation, SECTION, out_parts, args.scale, window=(-330, -470, 950, 260))
    sam_render.save_gif(frames, animation.tags[0].fps, args.out / "preview.gif")
    frames[LAUNCH_FIRST + 22].save(args.out / "frame_impact.png")
    print(json.dumps({"frames": len(frames), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
