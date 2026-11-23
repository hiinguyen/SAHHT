# SAHHT minimal private server

A protocol-level reimplementation of the server side the SAHHT 1.5.0 client talks to.
It is derived from the decrypted client Lua in `../decompiled/lua`, not from any original server code.

## Run

```
cd server
python3 -m sahht_server.app --port 8080
python3 -I -m unittest discover -s tests -t .
```

The server binds to loopback by default.
It needs only the Python standard library.
Config files are served from `../decompiled/apk/assets/config` (709 files, matching `data/game_config_version.json` exactly).
The database schema is upgraded in place on start (`store.MIGRATIONS`, counted by `PRAGMA user_version`).

## Content scope

`data/scope_2018.json` decides what the server serves: every client API module, every view id the client can hide, the hero cut (`card_id_max` 38700) and the background calls answered quietly.
The server refuses to start with a malformed file.
`python3 -m tools.audit_scope` lists the client's modules, view ids, level-gated buttons and campaign cities against it; `--draft` prints a fresh draft.
A view id counts as used when the Lua checks it (`isViewOpenByID`), lists it in a menu (`InReviewId = N`) or reads `in_review_N`; a view missing from `inreview.config` is shown by default, so every used id needs a row.

## Point the client at this server

```
python3 -m tools.patch_apk --url http://10.0.2.2:8080/pub_abroad_vr   # 10.0.2.2 = host, seen from the emulator
adb uninstall vn.sahht.sl            # the re-signed APK cannot update the original install
adb install build/sahht-local.apk
```

The tool decrypts `assets/lua/game_version_config.lua` (cocos2d-x XXTEA, key `aaa`), replaces the two `SERVER_LIST_URL_*` lines, re-encrypts, drops the old signature, then zipaligns and signs with `~/.android/debug.keystore`.
Set `TMPDIR` to a disk path if `/tmp` is a small tmpfs: the APK is 1.2 GB.
The client's native HTTP stack accepts plain `http://` (verified on the Android 14 emulator).

Verified end to end on the emulator with a fresh account: register, the whole first tutorial (naming, first battle with level-up and card experience, city recovered, recruiting, formation), the second city, the shop, and skipping the tutorial.

## What works

| Client step | Endpoint | State |
|---|---|---|
| Register, login, guest | `/login/?method=register`, `login`, `new_account` | working, scrypt-hashed passwords |
| Server list | `/login/?method=get_user_server_list` | working, one server, ticket checked via `rans` |
| Config check and download | `/login/?method=loading`, `/config/?method=all_config` | working, version map equals the APK so nothing is downloaded |
| Lua hot-update manifest | `/lua_ver/<version>.json` | working, reports no differing files |
| Enter game, starter kit | `/login/?method=mark_user_login`, `cards.open` | 3 starter heroes, starting money (`coin` 1000, `silver` 2000, `food` 10000) and role_detail's starting bag, once per player |
| Main page | `user.main_page` | combat power with the client's own formula (`game_util.getCombatValue`) |
| Tutorial | `user.guide`, `user.rename` | progress per team in `user_status.guide`; teams 2, 3, 5 start when the previous team is done and their `guide_team` condition holds |
| Campaign | `private_city.world_map`, `open`, `map_fight_and_enemy`, `recapture` | cities open by player level (`map_main_story.open_level`), one land grid per city sized from its tmx map, half-done buildings resume (`recapture_log`), first-clear and sweep rewards, `battle_rewards` with player and card experience |
| Levels | every reply's `user_status` | player levels from `role.config` (each level-up restores `recover_point` stamina, max 120), card levels from `character_base`, capped at the player level |
| Hero skills | battle frames `skill`, `add_buff`, `buff_skill`, `reenter` | every skill of every hero up to card 38700 (589 skill chains), unlocked and evolved by evolution step, see [SKILLS.md](SKILLS.md) |
| Heroes | `cards.set_alignment` (POST), `cards.inherit`, `cards.card_skill_levelup`, `cards.card_evolution`, `cards.butcher` (POST) | formation and layout, experience transfer, skill levels, evolution, selling |
| Recruiting | `gacha.get_all_gacha`, `gacha.get_gacha` | pools, unlock chains, prices and drop weights from `gacha.config`, pity score |
| Shop and bag | `shop.open`, `shop.buy`, `item.use` | escalating prices, daily and weekly caps; boxes, stamina and exp-ball items |
| Feature gate | `user.main_page` `inreview`, every method without a handler | `data/scope_2018.json`: closed views are hidden; methods without a handler answer `error_not_open` (a popup), except background calls listed as `quiet`, which get a verified empty body, and `/dataosha/` analytics, which get an empty success |
| Recharge | `payment.use_ticket`, `shop.vip_buy_step` | free: gold tickets fixed at 9999; coin bags grant coin (doubled on the first purchase of a pack) and VIP exp; packs with their own rewards (monthly and weekly cards) answer "Gói này chưa mở." |

## Protocol notes

- Responses are plain JSON: `{"status": 0, "msg": "", "data": {...}}`. Success is the integer `0`. Failures are strings such as `error_need_login`, `error_account`, `refused`.
- The session is the `rand_str` ticket returned by login. The client sends it back as `rans` on every request, together with `user_token` (the player uid for the chosen server).
- Authenticated responses carry a top-level `user_status` object (`uid`, `show_name`, `level`, currencies, `guide`). The client replaces its player state with it on every reply; balances change only through it.
- New cards and items reach the client only through `data._client_cache_update` (`{"cards": {"cards": {"update": {...}, "remove": []}}, "item": {"items": {...}}}`); `remove` must always be present.
- A few calls are POST with a form body (`cards.set_alignment`, `cards.butcher`), and some repeat a key (`metal=`, `card_id=`); handlers read `Request.lists` for those.
- `loading` returns `game_config_version` at the top level, not inside `data`.
- Every request is appended to `data/requests.jsonl` (passwords and tickets redacted). `"closed": true` marks a method the client called that has no handler yet, `"quiet": true` one answered with a recorded empty body.

## Not done

- Equipment, gems, pets, badges and the other gear systems do not exist; equipment rewards (type 7) are not granted, and tutorial team 2 (equipment) can only be skipped.
- Enemies fight with normal attacks: their `skill1..3` ids (900xx) have no specs yet. Heroes deal no element damage (element stats come from gear). Leader (rage) skills are not implemented.
- The 5-skill heroes' swap skills (slots 4-5, `cards.select_skill_index`) are not implemented; battles use slots 1-3.
- Gacha has no free draws (`gacha_freetimes` is empty) and no lucky-energy bar.
- The world achievement bar ("Điểm thu hồi" on the city and world map) stays at 0%: what earns `world_score` is not known.
- Everything outside phase 0 (elite stages, arena, guilds, events and the rest) is closed: its button is hidden, or a tap shows "Tính năng chưa mở.". The order of the next phases is in `../roadmap.md`.
- Only `is_use` 1 (box), 2 (stamina) and 19 (exp ball) items can be used.
