"""Hand a hero's part images to an image AI, then take the redrawn sheets back.

    python3 -m tools.art_kit export ironman build/ironman_kit
    python3 -m tools.art_kit import ironman build/ironman_kit build/ironman_new/ironman

`export` packs every part PNG of `characters/<name>/` onto grid sheets (flat
grey background, parts enlarged to help the AI) and writes `manifest.json`.
`import` reads the redrawn sheets from `<kit>/redrawn/` (same file names and
same pixel size), cuts each cell, shrinks it to the part's original size and
keeps the ORIGINAL alpha, so a redraw that bleeds outside the shape is clipped
back to the silhouette and every animation keeps working.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

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


def _remove_background(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Undo the grey the sheet blended into soft edges, then apply the original alpha."""
    pixels = []
    for (r, g, b), a in zip(rgb.getdata(), alpha.getdata()):
        if 0 < a < 255:
            k = a / 255
            r, g, b = (max(0, min(255, round((c - (1 - k) * bg) / k))) for c, bg in zip((r, g, b), BACKGROUND))
        pixels.append((r, g, b, a))
    out = Image.new("RGBA", rgb.size)
    out.putdata(pixels)
    return out


def import_sheets(name: str, kit: Path, out: Path, parts_dir: Path = None):
    parts_dir = parts_dir or sam_render.PARTS_DIR / name
    manifest = json.loads((kit / "manifest.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for entry in manifest["parts"]:
        if entry["sheet"] not in sheets:
            sheet = _load(kit / "redrawn" / entry["sheet"]).convert("RGB")
            if sheet.size != SHEET_SIZE:
                raise SystemExit("%s is %s, expected %s: ask the AI to keep the sheet size"
                                 % (entry["sheet"], sheet.size, SHEET_SIZE))
            sheets[entry["sheet"]] = sheet
        left, top, width, height = _part_box(entry)
        cut = sheets[entry["sheet"]].crop((left, top, left + width, top + height))
        cut = cut.resize((entry["w"], entry["h"]), Image.LANCZOS)
        alpha = _load(parts_dir / entry["part"]).getchannel("A")
        _remove_background(cut, alpha).save(out / entry["part"])
    return len(manifest["parts"])


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
        print("%d parts written" % import_sheets(args.name, args.kit, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
