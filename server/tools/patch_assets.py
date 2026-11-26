"""Replace files inside an APK, then zipalign and sign it with the local debug key.

    python3 -m tools.patch_assets --apk build/device/installed.apk --out build/sahht-device.apk \\
        assets/iphonehd/anim/ironman.swf.sam=build/ironman_rain2/ironman.swf.sam \\
        assets/iphonehd/anim/ironman.plist=build/ironman_atlas/ironman.plist

Every other entry is copied as it is (same bytes, same compression), so the server URL and the Lua
fixes already inside the APK stay. An entry that is not in the APK is refused: this tool replaces,
it does not add. Signature files are dropped and `patch_apk.align_and_sign` signs the result; the
debug key is the one the APK on the device was signed with, so `adb install -r` keeps its data.
"""

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict

from tools import patch_apk


def replace_entries(src: Path, dst: Path, replacements: Dict[str, bytes]) -> None:
    """Copy `src` to `dst` (unsigned) with the bytes of the named entries replaced."""
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("output must differ from the input APK")
    with zipfile.ZipFile(src) as zin:
        missing = sorted(set(replacements) - set(zin.namelist()))
        if missing:
            raise ValueError("not in the APK: " + ", ".join(missing))
        with zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                if patch_apk.SIGNATURE_FILE_RE.match(info.filename):
                    continue
                data = replacements.get(info.filename)
                if data is None:
                    data = zin.read(info)
                out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                out.compress_type = info.compress_type
                out.external_attr = info.external_attr
                zout.writestr(out, data)


def parse_replacements(pairs) -> Dict[str, bytes]:
    out = {}
    for pair in pairs:
        entry, sep, path = pair.partition("=")
        if not sep or not entry or not path:
            raise ValueError("expected ENTRY=FILE, got %r" % pair)
        out[entry] = Path(path).read_bytes()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apk", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("replace", nargs="+", metavar="ENTRY=FILE")
    args = ap.parse_args(argv)
    replacements = parse_replacements(args.replace)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        unsigned = Path(tmp) / "unsigned.apk"
        replace_entries(args.apk, unsigned, replacements)
        patch_apk.align_and_sign(unsigned, args.out)
    print("wrote %s (%d entries replaced)" % (args.out, len(replacements)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
