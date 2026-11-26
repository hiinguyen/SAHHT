# Phase 1: daily sign-in, VIP rewards, pay gifts, stamina purchase

Date: 2026-11-26.
Status: research spec, nothing implemented yet.
Source of truth: the decrypted client Lua in `decompiled/lua` and the APK configs in `decompiled/apk/assets/config`.
Vietnamese appears only where the client shows it.

## 0. Scope and summary

Features covered:

1. `daily_award.*`: the welfare tab "Điểm danh" (free 25-day sign-in plus the recharge sign-in tab).
2. `vip_reward.*`: the welfare tab "VIP reward" (7-day track per VIP level plus a daily bonus), and `vip.buy_point`, `vip.buy_cmdr_energy`, `vip.buy_commbander_protect`.
3. `pay_award.*`: the month card tab, and how it links to the existing free recharge in `server/sahht_server/payment.py`.

What is reachable in this client (verified by grep for callers):

| Method | Reachable from | Notes |
|---|---|---|
| `reward.once_index` | main scene welfare button (tag 10067) | Not in the task list, but the welfare scene cannot open without it. Section 1. |
| `daily_award.all_reward` | welfare tab "sign" | `game_fuli_activity_scene.createDailySignUI` |
| `daily_award.get_reward` | welfare tab "sign" | `game_pop/game_fuli_subui_dailysign.lua` |
| `daily_award.coin_award` | welfare tab "sign", second sub-tab | same file |
| `vip_reward.sign_index` | welfare tab "VIPReward" | `createVIPRewardUI` |
| `vip_reward.vip_sign` | `game_fuli_subui_VIPReward.getVipLevelReward` | |
| `vip_reward.every_day` | same file, button 103 | |
| `pay_award.index` | welfare tabs "monthvip" and "quartervip" (both send `tp=month`), `game_month_gift_pop` | |
| `pay_award.get_award` | `game_fuli_subi_monthvip_pop` (`tp=month`), quarter pop (`tp=quarter`), old `game_activity` (`tp=week`/`month`) | |
| `vip.buy_point` | `game_normal_tips_pop` openType 3, `city_auto_raids_pop` | |
| `vip.buy_cmdr_energy` | `game_normal_tips_pop` openType 17, only from `game_ability_commander_snatch` | commander system does not exist yet |
| `vip.buy_commbander_protect` | nothing | URL key exists, no Lua caller |

Dead screens (no caller, ignore them): `game_ui/game_daily_sign.lua`, `game_ui/game_daily_scene.lua`, `game_ui/game_task_scene.lua`, `game_ui/game_activity_scene.lua`, `game_pop/game_task_pop.lua`, `game_pop/game_daily_pop.lua`.
They only appear in commented-out `enterGameUi` calls.
`game_ui/game_activity.lua` (old activity scene, the only opener of `game_month_gift_pop`) is only entered from `reEnter()` and commented calls, so `game_month_gift_pop` is effectively dead too; its shape is still listed in section 4.6 because it shares `pay_award.index`.

Everything below is GET.
All handlers are `(Request, Services, player) -> body` and registered in `app.SESSION_HANDLERS` like `shop.HANDLERS`.
A module's `open` flag in `scope_2018.json` only controls the `inreview` view list (`Scope.closed_views`); `app._resolve` serves a handler whenever one is registered, open or not.
So handlers can be added before the views are opened, and the views are flipped when the emulator check passes.

## 1. How the welfare button opens everything

Main scene button `m_conbtn_fuli` (btnTag 10067), `game_ui/game_main_scene.lua` line 1163:

1. The client sends `reward.once_index` (GET, no params).
2. On success it enters `game_fuli_activity_scene` with `awardData = gameData`.
3. Each tab then sends its own request when first selected (sign: `daily_award.all_reward`, VIPReward: `vip_reward.sign_index`, monthvip and quartervip: `pay_award.index?tp=month`).

Visibility gates on the main scene:

- The button is shown only when `isViewOpenByID(3)` (`top_btn_name_tab`, `refreshTopButton`).
  View 3 is currently tied to module `reward` (closed), so the button is hidden today.
- The red dot on the button (`game_main_scene.lua` 2132-2150) reads, in this order: `alerts.active == 1` and view 49, else `alerts.month` truthy and view 126, else (only when player level >= 3) `alerts.daily == true` and view 9, and `alerts.once == true` and view 8.

### 1.1 `reward.once_index` minimal stub (required)

`game_fuli_activity_scene.init` does:

```lua
local temp = json.decode(t_params.awardData:getNodeWithKey("data"):getFormatBuffer())
local result = temp.once.result          -- UNGUARDED: needData.once.result
...
local item = result[tostring(cid)]        -- result may be empty
```

Minimal reply:

```json
{"status": 0, "msg": "", "data": {"once": {"result": {}}}}
```

- `data.once` and `data.once.result` are read with no nil guard.
  A missing `once` is `attempt to index field 'once'` when the button is tapped.
- With `result = {}` the four award tabs (`online`, `level`, `advanture`, `arena`, and `live_trial`) are removed from the tab strip (`showType` stays false), so nothing else is needed from `reward_once.config`.
- `game_fuli_subui_award` (the real "once" rewards) is a separate feature (module `reward`, daily tasks and achievements) and stays out of this phase.
- If someone later returns non-empty `result`, entries are `result[<reward_once key>] = [?, ?, state]` with `state` 0 locked, 1 claimable, 2 claimed (`item[3]`).
  Do not do that in this phase.

The stub lives in module `reward`, which stays `open: false` (it also gates views 4 and 8).
The scope change for view 3 is in section 6.

## 2. `daily_award.*` (check-in)

### 2.1 Client state

`game_data:setDailyAwardDataByJsonData(data)` stores the whole `data` object as-is (`m_dailyAwardData.data`).
`game_data:getDailyAwardData()` returns it and the sign tab reads these keys (`game_fuli_subui_dailysign.lua`):

| Key | Type | Read as | Used for |
|---|---|---|---|
| `score` | int | `(index+1) <= score`, `score > cfgCount-3` (arithmetic) | days available to claim or already claimed; a missing or non-number key is a Lua error |
| `reward` | JSON array | `#reward`, `reward[1]`, `table.remove`, `tostring(v) == tostring(key)` | day keys that are unclaimed (see below); must be an array |
| `coin_days` | int | `data:getNodeWithKey("coin_days"):toInt()` | recharge sign-in progress |
| `coin_status` | int 0/1/2 | `...:toInt()` | recharge sign-in state |
| `coin_pay_rmb` | int | `...:toInt()` | coins recharged today |
| `daily_award_loop` | bool, optional | `toBool()` if present | which config the free tab uses |
| `coin_award_loop` | bool, optional | `toBool()` if present | which config the recharge tab uses |
| `coin_award_loop_reriod` | int, optional | `toInt()` if present | period filter in `month_award_coin_loop` |

`coin_days`, `coin_status`, `coin_pay_rmb` are read with `:toInt()` and no guard: a missing key is a Lua error when the tab opens.
The three optional keys can be omitted (the tab then uses `daily_award.config` and `month_award_coin.config`).

### 2.2 `daily_award.all_reward`

Request: no params.
Response:

```json
{"status": 0, "msg": "", "data": {
  "score": 3,
  "reward": [2, 3],
  "coin_days": 0,
  "coin_status": 0,
  "coin_pay_rmb": 0
}}
```

Meaning of `score` and `reward` (derived from the rendering code):

- Day cell `i` (1-based, `i = index + 1`) is "available" when `i <= score`.
- It is "unclaimed" when the config key `tostring(i)` is in `reward`, otherwise "claimed" (green tick, `signed.png`).
- A day with `i > score` is locked.
- So `score` is the number of sign-in days reached so far, and `reward` is the list of day keys `<= score` that were not collected yet.
- On open the list scrolls to `reward[1]` (so keep it ascending), or to `min(score, cfgCount - 3)` if nothing is pending.
- The label under the list is fixed text "Mỗi ngày 24:00 tạo mới": a new day is added at local midnight.

The sub-tab shown first: `m_show_tpye = 1` (free sign-in) when `alerts.daily` is truthy in the last `user.main_page`, else 2 (recharge sign-in).
Both tab buttons always work.

Config for the free tab: `daily_award.config`, 25 rows keyed `"1".."25"` (the file stores them in string order `1,10,11,...`).
Row: `{"award": [[type, id, count], ...], "icon": "icon_daily_reward"}`, always two awards.
Types used: 1 food, 2 metal, 4 crystal, 5 hero card (50, 51, 52 universal cards, 6200, 6300, 6400, 9000), 6 item (522034), 9 coin, 14 star, 15 silver, 16 metalcore.
All types are supported by `rewards.Loot.add` and all ids exist in `character_detail.config` / `item.config` and are `<= card_id_max`.
`daily_award_loop.config` has the same shape (25 rows, other rewards) and is used only when `data.daily_award_loop == true`.

Server rule (proposal, no config field says otherwise):

- State per player: `signin:score` (int), `signin:claimed` (bitmask of claimed day numbers), `signin:today` (marker with the day as period).
- `sync(uid, today)`: if the marker for today is absent, set it and `score = min(score + 1, 25)` (25 = number of rows in the config).
  Call it from `user.main_page` (the client calls that every time the main scene is entered, see 2.6) and from `daily_award.all_reward`, so the day count advances on the first visit of the day and is idempotent after that.
- `reward` = day numbers `1..score` whose bit is not set, ascending, as integers.
- After day 25 is claimed the cycle ends.
  Optional extension: on the next day reset `score` and the bitmask and answer `daily_award_loop: true`, so the second cycle uses `daily_award_loop.config`.
  The client already supports this, but it is not required for the first release.

### 2.3 `daily_award.get_reward`

Request: `reward=<day key>` (string such as `3`).
The old comment in `game_url_config.lua` says several ids are allowed (comma separated), but every Lua caller sends exactly one key.
Accept one key and refuse anything else with `error_param`.

Response:

```json
{"status": 0, "msg": "", "data": {
  "reward": {"coin": 100, "silver": 3000},
  "_client_cache_update": {...}
}}
```

- The client does `game_util:removeValueInTeam(key, reward)` on its local copy, refreshes, then `game_util:rewardTipsByJsonData(data.reward)`.
  `data.reward` is the toast dict (`Granted.reward`), nil-safe on the client.
- Heroes and items reach the client only through `_client_cache_update` (use `Granted.cache`, as `shop.shop_buy` does).
- Currency balances change through the automatic `user_status` on every reply.
- Errors: key not an integer in `1..score` or already claimed: `error_param` with msg (use `Refused` so the transaction rolls back).
  Card bag or equipment bag full: whatever `rewards.grant` already raises.

Atomicity: set the bit and grant in the same transaction (`with svc.store.transaction()`), like `shop_buy`.

### 2.4 `daily_award.coin_award` and the recharge sign-in sub-tab

Data (`month_award_coin.config`, 25 rows keyed `"1".."25"`): `{"award": [[6, 9100934, 1], [6, 522051, 1]], "icon": "icon_daily_reward", "pay": 200}`.
`pay` is the number of coins that must be recharged today to unlock that day's reward (200 on every row).
`month_award_coin_loop.config` has extra fields `id`, `reriod`, `score`; used only when `coin_award_loop` is true.

Client semantics (`createRewardTableView2`, `createDateTableView2`):

- `coin_days` = index (0-based) of the cell that is "today": cells with `index < coin_days` are signed.
- `coin_status` applies to cell `index == coin_days`: 0 shows the "recharge" button (tapping calls `shop.vip_buy_step` and opens `ui_vip`), 1 shows the claim button, 2 shows "already" and the date list ticks that cell too (`index == coin_days and coin_status == 2`).
- Therefore after a claim today the server keeps `coin_days` at today's index and answers `coin_status = 2`; on the next day `coin_days` is the number of claimed days and the status is recomputed.
- Under the list the hint reads `month_award_coin[coin_days + 1].pay - coin_pay_rmb` ("Nạp tiếp N Xu, nhận thêm phần thưởng sau") when the status is 0.

Server rule (proposal):

- `claimed_count` (counter `coin_sign:claimed`) and a daily marker `coin_sign:today` (period = today).
- `coin_pay_rmb` = coins recharged today.
  Add a counter `recharge_coin` with daily period in `payment.use_ticket` (`coin = pack.coin + pack.gift_coin`, plus the first-purchase double bonus if you want it to count), because `payments` has no coin amount.
- `coin_days = claimed_count - 1` if the marker says "claimed today" else `claimed_count`.
- `coin_status`: 2 if claimed today, else 1 if `coin_pay_rmb >= month_award_coin[claimed_count + 1].pay`, else 0.
- Once `claimed_count == 25` there is no next row: answer `coin_status = 0` and refuse `coin_award` (the client then shows no hint, `itemCfg` is nil-guarded).

`daily_award.coin_award` request: no params.
Response (client reads `data.coin_days` and `data.coin_status` unguarded; `data.reward` is nil-safe):

```json
{"status": 0, "msg": "", "data": {
  "coin_days": 0,
  "coin_status": 2,
  "reward": {"...": 1},
  "_client_cache_update": {...}
}}
```

Errors: `coin_status` is not 1 -> `error_param` ("Chưa đủ điều kiện nhận.").
Note the client never sends `coin_pay_rmb` back; after the claim it only replaces `coin_days` and `coin_status` locally.

Because recharge is free in this server (`FREE_TICKETS` 9999), a player reaches `pay` by buying a coin pack in `ui_vip`.
If the tab is not wanted at first, send `coin_days: 0, coin_status: 0, coin_pay_rmb: 0` and implement `coin_award` later; the unfinished button then leads to the VIP screen, which works.

### 2.5 Reset period

Daily at 00:00 in `handlers.TIMEZONE` (UTC+7), the same zone sent as `timezone` in `user.main_page`.
Reuse `shop.period(DAILY, now)` for the counter period string.

### 2.6 `alerts` in `user.main_page`

Current code (`handlers.user_main_page`): `"alerts": {"is_double": False}`.
`game_data.setAlertsDataByJsonData` replaces the whole table on every `main_page`, and `game_scene.enterGameMainScene` calls `user.main_page` every time the main scene is entered (also when the welfare scene closes with `back()`), so the red dot refreshes on return.
`game_data_download` (login) only downloads `cards.open`; the 180 s timer in the main scene sends `user.main_page` but its callback is empty, so do not rely on it.

Keys to add (all read by the main scene or welfare scene):

| Key | Type to send | Read as | Meaning |
|---|---|---|---|
| `daily` | bool | `== true` | at least one free sign-in day is unclaimed (`reward` non-empty) |
| `month` | bool | truthy | the month card is active, not claimed today and days left |
| `once` | omit | `== true` | online/level rewards, module `reward`, not served |
| `active` | omit | `== 1` | survival supplies tab (view 49, closed); if ever sent it must be the integer 1 |

Traps:

- Send real booleans.
  `0` is truthy in Lua, so `"month": 0` would light the dot permanently.
  Omit a key or send `false`.
- Only `daily == true` is accepted; the string `"true"` or `1` does not match.
- The dot for `daily` only shows when the player level is >= 3.
- `inreview` stays driven by `Scope.closed_views()`.

### 2.7 Views

| View | Used by | Required |
|---|---|---|
| 3 | the welfare button itself | open (section 6) |
| 9 | sign tab (`InReviewID = 9`) and the `daily` dot | module `daily_award` open |
| 4, 8 | other reward tips | stay closed (module `reward`) |

The welfare tab strip also lists tabs for views 11 (announce), 49 (liveres), 151 (growth plan), 37 (gift code), 41 (invite code); all five are closed in the scope file already and must stay closed (their requests have no handlers).

## 3. `vip_reward.*`

Screen: `game_pop/game_fuli_subui_VIPReward.lua`, tab `VIPReward` (`InReviewID = 173`).

Config `new_vip_reward.config`: 17 rows keyed `"1".."17"` (VIP levels 1-17):

```json
{"day1": [[6,5,4]], "day2": [[5,51,2]], "day3": [[14,0,2000]], "day4": [[1,0,50000]],
 "day5": [[2,0,50000]], "day6": [[4,0,500]], "day7": [[6,92854,1]],
 "everyday": [[9,0,20],[2,0,500]]}
```

- `dayN`: exactly the first triple is read by the client (`reward[1]`), the server should grant all triples of the day (all configs have one).
- `everyday`: the client reads `everyday[1]` and `everyday[2]` unguarded and draws two icons, so the list has at least two entries (all rows do; level 16-17 have three).
- Config types are all supported by `rewards.Loot` and every referenced id exists.
- `vip.config` has levels 0-17 (`need_exp` is the total `vip_exp` for the next level); `player.vip_level` already derives the level for `user_status.vip`.

Client state on open (`init`): `data` and `user_status` of the `sign_index` reply are decoded; `m_vip_level = user_status.vip`, forced to 1 when 0 (VIP 0 sees the VIP 1 tab; red dots are hidden when `user_status.vip == 0`).

### 3.1 `vip_reward.sign_index`

Request: no params.
Response:

```json
{"status": 0, "msg": "", "data": {
  "sign_record": {"1": {"day": 2, "flag": true}, "2": {"day": 0, "flag": true}},
  "is_every_day": true
}}
```

- `sign_record` is read unguarded (`self.m_tGameData.sign_record[tostring(index+1)]` in `createLeftBtn`).
  It must be a table, `{}` is fine.
  Keys are VIP level strings `"1".."17"`; the client also tolerates a missing level (shown as "Nhận" greyed, tag -101).
- `day` (int 0-7): number of days already claimed on that level's 7-day track.
- `flag` (bool): `true` = the player may claim one more day of this track today; `false` = already claimed today (or nothing more to claim).
  Day cell rendering for the selected level, 0-based `index`:
  - `flag == true`: `index < day` claimed ("Đã nhận"), `index == day` claimable ("Nhận"), `index > day` locked ("Chưa thể nhận").
  - `flag == false`: `index <= day - 1` claimed, others locked.
- `is_every_day` (bool): the daily bonus of the player's own VIP level can be claimed today.
  It is read with `data.is_every_day` and compared `== true` / `== false`; send a real boolean, never omit it.
- Which levels appear in `sign_record`: the comment in `game_url_config.lua` says `vip_sign` with a `vip` param claims "the reward of a level lower than the player's own".
  Include one entry for every level `1..vip` (the player's VIP level), none for higher levels.
  With `vip == 0` send `{}` and `is_every_day: false`.
  The red dot on a level tab is `flag == true` for levels in `sign_record`, plus the own level when `is_every_day` is true.

Server rule (proposal): per level `L`, counter `vip_sign:L` holds `day` (permanent, 0-7) and a daily marker `vip_sign_today:L` (period = today) says whether a day was claimed today.
`flag = day < 7 and not claimed_today`.
`is_every_day` = vip >= 1 and the counter `vip_everyday` (daily period) is 0.

### 3.2 `vip_reward.vip_sign`

Request: optional `vip=<level>`.
The client sends no param when the selected tab is the player's own level, and `vip=<level>` for any other tab.
Rule: no param means the player's own VIP level; `vip=N` requires `1 <= N <= own vip` (else `error_param`, msg "Chưa đạt cấp VIP.").
Claim day `day + 1` of level N: refuse when `flag` is false or `day >= 7`.

Response:

```json
{"status": 0, "msg": "", "data": {
  "reward": {"...": 1},
  "sign_record": {...same shape as sign_index...},
  "is_every_day": true,
  "_client_cache_update": {...}
}}
```

- `data.sign_record` is read unguarded (`json.decode(data:getNodeWithKey("sign_record"):getFormatBuffer())`).
- The client then does `self.m_tGameData = data`, replacing the whole data object, so `sign_record` is also what `createLeftBtn` reads next.
  Always return the full map, not only the changed level.
- `reward` is the toast dict (nil-safe).
- `is_every_day` is not read from this reply (the client keeps its own copy) but include it so the two replies match.

### 3.3 `vip_reward.every_day`

Request: no params.
Response (`data` becomes `self.m_tGameData` as well):

```json
{"status": 0, "msg": "", "data": {
  "is_every_day": false,
  "sign_record": {...full map...},
  "reward": {"...": 1},
  "_client_cache_update": {...}
}}
```

- Trap: after this call the client assigns `self.m_tGameData = data` and calls `refreshUi()`, which indexes `self.m_tGameData.sign_record[...]` again.
  Omitting `sign_record` from this reply is a Lua error (`attempt to index field 'sign_record'`).
- `is_every_day` must be `false` after a successful claim; the client then switches the button to `VipReward_alredy.png`.
- Grants every triple of `new_vip_reward[<own vip>].everyday`.
- Errors: vip 0 or already claimed today -> `error_param`.

### 3.4 Reset period

`every_day`: daily at 00:00 (UTC+7).
Day tracks: permanent per level, one day claimable per level per calendar day, the `day` counter never resets (max 7).

### 3.5 Views and alerts

- View 173 must be open (currently closed with the wrong reason "không nơi nào trong Lua gọi view này"; `game_ui/game_fuli_activity_scene.lua` contains it but plain `grep` treats that file as binary, use `grep -a`).
- No `alerts` key is read for VIP rewards.
- Related VIP views that are not part of this phase: 105 (VIP gift button, needs `vip_bought`), 106 (privilege table), 111.

## 4. `pay_award.*` and the month card

### 4.1 Which packs are cards

`charge.config` (key = pack id, fields include `open_gift`, `buy_times`, `vip_exp`, `coin`, `gift_coin`, `is_show`):

| Pack | Name | `open_gift` | `is_show` | `vip_exp` |
|---|---|---|---|---|
| 1 | Thẻ tháng (month card) | 2 | 1 | 500 |
| 2 | Thẻ tuần (week card) | 1 | 1 | 1100 |
| 13 | Thẻ Mùa (quarter card) | 5 | 1 | 1100 |
| 12 | Grow plan | 3 | 0 | 1300 |
| 18-21 | voucher packs ("Đổi N phiếu") | 6 | 1 | 0 |

`payment.use_ticket` today refuses every pack with `open_gift` set ("Gói này chưa mở.").
The cards have `coin = 0` and `gift_coin = 0`: they grant `vip_exp` on purchase and nothing else; the rewards come from `pay_award.get_award` later.
`ui_vip` shows the toast "Thẻ tháng mua thành công, phần thưởng sẽ phát trong thư", which is misleading here but harmless.

### 4.2 Month card state

Store these as integers in `counters` (`store.counter`/`set_counter`, period `""`), using epoch days (`date.toordinal()` in UTC+7) so no migration is needed; a table `pay_cards(player_id, kind, pay_dt, award_day, days)` appended to `MIGRATIONS` is the cleaner alternative if date strings are preferred.

- `month_card:pay_day` (0 = never bought), `month_card:award_day` (0 = never claimed), `month_card:days` (days claimed).
- Convert to the client strings `YYYY-MM-DD` in UTC+7 (the client compares with `os.date("!%Y-%m-%d", server_time + timezone * 3600)` using the `timezone` from `main_page`, so both sides must use `TIMEZONE` 7).
- Card length: `count = number of rows in month_award.config = 21`.

Purchase hook in `payment.use_ticket` for `open_gift == 2` (pack 1):

- Allowed when never bought, or when `days >= count` (finished).
  Otherwise `fail("error_buy_times", "Thẻ tháng chưa nhận hết.")`.
- Do not apply the generic `buy_times` cap (pack 1 has `buy_times: 2`, which would stop a player from renewing a third time).
- On success: record the payment, grant `vip_exp` (the existing `change_wallet` call), set `pay_day = today`, `award_day = 0`, `days = 0`.
- No coin and no immediate reward.
  The first day is claimed from the tab ("Nhận"), the unpaid layout already previews the day 1 and day 2 rewards from `month_award.config`.

`shop.vip_buy_step` (`payment.vip_buy_step`) keeps reporting `month_award = 2` (buyable) only when the card can be bought (never bought or finished); otherwise `0` (claimable today) or `1` (already claimed today / waiting), because `ui_vip.onCellBtnClick` only calls `payment.use_ticket` when `month_award == 2` and otherwise shows the local tip "Quà mỗi tháng mua lần trước vẫn chưa nhận xong".
`week_award` stays `2` so a tap on the week card reaches `use_ticket`, which answers "Gói này chưa mở." (no client screen claims week rewards; `game_activity` is dead).
`quarter_award` (key of `vip_buy_step`, optional; the client defaults to 2) stays absent for the same reason (pack 13 stays refused).

### 4.3 `pay_award.index`

Request: `tp=month` (the month tab and the quarter tab both send `tp=month`; the old `game_month_gift_pop` sends no param).
Response for the month card:

```json
{"status": 0, "msg": "", "data": {
  "month_award": {
    "pay_dt": "",
    "award_day": "",
    "days": 0,
    "reward": {"1": {"award": [[35,0,600],[9,0,600]], "charge": 1000, "icon": "e_w_zhongwu2", "limit_time": [1,3]}, ...}
  }
}}
```

Read without guards in `game_fuli_subi_monthvip_pop`:

- `data.month_award.reward`: the table is counted (`getTableLen(...) or 20`) and used as the card length; send the rows of `month_award.config` (21 entries, same shape as the config, because `game_month_gift_pop` reads `reward[i].award`).
- `month_award.pay_dt`: string, `""` when the player never bought a card, else the purchase date.
  Compared with `== ""` and `~= ""`; it must be a string, not null.
- `month_award.award_day`: string, `""` or the date of the last claim.
  `init` does `monthData.award_day ~= "" and monthData.days <= monthDays`, so it must be a string (a nil `award_day` would evaluate `nil.days`-style comparison on a nil `days`).
- `month_award.days`: int claimed days.
  Arithmetic and comparisons (`dayLabel > count`) are done on it.
- Local config `month_award` (from the APK, `getConfig("month_award")`) is used to draw the reward icons, so the client does not need the rows from the server except for the count.

Client logic from those fields (for the server to stay consistent):

- Paid layout when `pay_dt ~= ""`.
  "Claimed" (button hidden, "already got" sprite) when `award_day == today` or `days == count` or `days > count`; otherwise the claim button shows reward row `days + 1`.
- `m_isMonthVIP` (used by the shop button) is true when `award_day ~= ""` and `days <= count`.
- Alerts: `alerts.month` (section 2.6) should be `pay_dt` set, `award_day != today`, `days < count`.

### 4.4 `pay_award.get_award`

Request: `tp=month` (or `week`, `quarter`).
Only `month` is served; `week` and `quarter` answer `error_not_open` "Tính năng chưa mở." (or "Gói này chưa mở.").
Response (the client does `self.m_gameData = json.decode(data)` and redraws, so it must be the same shape as `index`, plus `reward`):

```json
{"status": 0, "msg": "", "data": {
  "month_award": {"pay_dt": "2026-11-26", "award_day": "2026-11-26", "days": 1, "reward": {...21 rows...}},
  "reward": {"coin": 600, "high_forge_stone": 600},
  "_client_cache_update": {...}
}}
```

- Trap: `month_award` is mandatory here too; `refreshUi` reads `self.m_gameData.month_award.reward` right after.
  The quarter pop is different (it expects `data.quarter_award` and replaces its data with that), which is one more reason to keep view 184 closed.
- `reward` (toast dict) is read with `self.m_gameData.reward or {}`.
- Rule: card active (`pay_day > 0`), `award_day != today`, `days < count`; grant `month_award[days + 1].award` (types 35 high forge stone, 6 item 1430, 9 coin, all supported), then `days += 1`, `award_day = today`.
- Errors: `error_param`/"Hôm nay đã nhận rồi." when not claimable.
- Daily reset 00:00 (UTC+7); the card does not expire by calendar, only by claimed days.

### 4.5 Quarter card (not served)

The tab `quartervip` (view 184) and `game_fuli_subi_quartervip_pop` expect `data.quarter_award = {reward: {"1".."90": {reward: [...]}}, version, days, pay_dt, award_day}`, and the pop sends `pay_award.index?tp=month` (a client bug), so the month reply would crash it (`data:getNodeWithKey("quarter_award")` is nil).
`quarter_award.config` has 1080 rows (12 versions of 90 days) with `value_month` windows.
Keep it out of this phase: hide view 184 (section 6).

### 4.6 Old `game_month_gift_pop`

Reads `data.month_award.reward[i].award` (a list of objects with `award`) and `data.month_award.days`.
Fully satisfied by the same `pay_award.index` reply.
It is unreachable, listed for completeness.

### 4.7 Views and alerts

- View 126 (tab `monthvip`, the dot `alerts.month`): module `pay_award`.
  `inreview.config` row 126 has `name` "2014-08-07 18:00,2019-08-08 24:00" but `is_open: 1`, `show_lv: 0`; the client only checks `show_lv`, so the date range is ignored.
- View 184 (tab `quartervip`): not in `inreview.config` and not in the scope file, so it is shown by default.
- View 29 (module `payment`) is the existing recharge button.

## 5. `vip.buy_point`, `vip.buy_cmdr_energy`, `vip.buy_commbander_protect`

Module `vip` has no views of its own (no view in the scope file is tied to it), so opening it changes nothing in `inreview`; it only documents the feature.

### 5.1 `vip.buy_point` (buy stamina with coin)

Callers:

- `game_normal_tips_pop` openType 3 ("Thể lực không đủ"), button 2, shown by `map_building_detail_pop`, `game_small_map_scene`, `hero_road_pop` and, for the server error `error_3`, `game_error_pop`.
- `city_auto_raids_pop` (auto battle, when no potion is left).
- Cost and limit are computed locally; the server must use the same numbers:
  - Price of purchase number `n` (0-based, `n` = today's purchases): `pay.config["2"].coin[min(n, len - 1)]` (list `[10, 20, 30, 40, 50, 60, 70, 100]`; the last value repeats).
  - Daily limit: `vip.config[<user_status.vip>].buy_point` (0 -> 1, 1 -> 2, 2 -> 4, 3 -> 7, 4 -> 10, 5 -> 15, 6 -> 20, 7 -> 25, 8 -> 30, 9 -> 35, 10-11 -> 40, 12-13 -> 45, 14-17 -> 50).
  - The client refuses locally when `buy_ap_times >= limit` and, in `game_normal_tips_pop`, when `action_point >= 150`.

Request: no params.
Response (read unguarded: `data.buy_ap_times`):

```json
{"status": 0, "msg": "", "data": {"buy_ap_times": 1}}
```

- The client stores it with `game_data:setBuyActionTimes`, shows "Mua thể lực thành công~", closes the popup; `user_status.action_point` and `user_status.coin` update from the automatic `user_status`.
- Amount of stamina per purchase is NOT in any client file or config (potions: `item.config` 3-6 give 5/20/50/100).
  It needs a project decision; a named constant of 60 (half of `ap_max` 120) is suggested.
  Grant it with `store.change_action_point(uid, amount, now)`, which may exceed the maximum.
- Counter `buy_point` with daily period (`shop.period(DAILY, now)`).
- Cost: `rewards.pay(svc, uid, {"coin": price})`; for a coin shortage prefer `Refused("error_4", "Xu không đủ.")`, because `error.config` has `error_4` and `game_error_pop` maps it to the standard "not enough coin" popup (`error_not_enough` has no config row and only shows a text alert).
- Limit reached: `fail("error_param", "Số lần mua thể lực đã dùng hết.")`.
- Stamina already full (`action_point >= ap_max`): refuse with `error_param` (the client's own guard uses 150, the server maximum is 120).
- `user.main_page` currently sends the constant `"buy_ap_times": 0`.
  It must send today's counter, because the client reads it (`game_data.lua` 3642) for the price shown and the limit check; leaving 0 would let the client believe no purchase was made after a re-entry.
- Optional consistency fix: `campaign`, `sweep` and `elite` answer `error_action_point` when stamina is short; `game_error_pop` only knows `error_3` for the stamina popup.
  The client checks stamina locally before most fights, so this is secondary, but `error_3` would open the purchase popup from the server side too (three call sites and `tests/test_campaign.py:200`, `tests/test_sweep.py:72`).

Reset: daily at 00:00 (UTC+7).

### 5.2 `vip.buy_cmdr_energy` (commander system)

Caller: `game_normal_tips_pop` openType 17, opened only from `game_ability_commander_snatch` when `user_status.cmdr_energy < 2`.
Price: `pay.config["12"].coin[min(buy_cmdr_times, len - 1)]` (list `[10, 30, 50, 70, 100, 150, 200, 250, 300, 350, 400]`), where `buy_cmdr_times` comes from the commander screen's own data (`self.m_tGameData.buy_cmdr_times`), not from `main_page`.
The popup only needs `data` to exist and `status` 0; then it calls `m_ok_func` (refresh the screen).
`cmdr_energy` is already a wallet currency in `player.CURRENCIES`.
The amount per purchase is not in the client; the potion `item.config` 26 gives 10.
Not implementable until the commander system exists (roadmap phase 3 branch H, awaiting owner approval).
Until then leave it unhandled (`error_not_open`), as today.

### 5.3 `vip.buy_commbander_protect`

URL key exists, no Lua calls it.
Leave unhandled.

### 5.4 `item.use` for stamina

Already implemented (`item_use.py`, `USE_STAMINA`), it is button 1 of the same popup.

## 6. Scope changes (`server/data/scope_2018.json`)

`Scope.closed_views()` lists every view whose entry is closed; a view with `module` follows `modules[<name>].open`; a view that is not in the file is never hidden.

| Entry | Now | Change |
|---|---|---|
| module `daily_award` | `open: false` | `open: true` once sections 2.x pass on the emulator (opens view 9) |
| module `vip_reward` | `open: false` | `open: true` (opens nothing by itself: no view is tied to it yet) |
| view 173 | `{"open": false, "reason": "không nơi nào trong Lua gọi view này"}` | `{"module": "vip_reward", "reason": "tab VIPReward của màn phúc lợi (game_fuli_activity_scene.lua); giai đoạn 1"}` |
| module `pay_award` | `open: false` | `open: true` (opens view 126, the month card tab) |
| view 184 | missing | add `{"open": false, "reason": "tab thẻ mùa (quarter_award) cần pay_award.index?tp=quarter, ngoài phạm vi"}` |
| view 3 | `{"module": "reward", ...}` | `{"open": true, "reason": "nút phúc lợi trên màn chính (top_btn_name_tab); reward.once_index trả once.result rỗng"}`, a standalone flag so that modules `reward` stays closed and views 4 and 8 stay hidden |
| view 49 | closed | keep closed (liveres tab) |
| views 11, 151, 37, 41 | closed | keep closed (announce, growth plan, gift code, invite code tabs) |
| views 50, 51 | missing (and not in `inreview.config`) | add as closed ("thưởng cấp độ/ải ở tab award, cần reward.once_index thật"); today they are hidden only because `result` is empty |
| module `vip` | `open: false` | optional: `open: true` after `vip.buy_point` is done (no view effect) |

Also check the existing `tests/test_scope.py` and `tools/audit_scope.py`: the audit missed views 173 and 184 because `game_ui/game_fuli_activity_scene.lua` is detected as binary by `grep`; fix the audit to read it as text.
The `quiet` list is empty and must stay unused here: none of these methods is a background call.

Method gating: `app._resolve` serves a registered handler regardless of the module flag, and a method without a handler gets `error_not_open`.
Handlers needed: `reward.once_index` (stub), `daily_award.all_reward`, `daily_award.get_reward`, `daily_award.coin_award`, `vip_reward.sign_index`, `vip_reward.vip_sign`, `vip_reward.every_day`, `pay_award.index`, `pay_award.get_award`, `vip.buy_point`.

## 7. Suggested code layout (follows the existing pattern)

- `server/sahht_server/welfare.py`: `reward.once_index` stub, `daily_award.*`, sign-in sync used by `user_main_page`; `HANDLERS` merged into `app.SESSION_HANDLERS`.
- `server/sahht_server/vip_reward.py`: `vip_reward.*`.
- `server/sahht_server/pay_award.py`: month card state, `pay_award.*`, a helper used by `payment.use_ticket` and `payment.vip_buy_step`.
- `server/sahht_server/vip_buy.py` (or `shop.py`): `vip.buy_point`.
- `handlers.user_main_page`: compute `alerts` (`daily`, `month`) and `buy_ap_times` from those modules (call the sign-in sync first).
- `payment.py`: month card branch and a `recharge_coin` daily counter.
- Counter names: `signin:score`, `signin:claimed`, `signin:today`, `coin_sign:claimed`, `coin_sign:today`, `recharge_coin`, `vip_sign:<level>`, `vip_sign_today:<level>`, `vip_everyday`, `month_card:pay_day`, `month_card:award_day`, `month_card:days`, `buy_point`.
  Daily ones use `shop.period(DAILY, now)`.
- Tests (`tests/test_welfare.py`, `test_vip_reward.py`, `test_pay_award.py`): shape tests that decode the reply and assert every unguarded key listed here, daily reset by passing a fake `now`, double-claim refusal, bag rollback, month card purchase then claim then rebuy.

## 8. Open questions for the emulator pass

1. Config key order.
   The client enumerates `daily_award.config` and `month_award_coin.config` with `getNodeAt(index)` and labels cell `index + 1`, while the files store keys as `1,10,11,...,19,2,20,...`.
   If the native JSON keeps file order, "day 2" would pick key `10`.
   Check on the emulator that cell 2 pays row 2; if not, add an override in `config_overrides.py` that rewrites both configs with numeric key order.
2. Stamina per `buy_point` purchase and per `buy_cmdr_energy` purchase (not in the client).
3. Whether a finished month card may be renewed on the same day (the spec allows it).
4. Whether to loop the free sign-in with `daily_award_loop.config` after day 25.
