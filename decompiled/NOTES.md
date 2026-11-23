# SAHHT sl 1.5.0 - reverse engineering notes

## Stack
- Cocos2d-x (C++) with Lua game logic, engine in `lib/*/libjinqu.so`.
- Java layer (`classes.dex`) is mostly SDKs: NetEase NIM (chat), TalkingData, Alipay, iFlytek, UnionPay, Umeng.
- The game's own Java is `com/kqg/main` (19 classes) and `org/cocos2dx/lib`.
- `assets/config/*.config` (710 files) are plain JSON game tables.
- `assets/Sonnenblume/res.bin` is a ZIP.

## Lua protection
- `assets/lua/**/*.lua` start with the `XXTEA` signature.
- The loader is `cocos2dx_lua_loader` at `0x37b700` in the arm64 lib.
- It calls `xxtea_decrypt` with the 3-byte key `aaa` (string at `0x881d40`).
- `getGameTeaKey()` at `0x22a4e0` returns `kaiqigu-chuangshiji`, a different key.
  It is used for `getConfigByName` and exposed to Lua, not for loading Lua.
- Decrypted output is in `lua/`. Reproduce with `tools/xxtea_dec.py <src_dir> <dst_dir>`.
  The script has the key from the first attempt replaced by `aaa`.
  XXTEA output has 1-8 junk bytes at the end of each file, trimmed in a second pass.

## Not recovered
- 5 files in `skill_effect/yadainna/` are LuaJIT bytecode, not source.
- 56 files still start with `XXTEA` after the first layer.
  Neither `aaa` nor `kaiqigu-chuangshiji` opens the second layer.
  At least `game_ui/game_open_recharge.lua` looks like a stale copy, since the loaded module is `game_open_rechrage.lua`.
  Treat them as unresolved.
- 3 files are empty stubs (only the signature).
- `classes.dex` was not decompiled (JADX provider not configured).
- Native `libjinqu.so` was only inspected for the two functions above.

## Assets
- Full APK contents (minus `assets/lua`) are extracted in `apk/` (1.6 GB).
- Most are in `apk/assets/iphonehd/` (11032 files): png, `.pvr.ccz` textures (zlib-compressed PVR), plist atlases, `.ccbi` (CocosBuilder UI), `.sam` (animation), `.tmx` (maps).
- Sound is in `apk/assets/sound/` (wav and mp3).

## Characters
- No full-body PNG exists. A character is a cut-out set of parts (head, arms, hands, hair, cape, effects) packed in one atlas.
- `anim/<name>-hd.pvr.ccz` is zlib (CCZ header 16 bytes) over PVR v2, RGBA4444.
- `anim/<name>.plist` gives each part's rectangle (`<name>.swf<N>.png`).
- `anim/<name>.swf.sam` is the animation data that places and moves parts per frame (format not decoded yet).
- `tools/ccz2png.py <name> <anim_dir> <out_dir>` writes the atlas and every part as PNG. Example output in `preview/monkey/`.
- `characters/<name>/` holds atlas + all part PNGs for 322 animation names (1.4 GB, 39957 PNGs). Built with `tools/ccz2png.py apk/assets/iphonehd/anim characters --characters apk/assets/config/character_detail.config`.
- 6 names in `character_detail.config` have no atlas in the APK: boss, jiayezi, mai, spider, tyrant, zhenzi.
