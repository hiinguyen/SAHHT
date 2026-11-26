"""Iron Man's new ultimate (skill 3830): a rain of missiles on every enemy.

It replaces the section `gongji4` of `ironman.swf.sam` (the old one lifts a giant bomb). The new
section keeps the old length and the old hit anchors (the sounds, the screen shake, `beiji` and the
three `bao` damage ticks at frames 50, 53 and 56), so the Lua script `ironman_s3` and the server
need no change. Everything is drawn from the hero's own body parts and the existing missile and
explosion sprites.

    python3 -m tools.ironman_missile_rain build/ironman_rain [--parts build/ironman_new/ironman]

writes `<out>/ironman.swf.sam`, `<out>/preview.gif` and `<out>/frame_impact.png`.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from tools import sam, sam_author as au, sam_render

SECTION = "gongji4"
HERO_PIVOT = (75.0, 105.0)           # the idle hero's centre in canvas pixels
HOVER_Y = -190.0                     # how high the hero rises
MISSILE_PART = "ironman.swf204.png"  # the old bomb prop, used small
FLASH_PART = "ironman.swf80.png"     # white-gold star flare, the muzzle flash
EXPLOSION_CENTER = (507.0, 192.0)    # where the old bomb exploded, in canvas pixels
EXPLOSION_FIRST, EXPLOSION_LAST = 50, 60   # frames of the old explosion that are reused
LAUNCH_FIRST, LAUNCH_STEP, FLIGHT = 28, 2, 14
RISE_FRAMES = 5                      # of the flight, climbing before the dive
APEX_HEIGHT = -250.0
SHOULDERS = ((50.0, HOVER_Y - 22), (108.0, HOVER_Y - 28))   # launch points, left and right pod
TARGETS = [(360, 150), (520, 150), (680, 150), (360, 190), (520, 190), (680, 190),
           (360, 228), (520, 228), (680, 228)]
BIG_IMPACT = 4                       # lands on frame 50, the heavy hit
SMALL_SCALE, BIG_SCALE = 0.22, 0.4
BLAST_DEPTHS = (26, 27, 28, 29)       # crack, two shock rings and the fireball; the dark debris (30) is left out
SOUND = '{"type":"wav","res":"%s"}'
DROPPED_ANCHORS = {SOUND % "lunren"}  # the old blade-wheel sound has no place in a missile barrage
MISSILE_DEPTH, FLASH_DEPTH, EXPLOSION_DEPTH = 40, 60, 100


def _scalar(keys, frame, ease=au.ease_both):
    frames = sorted(keys)
    if frame <= frames[0]:
        return keys[frames[0]]
    for f0, f1 in zip(frames, frames[1:]):
        if frame <= f1:
            return au.lerp(keys[f0], keys[f1], ease((frame - f0) / (f1 - f0)))
    return keys[frames[-1]]


HERO_Y = {0: 0, 5: 6, 16: HOVER_Y, 46: HOVER_Y, 60: 0, 64: 0}
HERO_ROT = {0: -6, 5: -10, 16: -4, 26: -6, 46: 4, 60: 0, 64: 0}
HERO_SY = {0: 1.0, 5: 0.93, 8: 1.0}


def _hero_transform(frame, launches):
    bob = 3 * math.sin((frame - 18) * 0.6) if 18 <= frame <= 46 else 0.0
    recoil = sum(-4 * math.exp(-(frame - launch) / 1.5) * (1 if i % 2 else -1)
                 for i, launch in enumerate(launches) if frame >= launch)
    return au.about(HERO_PIVOT, au.make(recoil, _scalar(HERO_Y, frame) + bob, 1.0,
                                        _scalar(HERO_SY, frame), _scalar(HERO_ROT, frame)))


def _add_hero(timeline, idle, launches):
    """The idle pose's parts moved as one body; the shadow stays on the ground and shrinks."""
    for depth, (char_id, z, matrix, _color) in idle.items():
        if depth == 1:
            continue
        for frame in range(len(timeline)):
            timeline.set_item(frame, depth, au.Item(
                char_id, z, au.compose(_hero_transform(frame, launches), au.from_tag(matrix))))
    shadow_id, shadow_z, shadow_matrix, _ = idle[1]
    base = au.from_tag(shadow_matrix)
    for frame in range(len(timeline)):
        height = _scalar(HERO_Y, frame) / HOVER_Y
        matrix = au.compose(au.about((base[4], base[5]), au.make(sx=1 - 0.45 * height)), base)
        timeline.set_item(frame, 1, au.Item(shadow_id, shadow_z, matrix, round(au.OPAQUE * (1 - 0.35 * height))))


def _add_missile(timeline, index, ids):
    launch = LAUNCH_FIRST + LAUNCH_STEP * index
    arrive = launch + FLIGHT
    sx, sy = SHOULDERS[index % 2]
    tx, ty = TARGETS[index]
    apex = (sx + 70 + 12 * (index % 3), APEX_HEIGHT + 6 * (index % 3))
    dive = math.degrees(math.atan2(ty - apex[1], tx - apex[0]))
    depth, char = MISSILE_DEPTH + index, ids[MISSILE_PART]
    at_apex = {"x": apex[0], "y": apex[1], "sx": 1.1, "rot": -8}
    timeline.track(depth, char, depth, {launch: {"x": sx, "y": sy, "sx": 0.5, "rot": -55, "alpha": 0},
                                        launch + 1: {"alpha": 256, "sx": 0.9},
                                        launch + RISE_FRAMES: at_apex}, ease=au.ease_out)
    timeline.track(depth, char, depth, {launch + RISE_FRAMES: at_apex,
                                        arrive - 1: {"x": tx, "y": ty, "sx": 1.0, "rot": dive}}, ease=au.ease_in)
    return arrive


def _add_flash(timeline, index, ids):
    launch = LAUNCH_FIRST + LAUNCH_STEP * index
    sx, sy = SHOULDERS[index % 2]
    depth = FLASH_DEPTH + index
    timeline.track(depth, ids[FLASH_PART], depth,
                   {launch: {"x": sx, "y": sy, "sx": 0.5, "alpha": 256},
                    launch + 3: {"x": sx, "y": sy, "sx": 1.1, "alpha": 0}}, ease=au.ease_out)


def _add_explosion(timeline, displays, section_first, index, arrive):
    tx, ty = TARGETS[index]
    big = index == BIG_IMPACT
    scale = BIG_SCALE if big else SMALL_SCALE
    transform = au.compose(au.make(tx, ty, scale), au.make(-EXPLOSION_CENTER[0], -EXPLOSION_CENTER[1]))
    timeline.copy_clip(displays, section_first + EXPLOSION_FIRST, section_first + EXPLOSION_LAST, start=arrive,
                       transform=transform, depth_base=EXPLOSION_DEPTH + 10 * index,
                       keep=lambda depth, item: depth in BLAST_DEPTHS, fade_from=58)


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


def build(animation: sam.Sam) -> sam.Sam:
    first, last = animation.sections()[SECTION]
    length = last - first + 1
    displays = list(sam_render.frame_states(animation))
    ids = au.image_ids(animation)
    idle = displays[animation.sections()["daiji"][0]]
    timeline = au.Timeline(length)
    launches = [LAUNCH_FIRST + LAUNCH_STEP * i for i in range(len(TARGETS))]
    _add_hero(timeline, idle, launches)
    for index in range(len(TARGETS)):
        arrive = _add_missile(timeline, index, ids)
        _add_flash(timeline, index, ids)
        _add_explosion(timeline, displays, first, index, arrive)
    for frame, text in _anchors(animation, SECTION):
        if text not in DROPPED_ANCHORS:
            timeline.anchor(frame, text)
    for frame in launches[::2]:
        timeline.anchor(frame, SOUND % "qiangsheng")
    for frame in (44, 47, 52, 55):
        timeline.anchor(frame, SOUND % "bao")
    tags = au.compile_section(SECTION, timeline)
    if au.frame_count(tags) != length:
        raise SystemExit("section length changed: %d != %d" % (au.frame_count(tags), length))
    return au.replace_section(animation, SECTION, tags)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--parts", type=Path, help="folder of part PNGs for the preview (default: the shipped ones)")
    ap.add_argument("--scale", type=float, default=0.5)
    args = ap.parse_args(argv)
    animation = build(sam.load(str(sam_render.ANIM_DIR / "ironman.swf.sam")))
    args.out.mkdir(parents=True, exist_ok=True)
    sam.save(animation, str(args.out / "ironman.swf.sam"))
    frames = sam_render.render_frames(animation, SECTION, args.parts or sam_render.PARTS_DIR / "ironman",
                                      args.scale, window=(-330, -470, 950, 260))
    sam_render.save_gif(frames, animation.tags[0].fps, args.out / "preview.gif")
    frames[LAUNCH_FIRST + 22].save(args.out / "frame_impact.png")
    print(json.dumps({"frames": len(frames), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
