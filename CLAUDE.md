# SAHHT: reverse engineering and private server

This project reverse engineers the Android game "Siêu Anh Hùng Kỳ Sự Naruto" (`sahht-sl-1.5.0.apk`, package `vn.sahht.sl`) and rebuilds its server.
The user writes Vietnamese; answer in Vietnamese.
The goal so far: a private server the real client can log into and play the first campaign stages on, driven from an Android emulator.

## Layout

| Path | What it is |
|---|---|
| `sahht-sl-1.5.0.apk` | Original APK (1.2 GB). Never modify it. |
| `decompiled/NOTES.md` | Reverse-engineering notes: stack, Lua crypto, assets, characters, unresolved items. Read it before touching the client. |
| `decompiled/lua/` | Decrypted client Lua (about 3450 files). The source of truth for the protocol. |
| `decompiled/apk/` | Extracted APK minus `assets/lua`. Game tables are plain JSON in `apk/assets/config/*.config` (709 files). |
| `decompiled/characters/`, `decompiled/preview/` | Character atlases sliced into part PNGs. |
| `decompiled/tools/` | `xxtea_dec.py` (bulk Lua decrypt), `ccz2png.py` (atlas to PNG). |
| `server/` | The private server, client patcher, and tests. Has its own `server/README.md`. |
| `server/data/` | `game_config_version.json` (copied from the APK), `sahht.db` (SQLite, gitignored), `requests.jsonl` (request log, gitignored). |
| `server/build/` | Patched APK, screenshots, logs (gitignored). |

Git: `server/` (minus gitignored data and build output), the decompiled notes and tools, `CLAUDE.md`, `roadmap.md` and `docs/` are tracked; the APK and the extracted client are not. Remote `origin` is `github.com/hiinguyen/SAHHT`.
Commit only when the user asks.

## Client facts that matter

- Cocos2d-x C++ engine (`lib/arm64-v8a/libjinqu.so`, also `armeabi-v7a`) with Lua game logic.
- Lua files are cocos2d-x XXTEA: a 5-byte `XXTEA` signature, then XXTEA over little-endian words, key `aaa` zero-padded to 16 bytes.
  The last plaintext word is the plaintext byte length (this is what looked like "junk trailing bytes").
  `server/tools/patch_apk.py` implements encrypt and decrypt and round-trips the shipped file byte for byte.
- `kaiqigu-chuangshiji` is a different key (`getGameTeaKey`), not used for Lua.
- The only file naming the server is `assets/lua/game_version_config.lua` (`SERVER_LIST_URL_NET` / `_CN`).
  The original points at `https://api-game.tool-sah.pro.vn/pub_abroad_vr`, a live third-party server.
  Do not send logins, registrations or other state-changing requests there without the user's explicit go-ahead.
- HTTP is done by the native stack (curl), so plain `http://` works on Android 14.
- In the decrypted Lua, comments marked `SHHHT` are changes made by whoever built this Vietnamese client.

## Protocol

- Every call is HTTP GET. The client builds `<base><path>?method=<name>` and appends `user_token`, `mk`, `rand`, `version`, `rans`, `pt`, `device_mark`, `platform_channel`, `device_mem` (`game_url.getUrlForKey` in `game_url_config.lua`).
- Paths: `/login/` (master), `/api/` (game), `/config/`, `/pay/`, `/dataosha/`, plus `/lua_ver/<version>.json`.
  The server list returns `master_url` and `domain`; this server points both back at itself.
- Responses are plain JSON `{"status": 0, "msg": "", "data": {...}}`.
  Success is integer `0`; failures are strings (`error_need_login`, `error_account`, `refused`, ...).
  `shared/network.lua` `httpRequestCallback` calls the screen's callback only when status is `"0"` and `data` exists.
- Session: login returns `rand_str`; the client sends it back as `rans` on every call, with `user_token` = player uid.
  The server accepts a session only when the ticket's account owns that uid.
- Authenticated responses carry a top-level `user_status`; the client replaces its player state with it on every reply.
  Missing keys there are Lua nil errors (for example `action_point_max` in the top bar).
- `loading` must return `game_config_version` at the top level, equal to the APK's map, so the client downloads no configs.
- The Lua hot-update manifest must report `different_files: []`, otherwise the client fetches `/lua/hotfix64/...`.

### Boot sequence the client actually makes

1. Fresh install: login popup, then `register` (or `login`), then `get_user_server_list`.
   With a saved ticket it calls `get_user_server_list` directly.
2. "Vào game": `loading`, `lua_ver/<CSJ_FILES_UPDATE_VERION>.json`, `mark_user_login` (returns `mk`), `cards.open`, `user.main_page`, main scene.
3. "Xuất chiến": `private_city.world_map`, tap a stage: `private_city.open`, tap a building: `private_city.map_fight_and_enemy`, "Thám hiểm": `private_city.recapture`, then `private_city.open` again.

### Hard-won shape rules

- `cards.open`: `cards` is a map keyed by card instance id (string); each card needs `id`, `c_id`, `lv`, `level_max`, `step`, `evo`, `exp`, `pre_exp`, `quality`, `hp`, `patk`, `matk`, `def`, `speed`, and `s_1..s_3` skills (`{"s":0,...}` for a hero without that slot; `avail` 2 active, 0 locked).
  The client never derives stats; the server sends them (`base_x + growth_x * (lv - 1)` from `character_detail`).
- `alignment` must have two positional rows `[[5 attack ids], [3 bench ids]]` with `"-1"` for an empty position; `equip_pos` needs keys `"0".."9"` each `["0","0","0","0"]`; `formation` is `{"current":<layout>,"own":[...]}` (layouts 1-6 of `formation.config` each leave a different cell empty; the client sends the chosen one with `cards.set_alignment`); `battle_card_num` has `position_num` and `alternate_num`.
- Drawing any hero card (gacha result, lists) runs `pairs()` on `formation_bonus`, `formation_bonus_addition` and `god_field_ids["1".."3"]`; send them (empty) in `cards.open` or the client errors.
- Almost every other `cards.open` setter returns early on a missing key, so omitting a key is safe and sending a wrong shape crashes.
  Add keys only once their shape is confirmed from the Lua.
- `user.main_page` needs `alerts.is_double` (bool), `combat`, `timezone`, `arena_rank`, `arena_point`, `buy_ap_times`, and `config_refresh: 0`: without it, returning to the main scene compares a missing top-level `all_config_version` and forces a re-login popup that cannot be closed.
- New cards and items reach the client only through `data._client_cache_update`; its `remove` lists are read unguarded. Currency balances change only through `user_status`.
- `cards.set_alignment` and `cards.butcher` are POST with a form body; `metal=` and `card_id=` repeat. `Request.lists` holds every value.
- Tutorial progress is `user_status.guide` (`{"1": step}`); a new player starts at `{"1": 1}`. `game_guide_controller.getCurrentId` switches to team 2 as soon as `guide["2"] == 28`, so a team may only start after the previous one is done.
- Cities unlock by player level (`map_main_story.open_level`), not by clearing the previous city. Cities 100 and 101 pad their maps with placeholder buildings sharing fight 100002; the tutorial expects city 100 to be 100% recovered after its one real building.
- A city's land grid is its tmx map size / 4 (rows = tmx height); a cell outside the map makes the client's TMX lookup fail, a missing cell is drawn as fog.
- Campaign battles are computed by the server; the client only plays back frames (`sort`, `attack`, `cur_data` with `maxHp`, `death`, final `winer`).
  `winer < 5` is a win. Defenders must carry `animation`. `has_battled` must be exactly `1`.
  The result screen's exp bars come from `battle_rewards` (`reward_exp_player` `[added, old, [[lv, need], ...]]`, required when `battle_rewards` is sent; `reward_exp_character` needs an entry for every attacker or the screen errors).
- City grids (`land`) exist in no config; the server packs buildings onto a 7x7 grid.
  Cell = `[openType, buildingId, icon, anchorFlag]`, openType 1 cleared, 2 attackable, 0 visible.
- `step_n` is 0-based into the building's `fight_list`.
- Enemies are looked up in `enemy_soldier_<city>.config` first, then `enemy_detail.config`.
- Never send a `pre_battle` frame with skills in it: the client then loads `ccbResources/pre_battle_bg_res.plist`, which this APK lacks, and the native engine segfaults. Pre-battle skills are sent as ordinary `skill` frames.
- A `skill` frame plays `skill_effect/<hero animation>/<name>.lua`; an unknown name is silently skipped. Status art is `add_buff {src, name}` with `skill_effect/buff/<name>.lua`.
- `user.main_page` sends `inreview`: every view id to hide, the whole list every time (`game_data.updateInreviewByJsonData` resets it on each reply). A view id missing from `inreview.config` is shown by default. `active_switch` is never read by the client.
- A reply with an error status and a `msg` shows a popup and skips the screen's callback; `error_not_open` is used for closed features.
- Recharge: the client pays in gold tickets (`user_status.ticket`, fixed at 9999); `cpOrderId` is `<uid>_<server>_<pack>_<time>_<channel>_<random>`. `shop.vip_buy_step` `double_pay` is an array of numeric pack ids; `month_award`/`week_award` must be `2` or the client shows a local tip instead of calling `payment.use_ticket`.
- When a Lua error happens inside a screen, the log line is `SHHHT enterUi <scene> failed: ...` or `LUA ERROR: ...`; after a swallowed error the client may silently return to the login scene.

## Server architecture (`server/`)

Python 3 standard library only (no pip installs).

- `sahht_server/app.py`: `ThreadingHTTPServer`, routing by the first path segment that is a known service, session guard, JSONL request log (passwords and tickets redacted), `build_server()` and the CLI.
  A session method without a handler gets the body recorded in the scope's `quiet` list (logged `"quiet": true`), an empty success for `/dataosha/` analytics, or else `error_not_open` "Tính năng chưa mở." (logged `"closed": true`); unknown `/login/` methods get `refused`.
  `GameServer.server_close()` also closes the store.
- `sahht_server/scope.py` + `data/scope_2018.json`: the content scope (modules with phase and open flag, view ids, `card_id_max` 38700, `city_order_max`, `quiet` bodies with evidence), validated at startup. `tools/audit_scope.py` inventories the client against it (`--draft` for a fresh draft); a view id is used when the Lua checks it (`isViewOpenByID`), lists it in a menu (`InReviewId = N`, `game_function_pop.lua`) or reads `in_review_N`.
- `sahht_server/payment.py`: free recharge (`payment.use_ticket`, `shop.vip_buy_step`), table `payments` keyed by the client's order id.
- `sahht_server/handlers.py`: login, boot and roster handlers, `user_status`, `ConfigCache` (loads `<name>.config` once, plus memoized derived indexes; uses an `RLock` because builders call `get()`), `card_document`, starter heroes `(5300, 100, 200)`.
- `sahht_server/campaign.py`: the four `private_city.*` handlers, city grid packing (`CityPlan`), unlock order, building battle units.
- `sahht_server/battle.py` + `battle_unit.py`: the battle engine (skills, buffs, controls, DoTs, revives) and its frames. `skills.py` resolves a skill tier against `data/skill_specs.json`; `skill_spec.py` is the spec schema. Rules and the spec DSL: `server/SKILLS.md`.
- `data/skill_specs.json`: hand-curated spec per base skill of every hero up to card 38700. `data/skill_anims.json`: client skill scripts per animation, regenerated with `python3 -m tools.build_skill_anims`.
- `sahht_server/store.py`: SQLite data only, no game rules; `transaction()` makes multi-step changes atomic. Tables `accounts`, `players` (uid = id + 10000, level), `cards` (`step` = evolution, `slot` 0-4 attack, 5-9 bench), `card_skills`, `player_state` (stamina, exp inside the level), `wallet`, `items`, `guide`, `cleared_buildings`, `building_steps`, `counters` (gacha draws, shop purchases with a daily/weekly period, formation, starter kit), `payments`.
  Schema changes are appended to `MIGRATIONS` (applied in order, counted by `PRAGMA user_version`); never edit an applied migration.
- `sahht_server/progression.py`: rules from the configs (player and card levels, card documents with evolution stats and skill tiers, combat power). `player.py`: starter kit, player exp, tutorial teams, `user_status`. `rewards.py`: `[type, id, count]` rewards, weighted rolls, boxes, `grant()` and `_client_cache_update`.
- `sahht_server/cards.py` (formation, inherit, skill level-up, evolution, selling), `gacha.py`, `shop.py` (shop and `item.use`). A handler raises `handlers.Refused` inside a transaction to roll back and answer an error.
- `tools/patch_apk.py`: repoints the client at a URL, rebuilds the APK without the old signature, zipaligns and signs with `~/.android/debug.keystore`.
- `tools/cycle.sh`: one emulator test cycle (restart server, relaunch app, tap "Vào game", print requests and Lua errors, screenshot).
- Handlers are `(Request, Services[, player]) -> body`; register login handlers in `handlers.LOGIN_HANDLERS`, session handlers in `handlers.SESSION_HANDLERS` or `campaign.HANDLERS`.

## Commands

```
cd server
python3 -I -m unittest discover -s tests -t .          # 147 tests, about 50 s (scrypt dominates)
python3 -m tools.audit_scope                            # client modules, views, buttons, cities vs data/scope_2018.json (--draft)
python3 -m sahht_server.skill_spec data/skill_specs.json   # validate the skill specs
python3 -m sahht_server.app --port 8080                 # loopback only by default
TMPDIR=$PWD/build/tmp python3 -m tools.patch_apk --url http://10.0.2.2:8080/pub_abroad_vr
```

- Run the test suite with `discover`; `python3 -I -m unittest tests.x` cannot import the package.
- Run the server without `-I`, it is project code and needs the working directory on the import path.
- `TMPDIR` on disk matters: the APK is 1.2 GB and the build makes temporary copies.
- Restart the server after code changes: `kill $(ss -ltnpH 'sport = :8080' | grep -oP 'pid=\K[0-9]+')`, then start it again.

## Emulator workflow

- Android SDK in `~/Android/Sdk` (cmdline-tools, platform-tools, emulator, build-tools 37.0.0, image `android-34;google_apis;x86_64`).
  The x86_64 image translates ARM, so the ARM-only APK runs. KVM works.
- AVD name `sahht`. Start with a window: `~/Android/Sdk/emulator/emulator -avd sahht -no-audio -no-snapshot-save -gpu swiftshader_indirect`.
  The user sometimes closes the window; check `adb devices` before driving it.
- From the emulator, `10.0.2.2` is the host's loopback, so the patched client talks to `http://10.0.2.2:8080/pub_abroad_vr`.
- The patched APK is `server/build/sahht-local.apk` and is installed on the AVD.
  Installing a re-signed APK over a differently signed one needs `adb uninstall vn.sahht.sl` first, which wipes the app's local data.
- Test account on the local server: `testplayer1` / `pw123456`; it has cleared buildings 100001 and 100002 of city 100.
- Screen is 2400x1080. Useful tap points: "Vào game" (1260, 934), "Xuất chiến" (2302, 930), stage 1-1 platform on the world map (1272, 268), "Thám hiểm" in the building popup (1300, 882), "Tiếp tục" after a battle (2088, 792).
- While the tutorial overlay is active, only taps inside its highlighted circle register.
- Screenshot with `adb exec-out screencap -p > server/build/x.png` and read the PNG.
- Client logs: `adb logcat -d | grep LUA-print`. Errors: grep for `LUA ERROR`, `failed:`, `attempt to`.
- Do not pipe `tools/cycle.sh` into `tail` or similar: it starts the server in the background and the pipe never closes, so the command hangs.

## Working method that worked

1. Find the client code path in `decompiled/lua` (grep the URL key in `game_url_config.lua`, then the screen that calls it).
2. Read which response fields are used without a nil guard; delegate wide reads to an Explore agent when many setters are involved.
3. Write a failing test in `server/tests/`, implement, run the suite.
4. Restart the server, drive the emulator, read `server/data/requests.jsonl`, logcat and a screenshot.
5. Each Lua nil error names the missing field; fix one shape at a time.

## Environment gotchas

- Shell is zsh: `grep --include=*.lua` fails with "no matches found"; use `grep -rn PATTERN .` instead.
- A GateGuard hook blocks the first Bash call, the first Write or Edit of each file, and destructive commands until you state the facts it asks for (request, callers, data shape, user's words); state them and retry the same call.
- Read untrusted extracted files with `python3 -I`.
- REA: the JADX provider is not configured and Hopper timed out on `libjinqu.so`; `llvm-objdump` and `readelf` were used instead.

## Status and next steps

Done and verified on the emulator:
- Register, login, server list, config check, hot-update check, enter game.
- The whole first tutorial with a fresh account: naming, first battle (level-up popup, player and card exp bars), city 100 recovered, recruiting, formation saved by POST, city 101, skipping a tutorial team.
- Main scene combat power, the shop (buying with coin), the gacha pool chain.
- Phase 0 (2026-11-23): out-of-scope buttons hidden, closed features answer "Tính năng chưa mở.", free recharge (coin bag, VIP level, monthly card refused with "Gói này chưa mở.").

Not done (see also `server/README.md`):
- Equipment, gems, pets and other gear; equipment rewards are not granted and tutorial team 2 (equipment) must be skipped.
- Enemy skills (900xx), element damage, leader skills, 5-skill heroes' swap skills, gacha free draws.
- The "Điểm thu hồi" achievement bar (`world_level`/`world_score`) stays at 0%; its source is unknown.
- Everything outside phase 0 is closed through `data/scope_2018.json` (hidden or "Tính năng chưa mở.").
- Client-side unknowns: `.sam` animation format, 56 double-encrypted Lua files, 5 LuaJIT bytecode files, `classes.dex` not decompiled.

Good next steps: phase 1 of `docs/superpowers/specs/2026-11-23-roadmap-2018.md` (daily loop); when a feature is done, open its module in `data/scope_2018.json` and check its views on the emulator.
