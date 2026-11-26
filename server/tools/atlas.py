"""Edit a Cocos2d-x sprite atlas (`.pvr.ccz` + `.plist`): swap frames, add frames.

    python3 -m tools.atlas ironman <anim dir of the APK> <folder of part PNGs> <new_frames.json> <out dir>

Reads `<name>-hd.pvr.ccz` and `<name>.plist`, replaces every frame whose PNG in the folder differs
from what the atlas holds (it keeps the frame's rectangle, and its rotation), appends the frames of
`new_frames.json` (a JSON object {label: frame name}, files read from the folder) in shelves to the
right of the old atlas, and writes the new `.pvr.ccz` and `.plist` to the out dir.

Format: CCZ ("CCZ!", u16 compression 0, u16 version 2, u32 0, u32 length big endian) around zlib
around PVR v2 (52 byte header) holding RGBA4444, one u16 per pixel as R<<12 | G<<8 | B<<4 | A.
Pixels the edit does not touch are written back exactly; new pixels get an ordered dither so the
16 levels per channel do not band.
"""

import argparse
import json
import plistlib
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image

CCZ_MAGIC = b"CCZ!"
PVR_HEADER = struct.Struct("<13I")
PVR_TAG = 0x21525650                # "PVR!"
FLAGS_RGBA4444 = 0x8010             # pixel format 0x10 with the alpha flag
MASKS = (0xF000, 0x0F00, 0x00F0, 0x000F)
PADDING = 2                         # px of extruded edge around every added frame
MAX_WIDTH = 2048                    # new frames never push the atlas past this width
GAP = 4                             # between the old atlas and the added frames
BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32)


class AtlasError(ValueError):
    pass


def decode_ccz(blob: bytes) -> Image.Image:
    if blob[:4] != CCZ_MAGIC:
        raise AtlasError("not a CCZ file")
    data = zlib.decompress(blob[16:])
    header, height, width, _mips, flags, _length, bpp = PVR_HEADER.unpack_from(data)[:7]
    if flags & 0xFF != 0x10 or bpp != 16:
        raise AtlasError("only RGBA4444 PVR is supported (flags %#x, %d bpp)" % (flags, bpp))
    pixels = np.frombuffer(data, dtype="<u2", count=width * height, offset=header).reshape(height, width)
    rgba = np.stack([((pixels >> shift) & 15) * 17 for shift in (12, 8, 4, 0)], axis=-1).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def encode_ccz(image: Image.Image, dither: Optional[np.ndarray] = None) -> bytes:
    """`dither` is a bool array, True where the pixels are new and should be dithered."""
    rgba = np.asarray(image.convert("RGBA")).astype(np.float32)
    height, width = rgba.shape[:2]
    levels = np.floor((rgba + 8) / 17).astype(np.int32)         # exact for values that are multiples of 17
    if dither is not None and dither.any():
        threshold = np.tile(BAYER, (height // 4 + 1, width // 4 + 1))[:height, :width] / 16 + 1 / 32
        dithered = np.floor(rgba / 17 + threshold[..., None]).astype(np.int32)
        levels = np.where(dither[..., None], dithered, levels)
    levels = np.clip(levels, 0, 15)
    levels[rgba[..., 3] == 0, 3] = 0
    packed = ((levels[..., 0] << 12) | (levels[..., 1] << 8) | (levels[..., 2] << 4) | levels[..., 3]).astype("<u2")
    body = packed.tobytes()
    pvr = PVR_HEADER.pack(52, height, width, 0, FLAGS_RGBA4444, len(body), 16, *MASKS, PVR_TAG, 1) + body
    return CCZ_MAGIC + struct.pack(">HHII", 0, 2, 0, len(pvr)) + zlib.compress(pvr, 9)


def frame_box(entry: dict) -> Tuple[int, int, int, int, bool]:
    """(x, y, width, height) of a frame as it lies in the atlas, and whether it is stored rotated."""
    x, y, w, h = [int(v) for v in re.findall(r"-?\d+", entry["frame"])]
    rotated = bool(entry.get("rotated"))
    return (x, y, h, w, True) if rotated else (x, y, w, h, False)


def drawn_size(entry: dict) -> Tuple[int, int]:
    """The size a frame has when drawn, which is what its PNG measures."""
    _x, _y, w, h, rotated = frame_box(entry)
    return (h, w) if rotated else (w, h)


def read_frame(atlas: Image.Image, entry: dict) -> Image.Image:
    x, y, w, h, rotated = frame_box(entry)
    part = atlas.crop((x, y, x + w, y + h))
    return part.rotate(90, expand=True) if rotated else part


def _stored(part: Image.Image, rotated: bool) -> Image.Image:
    return part.rotate(-90, expand=True) if rotated else part


def _same(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()


def _extruded(part: Image.Image) -> Image.Image:
    padded = np.pad(np.asarray(part.convert("RGBA")), ((PADDING, PADDING), (PADDING, PADDING), (0, 0)), mode="edge")
    return Image.fromarray(padded, "RGBA")


def _shelves(sizes: Dict[str, Tuple[int, int]], start_x: int, max_width: int):
    """name -> (x, y) of each frame's inner corner, packed in shelves, tallest first; and the used height."""
    placed, x, y, row = {}, start_x, 0, 0
    for name in sorted(sizes, key=lambda n: (-sizes[n][1], n)):
        w, h = sizes[name]
        if x + w + 2 * PADDING > max_width:
            x, y, row = start_x, y + row, 0
        placed[name] = (x + PADDING, y + PADDING)
        x, row = x + w + 2 * PADDING, max(row, h + 2 * PADDING)
    return placed, y + row


def repack(atlas: Image.Image, plist: dict, replace: Dict[str, Image.Image], add: Dict[str, Image.Image],
           max_width: int = MAX_WIDTH):
    """(new atlas, new plist, dither mask). `replace` keeps rectangle and rotation; `add` goes to the right."""
    frames = plist["frames"]
    for name, part in replace.items():
        if name not in frames:
            raise AtlasError("%s is not a frame of the atlas" % name)
        if drawn_size(frames[name]) != part.size:
            raise AtlasError("%s must keep its size %s, got %s" % (name, drawn_size(frames[name]), part.size))
    for name in add:
        if name in frames:
            raise AtlasError("%s is already a frame" % name)
    placed, shelf_height = _shelves({n: im.size for n, im in add.items()}, atlas.width + GAP, max_width) \
        if add else ({}, 0)
    width = max([atlas.width] + [placed[n][0] + add[n].width + PADDING for n in add])
    height = max(atlas.height, shelf_height)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(atlas, (0, 0))
    dither = np.zeros((height, width), dtype=bool)
    for name, part in replace.items():
        x, y, w, h, rotated = frame_box(frames[name])
        canvas.paste(_stored(part.convert("RGBA"), rotated), (x, y))
        dither[y:y + h, x:x + w] = True
    new_frames = dict(frames)
    for name, part in add.items():
        x, y = placed[name]
        canvas.paste(_extruded(part), (x - PADDING, y - PADDING))
        dither[y - PADDING:y + part.height + PADDING, x - PADDING:x + part.width + PADDING] = True
        new_frames[name] = {"frame": "{{%d,%d},{%d,%d}}" % (x, y, part.width, part.height), "offset": "{0,0}",
                            "rotated": False, "sourceColorRect": "{{0,0},{%d,%d}}" % (part.width, part.height),
                            "sourceSize": "{%d,%d}" % (part.width, part.height)}
    metadata = dict(plist["metadata"], size="{%d,%d}" % (width, height))
    return canvas, dict(plist, frames=new_frames, metadata=metadata), dither


def _load_png(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def edit(name: str, anim_dir: Path, parts_dir: Path, new_frames: Dict[str, str], out_dir: Path) -> dict:
    atlas = decode_ccz((anim_dir / (name + "-hd.pvr.ccz")).read_bytes())
    plist = plistlib.loads((anim_dir / (name + ".plist")).read_bytes())
    replace = {}
    for frame_name, entry in plist["frames"].items():
        path = parts_dir / frame_name
        if path.exists():
            part = _load_png(path)
            if not _same(part, read_frame(atlas, entry)):
                replace[frame_name] = part
    add = {frame_name: _load_png(parts_dir / frame_name) for frame_name in new_frames.values()}
    canvas, new_plist, dither = repack(atlas, plist, replace, add)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / (name + "-hd.pvr.ccz")).write_bytes(encode_ccz(canvas, dither))
    (out_dir / (name + ".plist")).write_bytes(plistlib.dumps(new_plist, fmt=plistlib.FMT_XML))
    return {"replaced": sorted(replace), "added": sorted(add), "size": canvas.size}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name")
    ap.add_argument("anim_dir", type=Path)
    ap.add_argument("parts_dir", type=Path)
    ap.add_argument("new_frames", type=Path, help="JSON {label: frame name} of the frames to add")
    ap.add_argument("out_dir", type=Path)
    args = ap.parse_args(argv)
    result = edit(args.name, args.anim_dir, args.parts_dir, json.loads(args.new_frames.read_text()), args.out_dir)
    print("replaced %d frames, added %d, atlas %dx%d" % (len(result["replaced"]), len(result["added"]), *result["size"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
