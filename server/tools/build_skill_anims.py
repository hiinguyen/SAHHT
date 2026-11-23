"""Index the client's skill animation scripts into data/skill_anims.json.

The battle scene plays a skill frame by loading
`skill_effect/<hero animation>/<frame name>.lua`; a name with no file is
silently skipped. The server needs to know which names exist so every skill it
casts has a visible animation. This writes `{animation: [script names]}` from
the decrypted client Lua.

    python3 -m tools.build_skill_anims [--lua-dir ../decompiled/lua] [--out data/skill_anims.json]
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def index(skill_effect_dir: Path) -> dict:
    return {
        d.name: sorted(f.stem for f in d.glob("*.lua"))
        for d in sorted(skill_effect_dir.iterdir()) if d.is_dir()
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lua-dir", default=str(ROOT.parent / "decompiled" / "lua"))
    ap.add_argument("--out", default=str(ROOT / "data" / "skill_anims.json"))
    args = ap.parse_args()
    result = index(Path(args.lua_dir) / "skill_effect")
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=0) + "\n",
                              encoding="utf-8")
    print(f"{len(result)} animations, {sum(map(len, result.values()))} scripts -> {args.out}")


if __name__ == "__main__":
    main()
