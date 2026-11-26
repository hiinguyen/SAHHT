"""Hand a hero's part images to an image AI, then take the redrawn sheets back.

    python3 -m tools.art_kit export ironman build/ironman_kit
    python3 -m tools.art_kit import ironman build/ironman_kit build/ironman_new/ironman

`export` packs every part PNG of `characters/<name>/` onto grid sheets (flat
grey background, parts enlarged to help the AI) and writes `manifest.json`.
`import` reads the redrawn sheets from `<kit>/redrawn/` (same stem, any image
type and size, same grid), cuts each part out of its cell and fits it into the
opaque box of the old part, centred on it, so sizes and pivots keep the
animation working. The output folder holds every original part with the
redrawn ones replaced, ready for `tools.sam_render --parts`.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from tools import sam, sam_render

CELL = 384
COLS, ROWS = 5, 4
FILL = 360          # largest side a part may take inside a cell
MAX_SCALE = 4
BACKGROUND = (200, 200, 200)
PER_SHEET = COLS * ROWS
SHEET_SIZE = (COLS * CELL, ROWS * CELL)


NORMAL_SECTIONS = ("dengchang", "qianjin", "tibu", "houtui", "beiji1", "beiji2", "daiji", "shuaidao",
                   "siwang", "shengli")


def _load(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


SOLID_ALPHA = 230
MIN_SOLID = 0.6     # armor is mostly opaque; glows, shadows and flashes are soft
MAX_LUMA = 200      # ...and not near white


def _is_armor(path: Path) -> bool:
    pixels = [p for p in _load(path).getdata() if p[3] > 0]
    solid = [p for p in pixels if p[3] >= SOLID_ALPHA]
    if not pixels or len(solid) / len(pixels) < MIN_SOLID:
        return False
    return sum((r * 3 + g * 6 + b) / 10 for r, g, b, _ in solid) / len(solid) < MAX_LUMA


def body_parts(name: str, parts_dir: Path = None):
    """Opaque armor parts drawn in the everyday actions (the hero's own body).

    Everything else (glows, shadows, skill props, bursts) is `other`."""
    parts_dir = parts_dir or sam_render.PARTS_DIR / name
    animation = sam.load(str(sam_render.ANIM_DIR / (name + ".swf.sam")))
    names, ranges = animation.images(), animation.sections()
    displays = list(sam_render.frame_states(animation))
    used = set()
    for section in NORMAL_SECTIONS:
        if section in ranges:
            first, last = ranges[section]
            used.update(names[v[0]] for i in range(first, last + 1) for v in displays[i].values())
    return {n for n in used if _is_armor(parts_dir / n)}


def _part_files(parts_dir: Path, only=None):
    files = [p for p in parts_dir.glob("*.swf*.png")
             if re.search(r"swf\d+\.png$", p.name) and (only is None or p.name in only)]
    sizes = {p: _load(p).size for p in files}
    return sorted(files, key=lambda p: (-sizes[p][0] * sizes[p][1], p.name))


def layout(parts_dir: Path, only=None):
    """The manifest entries, one per part, in sheet order."""
    entries = []
    for index, path in enumerate(_part_files(parts_dir, only)):
        w, h = _load(path).size
        slot = index % PER_SHEET
        entries.append({
            "part": path.name, "w": w, "h": h,
            "scale": min(MAX_SCALE, FILL / max(w, h)),
            "sheet": "sheet_%02d.png" % (index // PER_SHEET + 1),
            "col": slot % COLS, "row": slot // COLS,
        })
    return entries


def _part_box(entry):
    """Where the enlarged part sits on its sheet: (left, top, width, height)."""
    width = max(1, round(entry["w"] * entry["scale"]))
    height = max(1, round(entry["h"] * entry["scale"]))
    left = entry["col"] * CELL + (CELL - width) // 2
    top = entry["row"] * CELL + (CELL - height) // 2
    return left, top, width, height


def _group_names(name: str, parts_dir: Path, group: str):
    if group == "all":
        return None
    body = body_parts(name, parts_dir)
    if group == "body":
        return body
    return {p.name for p in parts_dir.glob("*.swf*.png")} - body


def export(name: str, out: Path, parts_dir: Path = None, group: str = "body"):
    parts_dir = parts_dir or sam_render.PARTS_DIR / name
    entries = layout(parts_dir, _group_names(name, parts_dir, group))
    sheets = {}
    for entry in entries:
        sheet = sheets.setdefault(entry["sheet"], Image.new("RGB", SHEET_SIZE, BACKGROUND))
        left, top, width, height = _part_box(entry)
        big = _load(parts_dir / entry["part"]).resize((width, height), Image.LANCZOS)
        sheet.paste(big, (left, top), big)
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    for sheet_name, image in sheets.items():
        image.save(out / "sheets" / sheet_name)
    (out / "manifest.json").write_text(json.dumps(
        {"animation": name, "cell": CELL, "cols": COLS, "rows": ROWS, "parts": entries}, indent=1))
    return entries


MARKER = (255, 0, 255)
BACKGROUND_TOLERANCE = 45     # summed per-channel distance from the sheet's background colour
BORDER_STEP = 6
MIN_PART_AREA = 150           # smaller blobs are specks or a watermark, not parts
JOIN_DISTANCE = 24            # a small blob this close to a part belongs to it (antenna, glove tips)


def _border_points(width: int, height: int):
    for x in range(0, width, BORDER_STEP):
        yield x, 0
        yield x, height - 1
    for y in range(0, height, BORDER_STEP):
        yield 0, y
        yield width - 1, y


def _foreground(sheet: Image.Image) -> Image.Image:
    """Mask (255 = part) of everything that is not the flat background around the parts.

    The background is found by flood fill from the sheet border, so light pixels inside a
    part's outline are kept."""
    sheet = sheet.convert("RGB")
    marked = sheet.copy()
    reference = marked.copy()
    for point in _border_points(*sheet.size):
        seed = reference.getpixel(point)
        if marked.getpixel(point) != MARKER and sum(abs(c - b) for c, b in zip(seed, BACKGROUND)) <= 90:
            ImageDraw.floodfill(marked, point, MARKER, thresh=BACKGROUND_TOLERANCE)
    red, green, blue = marked.split()
    is_background = ImageChops.multiply(ImageChops.multiply(
        red.point(lambda v: 255 if v == 255 else 0),
        green.point(lambda v: 255 if v == 0 else 0)), blue.point(lambda v: 255 if v == 255 else 0))
    return ImageChops.invert(is_background).filter(ImageFilter.MinFilter(3))


def _blobs(mask: Image.Image):
    """Connected blobs of a mask as dicts with their pixel indexes, area and bounding box."""
    width, height = mask.size
    data = mask.tobytes()
    seen = bytearray(len(data))
    blobs = []
    for start in range(len(data)):
        if not data[start] or seen[start]:
            continue
        stack, pixels = [start], []
        seen[start] = 1
        while stack:
            index = stack.pop()
            pixels.append(index)
            x, y = index % width, index // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbour = ny * width + nx
                    if data[neighbour] and not seen[neighbour]:
                        seen[neighbour] = 1
                        stack.append(neighbour)
        xs, ys = [i % width for i in pixels], [i // width for i in pixels]
        blobs.append({"pixels": pixels, "area": len(pixels),
                      "box": (min(xs), min(ys), max(xs) + 1, max(ys) + 1)})
    return blobs


def _gap(a, b) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return (dx * dx + dy * dy) ** 0.5


def _merge_specks(blobs):
    """Attach small blobs to the nearest part within JOIN_DISTANCE, drop the rest."""
    parts = [b for b in blobs if b["area"] >= MIN_PART_AREA]
    for small in (b for b in blobs if b["area"] < MIN_PART_AREA):
        near = min(parts, key=lambda p: _gap(p["box"], small["box"]), default=None)
        if near is not None and _gap(near["box"], small["box"]) <= JOIN_DISTANCE:
            near["pixels"] = near["pixels"] + small["pixels"]
            near["box"] = (min(near["box"][0], small["box"][0]), min(near["box"][1], small["box"][1]),
                           max(near["box"][2], small["box"][2]), max(near["box"][3], small["box"][3]))
    return parts


def _by_slot(parts, row_sizes):
    """Rows by vertical position, left to right inside a row, in manifest order.

    `row_sizes` is the number of parts expected per row; extra blobs at the end of a row
    (a watermark in the empty cell) are ignored."""
    centres = sorted(parts, key=lambda p: (p["box"][1] + p["box"][3]) / 2)
    if len(centres) < sum(row_sizes):
        raise SystemExit("found %d parts on the sheet, expected %d: ask the AI to keep every part "
                         "separate and on the grid" % (len(centres), sum(row_sizes)))
    # split into rows at the largest vertical gaps between part centres
    ys = [(p["box"][1] + p["box"][3]) / 2 for p in centres]
    gaps = sorted(range(1, len(ys)), key=lambda i: ys[i] - ys[i - 1], reverse=True)[:len(row_sizes) - 1]
    cuts = [0] + sorted(gaps) + [len(centres)]
    rows = [sorted(centres[a:b], key=lambda p: p["box"][0]) for a, b in zip(cuts, cuts[1:])]
    ordered = []
    for row, size in zip(rows, row_sizes):
        if len(row) < size:
            raise SystemExit("a row has %d parts, expected %d: the AI broke the grid" % (len(row), size))
        ordered.extend(row[:size])
    return ordered


def _crop(sheet: Image.Image, blob) -> Image.Image:
    mask = bytearray(sheet.width * sheet.height)
    for index in blob["pixels"]:
        mask[index] = 255
    alpha = Image.frombytes("L", sheet.size, bytes(mask))
    cut = sheet.convert("RGBA")
    cut.putalpha(alpha)
    return cut.crop(blob["box"])


def _fit(cut: Image.Image, original: Image.Image) -> Image.Image:
    """Scale `cut` to sit inside the opaque box of `original`, centred on it, on a canvas of its size."""
    box = original.getchannel("A").getbbox() or (0, 0) + original.size
    target_w, target_h = box[2] - box[0], box[3] - box[1]
    scale = min(target_w / cut.width, target_h / cut.height)
    size = (max(1, round(cut.width * scale)), max(1, round(cut.height * scale)))
    placed = cut.resize(size, Image.LANCZOS)
    canvas = Image.new("RGBA", original.size, (0, 0, 0, 0))
    canvas.paste(placed, (box[0] + (target_w - size[0]) // 2, box[1] + (target_h - size[1]) // 2))
    return canvas


def _redrawn_sheet(kit: Path, sheet_name: str) -> Image.Image:
    stem = Path(sheet_name).stem
    found = sorted((kit / "redrawn").glob(stem + ".*"))
    if not found:
        raise SystemExit("missing %s/redrawn/%s.*" % (kit, stem))
    return _load(found[0]).convert("RGB")


def import_sheets(name: str, kit: Path, out: Path, parts_dir: Path = None):
    """Write `out` = every original part, with the redrawn ones replaced. Returns the replaced names.

    The redrawn sheet may have any size and a loose grid: parts are found as separate blobs on
    the flat background, ordered by row then left to right (the export order), and each one is
    fitted into the opaque box of the old part, centred on it."""
    parts_dir = parts_dir or sam_render.PARTS_DIR / name
    manifest = json.loads((kit / "manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    for path in parts_dir.glob("*.swf*.png"):
        _load(path).save(out / path.name)
    replaced = []
    for sheet_name in sorted({e["sheet"] for e in manifest["parts"]}):
        entries = [e for e in manifest["parts"] if e["sheet"] == sheet_name]
        row_sizes = [sum(1 for e in entries if e["row"] == r) for r in range(manifest["rows"])]
        row_sizes = [n for n in row_sizes if n]
        sheet = _redrawn_sheet(kit, sheet_name)
        found = _by_slot(_merge_specks(_blobs(_foreground(sheet))), row_sizes)
        for entry, blob in zip(entries, found):
            _fit(_crop(sheet, blob), _load(parts_dir / entry["part"])).save(out / entry["part"])
            replaced.append(entry["part"])
    return replaced


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["export", "import"])
    ap.add_argument("name")
    ap.add_argument("kit", type=Path)
    ap.add_argument("out", nargs="?", type=Path, help="import: folder for the new part PNGs")
    ap.add_argument("--group", choices=["body", "other", "all"], default="body",
                    help="export: body parts (default), skill props and effects, or everything")
    args = ap.parse_args(argv)
    if args.action == "export":
        entries = export(args.name, args.kit, group=args.group)
        print("%d parts on %d sheets" % (len(entries), len({e["sheet"] for e in entries})))
    else:
        if args.out is None:
            ap.error("import needs an output folder")
        print("%d parts replaced" % len(import_sheets(args.name, args.kit, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
