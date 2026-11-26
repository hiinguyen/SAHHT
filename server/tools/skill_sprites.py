"""Cut the sprites for a new skill out of the three sheets an image AI drew.

    python3 -m tools.skill_sprites build/ironman_skill_kit/generated build/ironman_skill_sprites

reads `pose.png` (hero poses on flat grey), `explosion.png` (6 frames on black) and `missile.png`
(a missile and 3 launch puffs on black), and writes one PNG per sprite plus `sprites.json`:
name -> {file, width, height, pivot}. Poses are made at POSE_SUPERSAMPLE times their size on
screen (the animation draws them with a matrix scale of 1 / POSE_SUPERSAMPLE); effects are 1:1.

Poses are cut out of the grey by flood fill. Effects are keyed from the black: the brightest
channel becomes the alpha and the color is divided by it, so over black they look exactly like the
original and fire and glow keep their color at any alpha.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

import numpy as np
from PIL import Image, ImageChops, ImageFilter

from tools import art_kit, sam, sam_render

POSE_SUPERSAMPLE = 2
POSE_ROWS = [2, 3]                 # the AI draws the 5 poses as 2 + 3
POSE_NAMES = ["crouch", "rise", "charge", "fire", "descend"]
HOVER_POSES = (2, 3, 4)            # drawn at the body size of the idle hero: they set the scale of all poses
EXPLOSION_GRID = (3, 2)            # columns, rows
EXPLOSION_WIDTH = 360              # px of the widest frame
MISSILE_BODY = 120                 # px, the body without the trail
BODY_SPAN = 0.92 - 0.51            # the missile body is this share of the AI image width
MISSILE_PIVOT = 0.72               # the body centre sits at this fraction of the image width
PUFF_COUNT = 3
PUFF_WIDTH = 100
PUFF_MIN_SHARE = 0.15              # a blob smaller than this share of the biggest puff is a label, not a puff
KEY_GAIN = 1.6
KEY_FLOOR = 0.04
VISIBLE = 30                       # alpha (0-255) above which a pixel counts as part of an effect
GROUP_SCALE = 6                    # masks are shrunk by this to find the main blob of an effect cell
GROUP_GROW = 5                     # and grown by this many shrunk pixels so specks join their blob
WATERMARK = (0.785, 0.85, 0.88, 0.905)   # where the AI's sparkle sits, as fractions (left, top, right, bottom)
NEUTRAL_SPREAD = 28                # max-min channel spread of a grey pixel
TUBE_SHARE = 0.32                  # the tube is the left part of the puff; warm smoke elsewhere stays
TUBE_MAX = 240                     # the launch tube is khaki and dull; the flame's white-gold core is brighter
EDGE_FADE = 0.12                   # share of a frame's width faded out where it was cut by the cell edge


class SpriteError(SystemExit):
    pass


def key_black(image: Image.Image) -> Image.Image:
    """RGBA from a picture on black: alpha from the brightest channel, color divided by it."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    bright = rgb.max(axis=-1)
    alpha = np.clip((bright - KEY_FLOOR) * KEY_GAIN / (1 - KEY_FLOOR), 0.0, 1.0)
    color = np.clip(rgb / np.maximum(alpha, 1e-4)[..., None], 0.0, 1.0)
    color[alpha <= 0] = 0
    return Image.fromarray((np.dstack([color, alpha]) * 255 + 0.5).astype(np.uint8), "RGBA")


def _groups(alpha: Image.Image, keep: int):
    """The `keep` biggest groups of visible pixels (nearby specks join their group), boxes at full size."""
    small = alpha.point(lambda v: 255 if v > VISIBLE else 0).resize(
        (max(1, alpha.width // GROUP_SCALE), max(1, alpha.height // GROUP_SCALE)))
    grown = small.filter(ImageFilter.MaxFilter(GROUP_GROW))
    found = sorted(art_kit.blobs(grown), key=lambda g: -g["area"])[:keep]
    return [{"area": g["area"], "box": tuple(v * GROUP_SCALE for v in g["box"])} for g in found]


def erase_watermark(sheet: Image.Image, background: tuple) -> Image.Image:
    """Paint the AI's sparkle out. On black the whole box is cleared except colored pixels (embers);
    on grey only light neutral pixels go, so the hero's dark armor next to it stays."""
    data = np.asarray(sheet.convert("RGB")).copy()
    height, width = data.shape[:2]
    left, top = int(WATERMARK[0] * width), int(WATERMARK[1] * height)
    right, bottom = int(WATERMARK[2] * width), int(WATERMARK[3] * height)
    region = data[top:bottom, left:right]
    levels = region.astype(np.int16)
    neutral = (levels.max(axis=-1) - levels.min(axis=-1)) <= NEUTRAL_SPREAD
    if max(background) > 0:
        neutral &= levels.min(axis=-1) >= 150
    region[neutral] = background
    return Image.fromarray(data, "RGB")


def _fade_cut_edges(image: Image.Image, cell_width: int, box) -> Image.Image:
    """Fade the side of a frame that was cut off by the edge of its cell."""
    alpha = np.asarray(image.getchannel("A")).astype(np.float32)
    width = alpha.shape[1]
    ramp = max(2, int(width * EDGE_FADE))
    fade = np.ones(width, dtype=np.float32)
    if box[2] >= cell_width - 3:
        fade[-ramp:] = np.linspace(1.0, 0.0, ramp)
    if box[0] <= 2:
        fade[:ramp] = np.linspace(0.0, 1.0, ramp)
    out = image.copy()
    out.putalpha(Image.fromarray((alpha * fade[None, :]).astype(np.uint8), "L"))
    return out


def _main_box(alpha: Image.Image, what: str) -> tuple:
    found = _groups(alpha, 1)
    if not found:
        raise SpriteError("%s is empty" % what)
    return found[0]["box"]


def _inside(image: Image.Image, box) -> Image.Image:
    """`image` with the alpha cleared everywhere outside `box`."""
    alpha = image.getchannel("A")
    kept = Image.new("L", alpha.size, 0)
    kept.paste(alpha.crop(box), box[:2])
    out = image.copy()
    out.putalpha(kept)
    return out


def _trim_box(image: Image.Image, group) -> tuple:
    """Where the visible part of `image` inside `group` starts and ends (cell coordinates)."""
    box = _inside(image, group).getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    return box if box else group


def _trim(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    if box is None:
        raise SpriteError("an effect cell is empty")
    return image.crop(box)


def _scaled(image: Image.Image, factor: float) -> Image.Image:
    return image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), Image.LANCZOS)


def extract_poses(sheet: Image.Image, idle_height: float) -> List[Image.Image]:
    """The 5 poses in storyboard order, scaled so a hovering pose is `idle_height * POSE_SUPERSAMPLE` tall."""
    found = sorted(art_kit.blobs(art_kit.foreground(sheet)), key=lambda b: -b["area"])[:len(POSE_NAMES)]
    if len(found) < len(POSE_NAMES):
        raise SpriteError("found %d poses on the sheet, expected %d" % (len(found), len(POSE_NAMES)))
    crops = [art_kit.crop_blob(sheet, blob) for blob in art_kit.by_slot(found, POSE_ROWS)]
    hover = sum(crops[i].height for i in HOVER_POSES) / len(HOVER_POSES)
    return [_scaled(crop, idle_height * POSE_SUPERSAMPLE / hover) for crop in crops]


def extract_explosion(sheet: Image.Image) -> List[Image.Image]:
    """The 6 frames in time order, at one common scale, each cropped to its own box."""
    keyed = key_black(sheet)
    cols, rows = EXPLOSION_GRID
    frames = []
    for row in range(rows):
        for col in range(cols):
            box = (col * sheet.width // cols, row * sheet.height // rows,
                   (col + 1) * sheet.width // cols, (row + 1) * sheet.height // rows)
            cell = keyed.crop(box)
            group = _main_box(cell.getchannel("A"), "explosion frame %d" % (row * cols + col + 1))
            frames.append(_fade_cut_edges(_trim(_inside(cell, group)), cell.width, _trim_box(cell, group)))
    factor = EXPLOSION_WIDTH / max(frame.width for frame in frames)
    return [_scaled(frame, factor) for frame in frames]


def _remove_olive(image: Image.Image) -> Image.Image:
    """Drop the olive launch tube the AI drew around the muzzle flash."""
    data = np.asarray(image).astype(np.int16)
    tube = (data[..., 1] >= data[..., 0] * 0.9) & (data[..., 1] > data[..., 2] + 12) & (data[..., :3].max(axis=-1) < TUBE_MAX)
    tube[:, int(data.shape[1] * TUBE_SHARE):] = False
    data[tube, 3] = 0
    return Image.fromarray(data.astype(np.uint8), "RGBA")


def extract_missile(sheet: Image.Image):
    """(missile, puffs). The missile points right with its trail behind; it is padded on the right so
    that its body is the image centre, which is where the game rotates it."""
    keyed = key_black(sheet)
    half = sheet.height // 2
    upper = keyed.crop((0, 0, sheet.width, half))
    missile = _trim(_inside(upper, _main_box(upper.getchannel("A"), "the missile")))
    missile = _scaled(missile, MISSILE_BODY / (missile.width * BODY_SPAN))
    padded = Image.new("RGBA", (missile.width + round(missile.width * (2 * MISSILE_PIVOT - 1)), missile.height),
                       (0, 0, 0, 0))
    padded.paste(missile, (0, 0))
    lower = keyed.crop((0, half, sheet.width, sheet.height))
    candidates = sorted(_groups(lower.getchannel("A"), PUFF_COUNT + 2), key=lambda g: -g["area"])
    found = [g for g in candidates if g["area"] >= PUFF_MIN_SHARE * candidates[0]["area"]][:PUFF_COUNT]
    if len(found) < PUFF_COUNT:
        raise SpriteError("found %d launch puffs, expected %d" % (len(found), PUFF_COUNT))
    puffs = [_remove_olive(_trim(_inside(lower, group["box"]))) for group in sorted(found, key=lambda g: g["box"][0])]
    widest = max(puff.width for puff in puffs)
    return padded, [_scaled(puff, PUFF_WIDTH / widest) for puff in puffs]


def idle_height(parts_dir: Path, animation_name: str = "ironman") -> float:
    """Height in canvas pixels of the hero's armor in its idle pose (shadow and flame left out), measured on a render."""
    animation = sam.load(str(sam_render.ANIM_DIR / (animation_name + ".swf.sam")))
    display = list(sam_render.frame_states(animation))[animation.sections()["daiji"][0]]
    body = art_kit.body_parts(animation_name, parts_dir)
    names = animation.images()
    armor = {depth: item for depth, item in display.items() if names[item[0]] in body}
    frame = sam_render.render_frame(animation, armor, parts_dir, scale=1).convert("RGB")
    flat = Image.new("RGB", frame.size, sam_render.BACKGROUND[:3])
    box = ImageChops.difference(frame, flat).convert("L").point(lambda v: 255 if v > 8 else 0).getbbox()
    return float(box[3] - box[1])


def extract_all(generated: Path, out: Path, parts_dir: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sprites = {}

    def save(name, image, pivot):
        image.save(out / (name + ".png"))
        sprites[name] = {"file": name + ".png", "width": image.width, "height": image.height,
                         "pivot": [round(pivot[0], 1), round(pivot[1], 1)]}

    with Image.open(generated / "pose.png") as sheet:
        clean = erase_watermark(sheet, art_kit.BACKGROUND)
        for name, image in zip(POSE_NAMES, extract_poses(clean, idle_height(parts_dir))):
            save("pose_" + name, image, (image.width / 2, image.height / 2))
    with Image.open(generated / "explosion.png") as sheet:
        for index, image in enumerate(extract_explosion(erase_watermark(sheet, (0, 0, 0))), 1):
            save("explosion_%d" % index, image, (image.width / 2, image.height))
    with Image.open(generated / "missile.png") as sheet:
        missile, puffs = extract_missile(sheet.convert("RGB"))
    save("missile", missile, (missile.width * MISSILE_PIVOT, missile.height / 2))
    for index, image in enumerate(puffs, 1):
        save("puff_%d" % index, image, (image.width / 2, image.height / 2))
    (out / "sprites.json").write_text(json.dumps({"pose_supersample": POSE_SUPERSAMPLE, "sprites": sprites}, indent=1))
    return sprites


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("generated", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--parts", type=Path, default=Path("build/ironman_new/ironman"),
                    help="folder of the hero's current part PNGs (to size the poses like his idle pose)")
    args = ap.parse_args(argv)
    for name, info in extract_all(args.generated, args.out, args.parts).items():
        print("%-14s %4d x %4d  pivot %s" % (name, info["width"], info["height"], info["pivot"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
