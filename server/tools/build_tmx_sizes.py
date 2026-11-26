"""Write data/tmx_sizes.json: the tile size of every city map the APK ships.

The server sizes each city's land grid from its tmx map (campaign._land_size), but the
deployed server has no copy of the APK's maps, so the sizes travel with the code.
Run from server/ after extracting the APK: python3 -m tools.build_tmx_sizes
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT.parent / "decompiled" / "apk" / "assets" / "iphonehd" / "building_img"
OUT = ROOT / "data" / "tmx_sizes.json"
SIZE_RE = re.compile(r'<map\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"')


def main():
    sizes = {}
    for path in sorted(MAPS.glob("*.tmx")):
        match = SIZE_RE.search(path.read_text(encoding="utf-8", errors="replace")[:2048])
        if match is None:
            raise SystemExit(f"{path.name}: no map size in its header")
        sizes[path.name] = [int(match[1]), int(match[2])]
    OUT.write_text(json.dumps(sizes, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(sizes)} maps)", file=sys.stderr)


if __name__ == "__main__":
    main()
