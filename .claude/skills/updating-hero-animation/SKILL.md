---
name: updating-hero-animation
description: Use when changing how a SAHHT hero card looks or moves in the client - redrawing its armor or art, replacing one of its skill animations, adding new sprites to its atlas, or putting a changed animation on an emulator or a real device.
---

# Updating a hero's animation (SAHHT)

## Overview

A hero in battle is a sprite atlas plus one `.sam` timeline.
The atlas (`anim/<name>-hd.pvr.ccz` + `.plist`) holds cut-out parts.
The `.sam` file places those parts frame by frame, in named sections (`daiji` idle, `gongji1..5` attacks, `mofa` cast, `beiji` hit, `siwang` death).
A skill is a Lua script (`skill_effect/<name>/*.lua`) that only says which section and frames to play.
The server never sees any of it, so a new look or a new skill animation needs no server change as long as the section length and the hit anchors stay the same.

Details of the formats, paths and commands: [reference.md](reference.md).
Run every tool from `server/` with `SAHHT_DECOMPILED=~/Documents/SAHHT/decompiled` set (the extracted APK lives in the main checkout, not in worktrees).

## Ask first

- Which cards use this animation (`character_detail.config`, field `animation`), and does the animation also serve other card families.
- Which skill section is replaced, and that it keeps its frame count and hit anchors.
- Where the target device's app points (see "Rules for the device"); a phone cannot reach a server on the emulator address.
- That the look is approved before the skill is built on it: the skill sprites are sized from the new armor.

## Pipeline

1. Find the hero: `character_detail.config` `animation` field, then `python3 -m tools.sam_render <anim> list`.
2. Look at it before changing it: render sections to GIF or PNG with `tools.sam_render`.
3. New look (first, the later steps use its parts): `tools.art_kit export`, give the sheet and `docs/art-brief.md` to an image AI, save the result in the kit's `redrawn/`, `tools.art_kit import`, preview with `sam_render --parts`.
4. New skill: have the AI draw the three sheets of `docs/skill-art-brief.md` into a separate folder (`build/<anim>_skill_kit/generated/`), cut them with `tools.skill_sprites`, build the section with a script on `tools.sam_author` (copy `tools/ironman_missile_rain.py`, it is Iron Man's and its constants are his), preview the GIF, iterate until the user approves it.
5. Pack: `tools.atlas`, then `tools.patch_assets` on the APK that is installed on the target device, then `adb install -r`.

## What must not change

- The section's frame count and the hit anchors (`beiji`, `bao`, `shock_screen`, `zhongpao`) keep their frames: the Lua script and the battle engine rely on them.
- Image tags stay in the file, the loader reads them all up front.
- Part PNGs keep their size and pivot: the engine rotates around the image centre.

## Traps that cost time

| Trap | Fix |
|---|---|
| Moving the whole body as one block looks stiff | Use key pose sprites and crossfade with squash and stretch |
| Reusing an old prop at a new size looks bad | Ask the AI for the prop |
| An AI sheet comes back with another size, rows or a sparkle watermark | `art_kit` and `skill_sprites` already find parts as blobs and wipe the sparkle, do not rely on the grid |
| Leftover parts from the previous section stay on screen | `compile_section(..., initial_depths=<state before>)` |
| A sprite that faded out stays invisible after fading back in | A move without a color form keeps the old tint, `sam_author` emits a neutral one |
| Explosions cut off at the end of the section | Everything must finish inside the old frame count |
| Pulling the APK with a relative destination fails silently | Give `adb pull` an absolute path |
| Installing over a differently signed app wipes its data | Check the certificate first, never uninstall without asking |

## Rules for the device

- Build from the APK installed on the device (pull it), not from the original: it holds the right server URL and Lua fixes.
- Read the URL (command in reference.md); never send requests to it.
- If it is the third-party live server named in CLAUDE.md, stop and ask before installing or opening the app.
- A phone reaches a local server only through the host's LAN address, with the server started with `--host 0.0.0.0` and the APK patched by `tools.patch_apk --url`; `10.0.2.2` is the emulator's alias only.
- Keep the pulled APK as the rollback.
- After installing, compare the SHA-256 on the device with the built file.
- Say what was not seen in the game: the preview renderer does not model the client's blend modes.
