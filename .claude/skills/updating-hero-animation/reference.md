# Reference: hero animation files and commands

## Where things are

| What | Path |
|---|---|
| Extracted client (main checkout) | `~/Documents/SAHHT/decompiled/` (set `SAHHT_DECOMPILED`) |
| Atlas, plist, timeline of a hero | `apk/assets/iphonehd/anim/<name>-hd.pvr.ccz`, `<name>.plist`, `<name>.swf.sam` |
| Sliced part PNGs | `characters/<name>/<name>.swf<N>.png` |
| Skill scripts | `lua/skill_effect/<name>/*.lua` (encrypted in the APK, `anim_sequence` lists section, rate, first and last frame) |
| Which card uses which animation | `apk/assets/config/character_detail.config`, field `animation` |
| Art briefs for the AI | `docs/art-brief.md` (armor parts), `docs/skill-art-brief.md` (poses and effects) |
| Tools | `server/tools/`: `sam.py`, `sam_render.py`, `art_kit.py`, `skill_sprites.py`, `sam_author.py`, `atlas.py`, `patch_assets.py`, `patch_apk.py` |

## The `.sam` format

A list of tags, each `u32 type, u32 size`; the loader reads fields by type and ignores `size`.

| Type | Tag | Fields |
|---|---|---|
| 0 | end | none |
| 1 | image | u32 id, cstring frame name (several ids may name one frame) |
| 2 | label | cstring section name, ends at the next label |
| 3 | place | u32 frame id (0 = move what is at the depth), depth, z, has color, has matrix; 6 f32 matrix; color form |
| 4 | remove | u32 depth |
| 5 | show | end of frame |
| 6 | handle | width, height, f32 fps, frame count (first tag) |
| 7 | anchor | cstring, a JSON event fired on that frame |

- The matrix in the tag is `(a, d, -b, -c, tx, ty)`; the real affine is x' = a x + c y + tx, y' = b x + d y + ty, y down.
- Parts rotate and scale around the centre of their image.
- A color form multiplies by 256 as 1.0; a move without a color form keeps the old tint.
- Anchors seen: `{"type":"wav","res":..}`, `shock_screen`, `bao` (a damage tick), `beiji` (the target's hit reaction).
- Sections of a hero: `dengchang` enter, `daiji` idle, `qianjin`/`tibu`/`houtui` steps, `beiji1/2` hit, `shuaidao`, `siwang` death, `mofa` cast, `shengli` win, `gongji1..7` attacks.

## The atlas

- `.pvr.ccz`: `CCZ!`, u16 0, u16 2, u32 0, u32 length (big endian), then zlib of a PVR v2 file with a 52 byte header and RGBA4444 pixels (R<<12 | G<<8 | B<<4 | A), straight alpha.
- Sizes need not be powers of two (Iron Man was 1049 x 1049).
- The plist lists `frame`, `offset`, `rotated`, `sourceColorRect`, `sourceSize` per frame.
- A rotated frame is stored turned 90 degrees clockwise and its plist width and height are the drawn ones.
- Some frames a `.sam` names are not in the atlas (Iron Man: 236, 238, 240); the client skips them.

## Commands (from `server/`)

Find the cards of an animation:

```
python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); print([(k,v['name']) for k,v in d.items() if v.get('animation')==sys.argv[2]])" \
  $SAHHT_DECOMPILED/apk/assets/config/character_detail.config <anim>
```

Pipeline, in this order (the poses are sized from the new armor):

```
export SAHHT_DECOMPILED=~/Documents/SAHHT/decompiled
python3 -m tools.sam_render <anim> list
python3 -m tools.sam_render <anim> <section> out.gif [--parts DIR] [--window l,t,r,b] [--scale 0.5]
python3 -m tools.sam_render <anim> <section> out.png --frame N

python3 -m tools.art_kit export <anim> build/<anim>_kit
#  save the AI sheet as build/<anim>_kit/redrawn/sheet_01.png
python3 -m tools.art_kit import <anim> build/<anim>_kit build/<anim>_new/<anim>

python3 -m tools.skill_sprites build/<anim>_skill_kit/generated build/<anim>_skill_sprites --parts build/<anim>_new/<anim>
#  pose.png, explosion.png, missile.png in that generated/ folder, not in the armor kit's redrawn/
#  Iron Man's script; for another hero copy it to tools/<anim>_<skill>.py and change its constants
python3 -m tools.ironman_missile_rain build/<out> --sprites build/<anim>_skill_sprites --parts build/<anim>_new/<anim>

#  new_frames.json is written by the build script: {label: frame name} of the frames to add
python3 -m tools.atlas <anim> $SAHHT_DECOMPILED/apk/assets/iphonehd/anim build/<out>/parts build/<out>/new_frames.json build/<anim>_atlas
mkdir -p build/tmp
TMPDIR=$PWD/build/tmp python3 -m tools.patch_assets --apk build/device/installed.apk --out build/sahht-device.apk \
  assets/iphonehd/anim/<anim>.swf.sam=build/<out>/<anim>.swf.sam \
  assets/iphonehd/anim/<anim>.plist=build/<anim>_atlas/<anim>.plist \
  assets/iphonehd/anim/<anim>-hd.pvr.ccz=build/<anim>_atlas/<anim>-hd.pvr.ccz
```

## Writing a new skill animation

- Copy `tools/ironman_missile_rain.py`: it holds the constants (depths, timing, targets) and one function per layer.
- Build a `Timeline` of the old section's length, add hero layers, missiles and effects, copy the old section's hit anchors, call `compile_section(label, timeline, initial_depths=displays[first - 1])`, then `replace_section`.
- Keep the new sprite frames named `<anim>.swf<N>.png` from 301 up and register them with `Image` tags (ids from 1001 up).
- Preview with `sam_render.render_frames(..., window=(-330, -470, 950, 260))`; effects reach far from the hero's 150 x 200 canvas.
- Tests: `python3 -I -m unittest discover -s tests -t . -p "test_sam*.py"` and the tests of each tool.

## Putting it on a device

```
adb devices -l
adb -s <id> shell pm path vn.sahht.sl                          # prints package:<path>, drop the prefix
mkdir -p build/device
adb -s <id> pull "<that path>" /absolute/path/build/device/installed.apk
~/Android/Sdk/build-tools/<version>/apksigner verify --print-certs build/device/installed.apk
#  the SHA-256 must equal the one of ~/.android/debug.keystore (keytool -list -v); apksigner is not on PATH
adb -s <id> install -r build/sahht-device.apk                   # keeps the app's data
adb -s <id> shell sha256sum "<new path>"                        # must equal sha256sum of the built file
```

- The server URL of the installed APK (`patch_apk.decrypt` has no command line):

```
python3 -I -c "import zipfile,sys; sys.path.insert(0,'.'); from tools import patch_apk as p; z=zipfile.ZipFile(sys.argv[1]); print([l for l in p.decrypt(z.read(p.CONFIG_ENTRY),p.LUA_KEY).decode().splitlines() if l.startswith('SERVER_LIST_URL')])" build/device/installed.apk
```

- The tools find the Android SDK in `~/Android/Sdk` (or `ANDROID_HOME`).
- Rollback: `adb -s <id> install -r build/device/installed.apk`.
- A signature mismatch means the app was signed with another key: stop and ask before uninstalling, that wipes the app's local data.
- A new animation shows in a battle that uses it: for Iron Man the card `3800` and its ultimate `3830`.
