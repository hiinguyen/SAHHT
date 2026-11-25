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
| Config check and download | `/login/?method=loading`, `/config/?method=all_config` | working, the version map reports the edited configs (`chapter`, `map_main_story`, `character_detail`) so the client downloads them once |
| Lua hot-update manifest | `/lua_ver/<version>.json` | working, reports no differing files |
| Enter game, starter kit | `/login/?method=mark_user_login`, `cards.open` | 3 starter heroes, starting money (`coin` 1000, `silver` 2000, `food` 10000) and role_detail's starting bag, once per player |
| Main page | `user.main_page` | combat power with the client's own formula (`game_util.getCombatValue`) |
| Tutorial | `user.guide`, `user.rename` | progress per team in `user_status.guide`; teams 2, 3, 5 start when the previous team is done and their `guide_team` condition holds |
| Campaign | `private_city.world_map`, `open`, `map_fight_and_enemy`, `recapture` | every normal chapter and city open from level 1 (`config_overrides.py` edits `chapter` and `map_main_story`, the client downloads them), elite cities by player level, one land grid per city sized from its tmx map, half-done buildings resume (`recapture_log`), first-clear and sweep rewards, `battle_rewards` with player and card experience |
| World achievements | `private_city.world_score`, `get_world_reward` | one "Điểm thu hồi" point per cleared building, `integration_world` tiers claimed in order; type-7 rewards become equipment instances |
| Levels | every reply's `user_status` | player levels from `role.config` (each level-up restores `recover_point` stamina, max 120), card levels from `character_base`, capped at the player level |
| Hero and enemy skills | battle frames `skill`, `add_buff`, `buff_skill`, `reenter` | every skill of every hero up to card 38700 (589 chains) plus all 166 skill ids campaign enemies use (`data/enemy_skill_specs.json`), unlocked and evolved by evolution step, see [SKILLS.md](SKILLS.md) |
| Leader skills | `leader_skill.open`, `train`, `set_skill`; battle frames `anger`, `skill_hero` | the 12 skills whose effect script ships (of 96 rows), learned with `star`, three equipped, rage 0-100 in battle; view 15 open |
| Skill swap | `cards.select_skill_index`, `cards.set_battle_skill`, `cards.unlock_skill` | 5-skill heroes pick any three of their five slots; slots 4-5 unlocked from the start; `skill_num` is no longer overridden |
| Heroes | `cards.set_alignment` (POST), `cards.lock_card`, `cards.release_card`, `cards.inherit`, `cards.card_skill_levelup`, `cards.card_evolution`, `cards.butcher` (POST) | formation and layout, locking (locked cards cannot be sold or used as material), experience transfer, skill levels, evolution, selling |
| Equipment | `cards.open` (`equip`, `equip_pos`), `cards.set_alignment`, `equip.sell`, `factory.equip_levelup`, `equip.all_equip_levelup_auto`, `equip.evolution`, `equip.st_levelup`, `equip.exchange`, `equip.equip_refine`, `equip.auto_refine`, `equip.enchant`, `equip.save_init_enchant`, `equip.remove_enchant`, `equip.auto_enchant`, `equip.equip_forge_index/level/refresh`, `equip.fate_equip_bind/unbind/levelup`, `equip.auto_fate_equip_levelup` | a starter weapon, equipment instances from type-7 rewards and equipment gacha, four slots per team position, enhance cost and level cap from `equip_strongthen`, selling for metal, in-place evolution, refining 0-10 (`equip_st.config`), splitting for metal and metalcore (`equip_exchange` row plus enhance and refine refunds), tempering (`equip_refine` bands clamped by `refine_control_*`), enchanting (`enchant.config` elements, 1 attack or 2 defence keys, pending save and piece refund), forging (`equip_set_*`: stones, three distinct properties, refresh preview/save) and fate binding (`bind_card`/`bind_data` percentages, refreshes with fate stones); suit bonuses (`suit.config`), temper and forge attributes and enchant elements enter combat power; in battle gear feeds crit, hit, dodge, damage reduction and elemental attack/defence; the bag holds 100 pieces (`error_equip_full`) |
| Equipment recruiting | `equip_gacha.get_all_gacha`, `equip_gacha.get_gacha` | `equip_gacha.config` pools, unlock chains, limited draws, weights and pity score; new equipment instances reach the bag through `_client_cache_update.equip._equip` |
| Shop and bag | `shop.open`, `shop.buy`, `shop.vip_store_index`, `shop.vip_store_buy`, `item.use` | escalating prices, daily and weekly caps; the VIP shop's `vip_store` stock bought with coin; boxes, stamina and exp-ball items |
| Feature gate | `user.main_page` `inreview`, every method without a handler | `data/scope_2018.json`: closed views are hidden; methods without a handler answer `error_not_open` (a popup), except background calls listed as `quiet`, which get a verified empty body, and `/dataosha/` analytics, which get an empty success |
| Recharge | `payment.use_ticket`, `shop.vip_buy_step` | free: gold tickets fixed at 9999; coin bags grant coin (doubled on the first purchase of a pack) and VIP exp; packs with their own rewards (monthly and weekly cards) answer "Gói này chưa mở." |

## Protocol notes

- Responses are plain JSON: `{"status": 0, "msg": "", "data": {...}}`. Success is the integer `0`. Failures are strings such as `error_need_login`, `error_account`, `refused`.
- The session is the `rand_str` ticket returned by login. The client sends it back as `rans` on every request, together with `user_token` (the player uid for the chosen server).
- Authenticated responses carry a top-level `user_status` object (`uid`, `show_name`, `level`, currencies, `guide`). The client replaces its player state with it on every reply; balances change only through it.
- New cards, equipment and items reach the client only through `data._client_cache_update` (`{"cards": {"cards": {"update": {...}, "remove": []}}, "equip": {"_equip": {"update": {...}, "remove": []}}, "item": {"items": {...}}}`); `remove` must always be present.
- `cards.open` also sends empty `equip_pos_1..3` and `bonus_equip_pos` (keys "200".."209"): the client indexes them unguarded whenever an equipment icon is drawn.
- A few calls are POST with a form body (`cards.set_alignment`, `cards.butcher`), and some repeat a key (`metal=`, `card_id=`); handlers read `Request.lists` for those.
- `loading` returns `game_config_version` at the top level, not inside `data`.
- Every request is appended to `data/requests.jsonl` (passwords and tickets redacted). `"closed": true` marks a method the client called that has no handler yet, `"quiet": true` one answered with a recorded empty body.

## Not done

- Equipment covers bag/equip/enhance/sell/evolution/refine, splitting, tempering, enchanting, forging and fate binding (views 25, 148, 131, 167, 182, 193 still closed in the scope until each screen is verified on the emulator). Item crafting (`equip.equip_building*`), the rest of the workshop (`factory.*`), pets, badges and cheer-formation gear do not exist.
- Gems (phase 3 branch G1-G2) are stacks keyed `"<id>"` or `"<evolution level>-<id>"` (`cards.open` `gem`, `gem_pos`; placed through `cards.set_alignment` `gem_1i`/`gem_2i`), with `gem.synthesis`, `gem.resolve` (pays metalcore) and `gem.evolution` (success rate, `false_back`, super attempt); their stats (`value` plus the evolution bonus) join gear in combat power and battle. `gem.upgrade` (experience feeding, fields gems no longer have) and the fate gems (`gem_fate.*`) answer "Tính năng chưa mở."; module `gem` is open, `gem_fate` is closed. Not yet driven on the emulator.
- The 83 passive leader-skill nodes and 15 leader skills whose effect script never shipped stay closed; `leader_skill.add_tree_point`, `wash_down` and `train_force` answer "Tính năng chưa mở.".
- Gacha has no free draws (`gacha_freetimes` is empty) and no lucky-energy bar.
- Skins (`cards.buy_skin`, `cards.use_skin`) do not exist; `config_overrides` clears `is_skin` so the skin buttons are hidden.
- Everything outside the open scope (elite stages, arena, guilds, events and the rest) is closed: its button is hidden, or a tap shows "Tính năng chưa mở.". The order of the next phases is in `../roadmap.md`.
- Only `is_use` 1 (box), 2 (stamina) and 19 (exp ball) items can be used.
