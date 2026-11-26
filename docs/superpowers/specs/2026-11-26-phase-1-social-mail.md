# Phase 1 spec: mail (notify), friends, city chests, free gacha draws, world score, item.view / item.exchange

Research only.
Nothing under `server/` or `decompiled/` was changed to write this.
All field names below were read from `decompiled/lua`; "UNGUARDED" marks a field the Lua indexes without a nil check.
`ok(data)` and `fail(status, msg)` are `handlers.ok` and `handlers.fail`.
The client calls a screen callback only when `status` is `0` and `data` exists, so every success sends a `data` object (`{}` at least).
Every authenticated reply also carries `user_status` (added by `app._dispatch`), so currency and stamina changes need no extra work.

## 0. Summary of findings

| Topic | Verdict |
|---|---|
| notify (mail) | Used by the "Thông tin" menu button (tag 302, view 28) and by the secretary menu. Needs 3 methods and a `mail` table. |
| friend | Used by the "Bạn bè" menu button (tag 301, view 27) -> `game_friend_scene`. 7 methods are reachable, 2 are never called by any screen. |
| gift (city chests) | DEAD in this client. No live caller, and `map_main_story.config` has no `rate_loot*` / `rate*` fields. Keep `gift` closed, do not implement. |
| free gacha | Client side is fully built; the server only lacks `gacha_freetimes` data and a cooldown rule. Small change in `gacha.py`. |
| "Điểm thu hồi" bar | Already implemented (`campaign._world_progress`, `private_city.world_score`, `get_world_reward`). The bar is not broken, see section 5. `CLAUDE.md` is stale on this point. |
| item.view / item.exchange | Used by the "Đổi đồng đội" (view 21) and "Đổi trang bị" (view 26) menu buttons and by the talisman screen. Not served at all. They are the only reason views 21 and 26 are closed. |
| item.use | Already in the working tree (`server/sahht_server/item_use.py`, untracked, registered in `app.py`). Section 6.4 lists the `is_use` kinds it still refuses. |

## 1. notify (mail and notices)

### 1.1 Which screens call it

- `game_pop/game_function_pop.lua` tag 302 and `game_pop/ui_secretary_detaile.lua` tag 302 send `notify.messages` and open `game_ui/game_notify_message_scene.lua` with that reply.
- The menu button is gated by view 28 (`InReviewId = 28`, name "Thông tin"), currently hidden because module `notify` is closed.
- The red dot comes from `alerts.notify` (section 1.5).
- Tab 2 of the scene ("tổ đội") calls `team_fight.team_fight_messages`, gated by view 213 (`"Tổ đội BOSS chưa mở"` tip). Leave it unserved; the default `error_not_open` popup is fine.
- `notify.messages` is called only from those two menus. Nothing else polls mail.

### 1.2 `notify.messages`

Request: no params.

Response `data`:

```json
{
  "messages": [
    {"id": "17", "send_name": "sys", "title": "Chào mừng", "content": "Dòng 1\nDòng 2",
     "gift": [[15, 0, 2000], [6, 3, 2]]}
  ]
}
```

- `messages` MUST be a JSON array and MUST be present even when empty. The scene does `#self.m_tGameData.messages` in `refreshUi` and `pageChangedCallFunc` (UNGUARDED). A JSON object would make `#` return 0.
- Per message, read by the list cell (`setcellInfo`) and by the detail pop (`game_message_pop`):
  - `id` (string): sent back as `message_id`. UNGUARDED in `receiveAwards` (`itemData.id`).
  - `content` (string): UNGUARDED (`util.stringSplit(data.content, "\n")`, `setString`). The list shows only the first line, cut to 50 characters; the pop shows all of it.
  - `gift` (array of `[type, id, count]`): UNGUARDED (`next(data.gift)`, `#rewardList`). Send `[]` for a message with no reward.
  - `send_name` (string): UNGUARDED in the pop. The literal `"sys"` is shown as "Thông tin hệ thống"; any other string is shown as the sender name.
  - `title` is only used by the tab-2 list; it is harmless on tab 1 and useful for GM tooling.
- `gift` triples use the same type numbers as `rewards.Loot.add` (`CURRENCY_BY_TYPE`, 5 card, 6 item, 7 equip, 13 action point, 19 gem). The client draws them with `game_util:getRewardByItemTable`, so an unknown type id draws nothing but does not crash.
- The list pages 6 messages at a time, newest first is the natural order (sort by `created_at` descending, then `id` descending).
- Cap the list at 100 messages (drop the oldest claimed or expired first); the client has no scrolling beyond pages and a long list only costs payload.
- There is no timestamp field in the client; do not add one expecting it to be shown.

### 1.3 `notify.read`

Request: `message_id=<id>`.
This is the only call made when the player taps a message, then "Nhận" (message has gifts) or "Xác định" (no gifts) in the pop; both buttons run the same `okBtnCallBack`, so a mail with an empty `gift` must be accepted and simply removed.

Response `data` (the scene replaces its whole list with it, `self.m_tGameData = decode(data)`):

```json
{
  "messages": [ ...the remaining unclaimed messages, same shape as notify.messages... ],
  "reward": {"coin": 100, "item": [3, 3], "cards": ["12"], "equip": ["5"], "action_point": 20},
  "_client_cache_update": { ... }
}
```

- `messages` is UNGUARDED again (`refreshUi`), same rule as above.
- `reward` is the `Granted.reward` dict from `rewards.grant`; the client runs `game_util:rewardTipsByDataTable(reward)` on it. It may be omitted (the function returns on nil) but then no toast is shown, so always send it.
- New items, cards and equipment reach the client only through `_client_cache_update`, so return `granted.cache` exactly like `item_use` and `get_world_reward` do. Currency balances change only through `user_status` (automatic).
- Error cases (all with a Vietnamese `msg`, which the client shows as a popup and which skips the callback): unknown or foreign or already claimed id -> `error_param`; bag full -> let `grant` raise `Refused("error_equip_full", ...)`, which rolls the claim back so the mail stays.
- Claiming must be atomic with the mark: inside the request's transaction, set `claimed_at` and call `grant`. A `Refused` rolls both back.

### 1.4 `notify.auto_read` ("Nhận tất cả")

Request: `message_id=<id1>|<id2>|...` (ids joined by `|`, no trailing bar).
The client sends exactly the ids on the currently shown page of 6 (`(page-1)*6+1 .. page*6`), not the whole inbox.
The response is the same shape as `notify.read` (`messages`, `reward`, `_client_cache_update`).
Rules:

- Split on `|`, ignore empties and duplicates, drop ids that are not the caller's or already claimed (no error for those).
- Merge the loots into one `Loot` and grant once, so the toast shows one combined reward (`Loot.merge` exists).
- If the merged grant raises `error_equip_full`, fall back to claiming one by one and stop at the first failure; if nothing was claimed return that error, otherwise return success with what was claimed.
- Mails without gifts on that page are removed too.

### 1.5 `alerts.notify`

- Read at `game_ui/game_main_scene.lua` ~2157: `if game_data:getAlertsDataByKey("notify") then addTipsAnimByType(self.m_social_btn, 9)`. It is a truthiness test, so send a JSON boolean.
- `alerts` comes only from `user.main_page` (`game_data.updateMainPageByJsonData`), and the client REPLACES the whole `alerts` table on every `main_page` reply (`setAlertsDataByJsonData`).
- So `handlers.user_main_page` must build `alerts` as `{"is_double": False, "notify": <bool>, ...}` every time; never merge from a previous reply.
- `notify` = there is at least one mail with `claimed_at IS NULL AND expires_at > now`.
- The main scene runs `user.main_page` when it is entered again (the notify scene's `back()` calls `enterGameUi("game_main_scene")`), so the dot clears after claiming without any extra push.
- Friend messages do NOT set a client-side dot (no `friend` key is read anywhere). Do not invent one.

### 1.6 Store design for mail

Append one migration (never edit an applied one; current count is 11, so this is migration 12) to `store.MIGRATIONS`:

```sql
CREATE TABLE IF NOT EXISTS mail (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    mail_key   TEXT,                       -- idempotency key, e.g. 'welcome'
    sender     TEXT NOT NULL DEFAULT 'sys',
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL,
    gift       TEXT NOT NULL DEFAULT '[]', -- JSON [[type, id, count], ...]
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    claimed_at INTEGER                      -- NULL = still in the inbox
);
CREATE INDEX IF NOT EXISTS mail_by_player ON mail(player_id, claimed_at);
CREATE UNIQUE INDEX IF NOT EXISTS mail_once ON mail(player_id, mail_key) WHERE mail_key IS NOT NULL
```

- Claimed rows stay as tombstones so `mail_once` keeps a keyed mail from being re-sent; purge tombstones older than 30 days on read.
- Statements are split on `;` by `_statements`, so keep one statement per `;` and no trailing semicolon problems.
- Store API (SQLite only, no game rules, per `store.py` convention): `add_mail(uid, *, key, sender, title, content, gift, now, ttl)` returns the new id or `None` when the key already exists; `mail_inbox(uid, now)`; `mail_row(uid, mail_id)`; `claim_mail(uid, mail_id, now)` returns False if already claimed; `has_unread_mail(uid, now)`.
- Rules live in a new `sahht_server/mail.py` with `HANDLERS = {("api", "notify.messages"): ..., ("api", "notify.read"): ..., ("api", "notify.auto_read"): ...}` registered in `app.SESSION_HANDLERS`.
- Public helper for other modules: `mail.send(svc, uid, content, gift=(), *, key=None, title="", sender="sys", ttl_days=30, now=None)`.
- Default TTL 30 days (client has no expiry field).

How the server creates mail:

1. Welcome mail: in `player.ensure_starter` (inside its transaction, after the starter counter check) call `mail.send(..., key="welcome", content="Chào mừng đến với SAHHT!\nQuà tân thủ của bạn đây.", gift=[[15,0,2000],[6,3,2]])` (amounts are a design choice; they must be small enough not to disturb the tutorial economy). `veteran` accounts get it once too, because the key makes it idempotent, so also call it from `mark_user_login` for old accounts.
2. System rewards: any module that today grants directly and wants an inbox trail (level milestones, GM gifts, event compensation) calls `mail.send` with a stable key such as `level:30`, `gm:<unix time>`. A mail with `gift: []` is a plain notice.
3. Friend stamina gifts are NOT mail (they live in `friend_messages`, section 2.5); do not mix the two inboxes, the client reads them from different methods.
4. `tools/admin.py` and `gm.py` should get a `mail` command so the GM can send a test mail with a gift (needed to verify the screen).

### 1.7 What must change to open it

1. `data/scope_2018.json`: module `notify` -> `"open": true`. View 28 is already `{"module": "notify"}`, so it opens with it.
2. `tests/test_scope.py::test_every_module_with_a_handler_is_open` will fail until step 1 is done in the same change as the handlers.
3. `python3 -m tools.audit_scope` should then list view 28 as used and open.
4. Do not open view 213 or add `team_fight.*`.

## 2. friend

### 2.1 Which methods the visible screens use

| Method | Used by | Needed |
|---|---|---|
| `friend.friends` | scene tab 1, on entry | yes |
| `friend.messages` | scene tab 2, on first open | yes |
| `friend.read_message` | message rows (claim gift, accept, reject, ack) and "Nhận tất cả" | yes |
| `friend.search` | scene tab 3 search box | yes |
| `friend.apply_friend` | search result menu "Thêm bạn"; also the player-info pop (`game_player_info_pop`, `game_player_info_pop_new`), chat player pop, `game_pk`, guild chat | yes |
| `friend.remove_friend` | friend row menu "Xóa" | yes |
| `friend.send_gift` | the small stamina icon on each friend row | yes |
| `friend.battle` | friend row menu "Tỉ thí" | later, see 2.9 |
| `friend.guild_invite` | "Mời vào liên minh" menus | no: guilds do not exist, the default `error_not_open` popup is right |
| `friend.send_message`, `friend.del_message` | nothing (only listed in `game_url_config.lua`) | no |

The scene has three tabs; tags: 2 friends, 3 messages, 4 search. Entering the scene issues one request (`friend.friends`); tab 2 issues `friend.messages` once.

### 2.2 Social model (smallest coherent)

- Friendship is symmetric. Two accounts on the same server become friends through `apply_friend` -> the target accepts in the "messages" tab.
- Limits (design constants, not in any config): `FRIEND_MAX = 30`, stamina gift value `FRIEND_AP_GIFT = 6`, gifts a player may accept per day `ACCEPT_AP_TOP = 10`. They are shown to the player as `friend_len/friend_top` and `accepted/top`.
- Three seeded NPC friends so a single player can see the whole screen: uids `9001`, `9002`, `9003` (real uids are `id + 10000 >= 10001`, so they never clash), data in `server/data/npc_friends.json`: `{uid, name, level, role, combat, association_name}`. Every new player gets them as friends (store rows created in `ensure_starter`); they can be removed and re-added by search (an NPC accepts at once).
- NPCs "send" one stamina gift per day: the first time the player calls `friend.friends` or `friend.messages` on a new local day, insert one `action_point` message from each NPC friend (idempotent by `(player, npc, day)`).
- `online`: NPCs always true. Real players: true when the server saw a request from them in the last 5 minutes (keep a `Services.last_seen` dict updated in `app._dispatch`; no table needed).
- `role` is the role id used for the avatar (`createPlayerIconByRoleId(tostring(role))`); `user_status.role` is the fixed `1`, so use `1` for real players.
- `combat` for a real friend: `handlers.team_combat(svc, uid)`; for NPCs a constant.
- `association_name`: always `""` (shown through `tostring`, so a missing value would print the text "nil").
- Day boundary: `shop.period(shop.DAILY, now)` (UTC+7).

### 2.3 Tables (migration 13, or the same migration as mail)

```sql
CREATE TABLE IF NOT EXISTS friends (
    player_id  INTEGER NOT NULL REFERENCES players(id),
    friend_uid TEXT NOT NULL,              -- real uid or NPC uid
    since      INTEGER NOT NULL,
    PRIMARY KEY (player_id, friend_uid)
);
CREATE TABLE IF NOT EXISTS friend_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),   -- the recipient
    sort       TEXT NOT NULL,              -- add_friend | agree_friend | action_point
    send_uid   TEXT NOT NULL,
    day        TEXT NOT NULL DEFAULT '',   -- only for action_point
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS friend_message_once
    ON friend_messages(player_id, sort, send_uid, day);
CREATE TABLE IF NOT EXISTS friend_gift_log (
    player_id  INTEGER NOT NULL REFERENCES players(id),   -- the sender
    friend_uid TEXT NOT NULL,
    day        TEXT NOT NULL,
    PRIMARY KEY (player_id, friend_uid, day)
)
```

- Accepted gifts per day use the existing `counters` table: name `friend_ap_accepted`, period `period(DAILY, now)`.
- Friendship rows are written both ways in one transaction.
- `guild_invite` messages are not stored (guilds are out of scope), so the client branch for `sort == "guild_invite"` never appears.

### 2.4 `friend.friends`

Request: no params.

Response `data`:

```json
{
  "friends": [
    {"uid": "9001", "name": "Naruto Bóng", "level": 20, "combat": 1800, "role": 1,
     "online": true, "association_name": "", "has_send_gift": false}
  ],
  "friend_len": 3, "friend_top": 30,
  "accept_action_point": 0, "accept_action_point_top": 10
}
```

- `friends` MUST be an array and MUST be present (`friends:getFormatBuffer()` is UNGUARDED in the tab-1 callback). Order: the client numbers rows by position (`m_rank_label = index+1`), so sort by combat descending.
- Per friend: `level`, `name`, `combat`, `association_name`, `role`, `uid` are all read without a guard (`tostring()` or passed straight to a sprite/label); `online` (bool) and `has_send_gift` (bool, true when `friend_gift_log` has today's row for this friend) are tested for truthiness.
- `uid` MUST be a string (it is sent back as `target_id`).
- `initFriendData` reads the four counters only when present; send all four every time. If `accept_action_point` is present but `accept_action_point_top` is not, `>=` compares a number with nil and errors.
- `friend_len/friend_top` and `accept_action_point/..._top` fill two labels. The "Nhận tất cả" button is shown only when `accept_action_point < accept_action_point_top` AND the reply carries a `messages` array with at least one `sort == "action_point"` entry. Because `friend.friends` normally has no `messages`, the button shows only after `friend.messages`/`read_message` replies; that is the original behaviour.
- Any friends-list reply may also carry `messages`; `initFriendData` then rebuilds the message tab from it. Do not add `messages` to `friend.friends` unless it is complete.

### 2.5 `friend.messages`

Request: no params.

Response `data`: `{"messages": [...], "friend_top": 30, "friend_len": 3, "accept_action_point": 0, "accept_action_point_top": 10}` (the four counters are optional here but keep the button logic right, so send them).

Per message (all UNGUARDED in the cell builder: `send_level`, `send_name`, `send_combat`, `send_role` are passed to labels or `tostring`):

```json
{"id": "41", "sort": "action_point", "send_uid": "9001", "send_name": "Naruto Bóng",
 "send_level": 20, "send_combat": 1800, "send_role": 1}
```

- `sort` is one of `action_point` (button "nhận", gives stamina), `add_friend` (agree and reject buttons), `agree_friend` (a notice "Đồng ý kết bạn với bạn" with a "xem" button). Any other value draws no text and no button, so never invent one. `guild_invite` needs `send_association_name`; not used.
- `send_uid` is read by the avatar tap (`user.info`, see 2.8) and must be a string.
- Order: newest first.
- `id` is a string; it is sent back as `message_id`.
- Entry generation: on a new day the server first inserts the NPC `action_point` messages (2.2).

### 2.6 `friend.read_message`

Request variants (all GET):

| Params | Meaning |
|---|---|
| `message_id=<id>` on an `action_point` message | claim the stamina gift |
| `message_id=<id>&agree_friend=1` on `add_friend` | accept |
| `message_id=<id>&agree_friend=0` on `add_friend` | reject (just delete) |
| `message_id=<id>` on `agree_friend` | acknowledge (delete) |
| `accept_all=1` | claim every `action_point` message up to the daily cap |

Response `data` for every variant: the FULL current friend state, so the scene can rebuild both tabs from it:

```json
{
  "messages": [...remaining...], "friends": [...current friends...],
  "friend_len": 4, "friend_top": 30, "accept_action_point": 1, "accept_action_point_top": 10,
  "reward": {"action_point": 6}
}
```

- Every variant calls `refreshTab2(gameData)` which runs `initFriendData` (reading `messages`, `friends`, and the four counters) and then rebuilds the list; the claim variants (`message_id` alone, `accept_all`) also run `rewardTipsByJsonData(data.reward)`.
- `reward` is `{"action_point": N}`; the client toast reads `dataTable.action_point`. Stamina itself arrives through `user_status.action_point` (apply it with `rewards.grant(Loot(action_point=N))` or `store.change_action_point`).
- After an accept (`agree_friend=1`) the client sets its own friends cache stale (`m_tFriendData.init = false`) and re-fetches `friend.friends` when tab 1 opens, but also shows "friend_hadbeen_friedn_tips"; the server must already have created both friendship rows and an `agree_friend` message in the applicant's inbox (unique index prevents duplicates).
- Rules: claiming above the daily cap returns `fail("error_limit", "Hôm nay bạn đã nhận đủ thể lực từ bạn bè.")` (popup, no callback); `accept_all` stops silently at the cap; accepting when `friend_len >= friend_top` returns `error_limit` ("Danh sách bạn bè đã đầy.") and keeps the message; messages that do not belong to the caller -> `error_param`.
- Accepting an `add_friend` whose sender is already a friend just deletes the message.
- Stamina uses the player's real maximum: `change_action_point` is not capped at `ap_max` for gifts in `rewards.grant` (same as stamina items); keep that behaviour.

### 2.7 `friend.search`

Request: `target_id=<text>` (URL-encoded; the client sends `util.url_encode`, decode with `unquote` like `user_rename` does).
Response `data`: `{"user": [ {uid, name, level, combat, role, online, association_name}, ... ]}`.

- `user` MUST be an array (the client does `self.m_tSearchData.data = decode(user)` and then `#` on it; UNGUARDED, `user:getFormatBuffer()`).
- Match order: exact uid (digits) first, then case-insensitive exact name, at most 10 rows. Include NPCs by name or uid. Include the caller if matched (the client itself blocks self-invites for guilds; for `apply_friend` the server refuses self).
- No match: return `user: []` (success). A popup for "not found" is not needed, the empty list shows nothing.
- The reply is also passed through `initFriendData`, so adding the four counters is optional but harmless.
- Search rows show no gift icon; the row menu offers "Thêm bạn" and "Mời vào liên minh".

### 2.8 `friend.apply_friend`, `friend.remove_friend`, `friend.send_gift`

`friend.apply_friend`: `target_id=<uid>` (some callers also pass nothing else). Response `{}` (the callback ignores `data`; it only shows a client tip using the name it saved).

- Target is an NPC: friendship is created at once (both rows), response `{}`.
- Target is a real player: insert an `add_friend` message into the target's inbox (unique, so repeated taps are idempotent and answer success).
- Refusals (popup text from `msg`): self -> `error_param` "Không thể kết bạn với chính mình."; unknown uid -> `error_param`; already friends -> `error_friend` "Hai bạn đã là bạn bè."; caller full -> `error_limit` "Danh sách bạn bè của bạn đã đầy.".
- A pending reverse request (the target already applied to the caller) is an immediate accept.

`friend.remove_friend`: `target_id=<uid>` (a `message_all` flag appears only in a comment). Delete both rows and the pair's stamina messages.
Response `data` MUST be `{"friends": [...remaining...], "friend_len": N, "friend_top": 30, ...}`: the callback does `friends:getFormatBuffer()` UNGUARDED.
Removing a non-friend returns the unchanged list (success).

`friend.send_gift`: `target_id=<uid>`. The icon is shown only while `has_send_gift ~= true`, and after a reply the client sets `has_send_gift = true` locally, so the server must refuse a second gift the same day (`error_limit` "Hôm nay bạn đã tặng thể lực cho bạn này.").

- Insert `friend_gift_log(player, friend, day)`; if the target is real, insert an `action_point` message into the target's inbox keyed by `(sender, day)`; if it is an NPC do nothing more (NPCs gift on their own, 2.2).
- Response `data`: `{}` is enough (only the callback firing matters). Sending costs the sender nothing.
- Only friends can be gifted (`error_param` otherwise).

`user.info` (head tap in any friend list and the "Xem thông tin" menus):

- Not served today. Without it the tap shows the standard "Tính năng chưa mở." popup, which is acceptable for the first cut.
- When added: `data.new_data` must be the target's `cards.open`-style document (reuse `handlers.cards_open` pieces: `cards`, `alignment`, `equip_pos`, `formation`, `equip`, `gem`, `gem_pos`, `items`, `battle_card_num`, the empty `formation_bonus*`/`god_field_ids`) PLUS `new_data.user = {uid, name, level, role, title, association_id: 0, association_name: "", combat}`.
- `game_player_info_pop.init` feeds `new_data` into `game_player_data:updateCardsOpenByJsonData` and reads `boss_data.user.*`; `association_id == 0` decides which action buttons show. For an NPC build a fixed 5-hero document from `data/npc_friends.json`.

### 2.9 `friend.battle` (optional, phase after PvP exists)

- Request `target_id=<uid>`. The client sets `game_data:setBattleType("friend_pk")` and enters `game_battle_scene` with the raw reply.
- The reply must be the same record as a campaign fight (`{"has_battled": 1, "battle": {"winer", "init", "battle": {frames}}}`, see `campaign.run_battle`), but the defenders are the friend's hero cards: `init.dfd[i]` needs `card_id` = the hero `c_id` (the scene looks them up in `character_detail` for `friend_pk`, not in the enemy tables), so no `animation`/`rgb_sort` is required; `dfd_skill` is the friend's leader skills, `dfd_role` their role id, `dfd_name`/`dfd_lv` their name and level.
- There is no reward and nothing persisted. It is a battle against a snapshot of the friend's team (or an NPC team from the json).
- Until then leave it unserved: the default reply is `error_not_open` "Tính năng chưa mở." (popup).

### 2.10 What must change to open it

1. `data/scope_2018.json`: module `friend` -> `"open": true` (view 27 follows). `friend.guild_invite`, `friend.battle`, `friend.send_message`, `friend.del_message` stay handler-less and answer `error_not_open`.
2. Seed NPC friends in `player.ensure_starter` and for existing accounts at `mark_user_login` (idempotent by counter `friend_seed`).
3. New module `sahht_server/friends.py` (rules) + store methods, registered in `app.SESSION_HANDLERS`.
4. Tests in `tests/test_friends.py`: two accounts befriend, stamina gift once per day, daily cap, removal, NPC auto accept, search by uid and name.

## 3. gift (city treasure chests): do not implement

Evidence that the feature is dead in this client:

- `gift.curt_city_gift` and `gift.receiving_gift` are only referenced by `game_ui/game_treasure_chest.lua` and `game_pop/game_treasure_chest_pop.lua`.
- Nothing calls `addTreasureChest` or `addPop("game_treasure_chest_pop")`. The only trigger, in `game_ui/game_small_map_scene.lua` ~line 915-936 (button tag 2, "rương" / rate button), is commented out. Tag 2 now sends `reward.index` and opens `game_offer` (the daily bounty screen of module `reward`, phase 1 but a different task).
- The config the screen needs is gone: `map_main_story.config` rows have only `chapter, jingyingfirst, jingyingsweep, open_level, stage_id, stage_name, stage_story, tmx, wanted`; the chest screen reads `rate_loot1..3` and `rate1..3` from them (UNGUARDED `rate:toInt()`), which no row has.
- The `isViewOpenByID` calls near `game_small_map_scene.lua:1806` gate `mainSceneTips` (views 3 "reward", 4 "day", 8 "online", 9 "sign", 10 "open"): the little tip bubble on the small map driven by `alerts.reward`, `alerts.daily`, `alerts.once`. They belong to the `reward` / `daily_award` modules, not to `gift`.

Decision: keep module `gift` closed with its reason updated to "mã chết: không còn nút nào gọi, thiếu rate_loot trong map_main_story". If a future client revives it, the shapes are: request `city=<city id>`; reply `{"curt_gift": [gift ids claimable], "old_gift": [gift ids claimed]}` with gift id `= cityOrderId * 10 + chestIndex(1..3)`; `gift.receiving_gift` takes `gift=<that id>` and answers the same two arrays plus `reward`.

Related, for the lead (not part of this task): views 3/4/8/9 become useful only when `alerts.reward`, `alerts.daily`, `alerts.once` are served by `main_page` and the `reward.index` / daily sign screens exist.

## 4. Free gacha draws

### 4.1 What the client reads

`game_ui/game_gacha_scene.lua` (hero recruiting). Everything is already implemented client side; the server sends the data.

- `gacha.get_all_gacha` reply: `gacha_all`, `gacha_expire`, `gacha_freetimes`, `energy_slot`, `discount_flag`, `guild_reward_sort`, `score`. The current server sends `gacha_freetimes: {}` and `gacha_expire: {}`.
- `gacha_freetimes` is a map pool id (string) -> seconds:
  - key absent or value `-1`: no free draw on this pool; the normal cost shows and the money check runs.
  - `0`: a free draw is available NOW; the card shows the "Miễn phí" label (`m_free_label`) and `getGacha` skips the money check.
  - `N > 0`: seconds until the free draw; the card shows `HH : MM giờ sau miễn phí`, counting down locally from `os.time() - m_enterUiTime`. When the local countdown reaches 0 the label switches to "Miễn phí" without a request, and `getGacha` (which tests `freetimes - elapsed > 0`) also skips the money check.
- `getGacha` itself sends the same `gacha.get_gacha?gacha_type=<pool>` for free and paid draws. No extra parameter exists, so the SERVER decides whether a draw is free.
- `gacha.get_gacha` reply fields read: `gacha_all` (UNGUARDED `getNodeWithKey("gacha_all")` passed to `setGachaDataByJsonData`), `new_card` (UNGUARDED), `score` (UNGUARDED `:toInt()`), `energy_slot` (UNGUARDED), `reward`, and `gacha_freetimes` (optional: when present it REPLACES the whole local table, so send every pool's value, not just the one drawn). After the reply the client resets `m_enterUiTime = os.time()`, so all values are seconds relative to the reply.
- `alerts.gacha` is read in `game_main_scene.lua` ~2111, but it puts the red dot on `self.m_shop_btn`, not on the recruit button. Do not set it for free draws; the recruit button already has its own dot rule (silver >= 300, `updateShowTips("gold_enough")`).
- `energy_slot`, `discount_flag` (0 = off), `guild_reward_sort` (0) stay as they are.

### 4.2 What is missing on the server

- `gacha.py` never returns anything but `{}` for `gacha_freetimes` and always charges `pay(...)`.
- No config row defines free draws: `gacha.config` has no `free_*` or `cd` field (19 pools, keys `add_point, bad_item, bad_point, consume_sort, end_time, gacha_name, gacha_num, gacha_sort, gacha_team, get_card, get_num, good_item, good_point, image*, is_box, piece, quality, star_time, story, use_gacha, use_level, value`). The cooldown rule has to be a server design constant.
- The equipment gacha screen (`game_ui/game_gacha_equip.lua`) uses the identical `gacha_freetimes` protocol; if `equip_gacha.py` should get free draws too, reuse the same helper.

### 4.3 Design

- Constant table in `gacha.py` (or `data/gacha_free.json`): `FREE_POOLS = {"112": 5 * 3600, "221": 48 * 3600}`: the unlimited silver-cost pool (team 20) is free once per 5 hours, the unlimited coin-cost single-draw pool (team 30) once per 48 hours. Both are `gacha_sort 0` pools, so draw counts are unaffected. The numbers are a game-design choice; the client works with any positive cooldown. Only list pools that are in `_available` for the player.
- State: counter `gacha_free:<pool>` stores the epoch second at which the next free draw becomes available (`0` or missing = available now). Use `store.counter/set_counter` with the default empty period.
- `free_times(svc, uid, now, available)` builds the map: for each pool in `FREE_POOLS` that is in `available`, `max(0, next_free_at - now)`; leave other pools out. Add it as `gacha_freetimes` to BOTH `get_all_gacha` and `get_gacha` replies.
- `get_gacha`: inside the existing transaction, if the pool is in `FREE_POOLS` and `next_free_at <= now`, skip `pay(...)` and set `next_free_at = now + cooldown`; otherwise charge as today. The draw still increments `gacha:<pool>` and the pity score and grants heroes exactly as now.
- Do not let a free draw be the tutorial path: pool 999 (tutorial) and chain pools 101, 102, 111 stay paid.
- Do not add `alerts.gacha`.
- Tests: a never-drawn free pool reports `0`, the draw costs nothing and the next reply reports about `cooldown`, a second draw before the cooldown is charged, `gacha_freetimes` present in both replies.

## 5. "Điểm thu hồi" achievement bar: not a bug, already served

- Client: `game_ui/game_small_map_scene.lua` ~line 987 calls `game_util:setWordAchieve(achieve_btn, expBar, data.world_level, data.world_score)` with `data` = the `private_city.open` reply (so it shows in a city's small map, not on the world map). Defaults are level 1, score 0.
- `game_util:setWordAchieve` (`game_util.lua` ~8289): looks up `integration_world[<world_level>]`, `maxScore = top` (0 means 100), draws `floor(100 * min(maxScore, score) / maxScore) %`.
- The tap on the button (tag 5) sends `private_city.world_score` and opens `game_pop/word_achieve_pop.lua`, which reads `world_level`, `world_score`, `world_reward_log` and claims with `private_city.get_world_reward?level=N` (reply: `world_score`, `world_level`, `world_reward_log`, `reward`).
- Config: `integration_world.config` has 5 rows: level 1 `top` 200, 2 -> 700, 3 -> 1500, 4 -> 2300, 5 -> 3127, each with a `reward` list.
- Server: this is already implemented in `server/sahht_server/campaign.py` (`_world_progress`, `world_map`, `city_open`, `world_score`, `get_world_reward`, tests in `tests/test_campaign.py` lines 65-99); the score is the number of cleared buildings (the original rule is not recoverable from the client; 3127 fits "3274 attackable buildings").
- Why it still looks like 0%: tier 1 needs 200 points and the bar prints `floor(100 * score / 200)`. The test account (2 buildings) therefore shows 1%, and one cleared building shows 0%. This is correct arithmetic, not a missing feed.
- Doc fix needed: `CLAUDE.md` still lists the bar as "stays at 0%... source unknown"; `server/README.md` (line 52) already describes it correctly. Update `CLAUDE.md` when convenient (do not edit it from this research task).
- Emulator check to close the item: clear a few buildings, open the small map and confirm the percent grows; the elite replies (`elite.py` line 85) also carry the two fields.
- Optional product decision: if a visibly moving bar is wanted early, change the score to something faster than one point per building (for example 10 per building or points for first clears), at the cost of departing from a rule that fits the published 3127 ceiling.

## 6. item.view, item.exchange and the bag

### 6.1 Who uses them

- `item.view` (no params) is the data load for `game_ui/game_exchange_scene.lua`, opened from the menu button "Đổi đồng đội" (`btnTag 100002`, view 21, `openType = 1`) and "Đổi trang bị" (`btnTag 508`, view 26, `openType = 2`), in both `game_function_pop.lua` and `ui_secretary_detaile.lua`. `game_ui/game_magic_list.lua` (talisman, tab 3) also calls it, but talismans are out of scope.
- `item.exchange` (`change_id=<exchange.config key>`) is called by the confirm dialog of the same scene, and by the talisman screen.
- `game_pop/game_item_card_pieces_pop.lua` (the shard popup in the bag) makes no network call.
- The scene lists, from the client's own copy of `exchange.config`, every row whose `need_item` the player owns (read from the reply's `items`), so the server never sends a "catalog".

### 6.2 `item.view`

Request: none.

Response `data`:

```json
{
  "items": {"1001": [20, 7], "1501": [3]},
  "exchange_log": {"1": 2, "10": 1}
}
```

- `items`: item id (string) -> list of stack counts. This is exactly `handlers.item_stacks(svc, uid)` (the same shape as `cards.open.items`); the client sums the list per item. UNGUARDED: `pairs(items[tostring(need_item_id)])`; an item with count 0 must be absent, not `[]`.
- `exchange_log`: exchange key (string) -> number of exchanges already done by this player (lifetime counter). UNGUARDED: `self.m_exchange_data.exchange_log[key]` is indexed whenever a row has a `need_num` list (all 426 rows do), so `exchange_log` MUST be present, even as `{}`.
- Optional `reward` (the scene runs `rewardTipsByDataTable(reward)` on it; nil is fine).
- Required count for the next exchange: `need_num[min(times, len(need_num) - 1)]` (every row has exactly one entry today, 5 to 100).

### 6.3 `item.exchange`

Request: `change_id=<exchange key>`.

Response `data`: the same as `item.view` (the scene calls `backData(gameData)` again) plus `reward` and `_client_cache_update`:

```json
{"items": {...}, "exchange_log": {...}, "reward": {"cards": ["88"]}, "_client_cache_update": {...}}
```

Rules from `exchange.config` rows (`change_id [[type, id, count]]`, `change_sort`, `change_time`, `need_item`, `need_num [n]`, `need_food`, `need_metal`, `refesh`):

- Validate `change_id` is an integer key of the config; else `error_param`.
- Serve `change_sort` 1 (hero, `change_id` type 5, 245 rows, costs `need_food` food) and 2 (equipment, type 7, 139 rows, costs `need_metal` metal). The client groups rows by `change_sort`: 1 -> tab "đồng đội", 2 -> "trang bị", 4 -> pets. Sorts 3 (talisman, one row), 4 (pet, 18 rows) and 5 (type 49, 23 rows) have no served system: answer `error_not_open` "Tính năng chưa mở." (sorts 3 and 5 are ignored by the exchange scene's list anyway).
- Spend inside one transaction: `need_num[...]` of `need_item` (`store.change_items(uid, {need_item: -n})` returns False when short -> `Refused("error_item", "Không đủ mảnh.")`), plus food or metal through `rewards.pay` (`error_not_enough` when short; the scene already pre-checks and shows `game_normal_tips_pop`).
- Grant `Loot.of(change_id)` with `rewards.grant`; heroes beyond card 38700 raise `error_scope` automatically; a full equipment bag raises `error_equip_full` (rolls everything back).
- `change_time`: maximum exchanges per row (`9999` effectively unlimited; `1` for the 18 pet rows). Refuse with `error_limit` when `exchange_log[key] >= change_time`.
- `refesh` is 1 for the 408 unlimited rows and 0 for the 18 one-shot pet rows; it looks like a "refresh" flag with no effect when `change_time` is already enforced. Ignore it.
- Increment the log through `store.set_counter(uid, f"exchange:{key}", times + 1)` (a counter per row; `item.view` builds `exchange_log` from all `exchange:*` counters - add a `store.counters_with_prefix(uid, "exchange:")` helper, or keep the keys in a single JSON counter).
- After a successful exchange `item.exchange` also finishes tutorial step 503 on the client side (`game_guide_controller:gameGuide("send","5",503)`); `player.seed_guides` already completes team 5, so nothing is needed server side.
- Return `_client_cache_update` = `merge_cache(granted.cache, client_cache(svc, uid, items=[need_item]))` so the spent shards leave the bag and the new hero/equipment appears.

### 6.4 `item.use` status (already being written)

The bag's "Dùng" button, the batch-use pop and the pick pop all call `item.use` with `item_id`, `num` and, for optional boxes, repeated `type_list` / `type_list_1`; the client shows `data.effect` as a toast.
`item_use.py` in the working tree serves `is_use` 1 (chest), 2 (stamina), 4 (crystal pack), 7 and 8 (hero / equipment bag), 15 (optional exchange) and 19 (exp ball). It answers `error_item` "Vật phẩm này chưa dùng được." for the remaining kinds. Counts in `item.config`: kind 0 (not usable, 1542 items), 1 (1545), 15 (610), 17 (38, titles), 18 (8, battlefield coins), 19 (8), 2 (4), 4 (4), and one item each of 6, 7, 8, 9, 10, 11, 13, 14, 16, 20, 21, 22, 23, 24.
Gaps worth scheduling next, cheapest first:

- Kinds 22 (hero bag +5, item 9101343) and 23 (equipment bag +5, item 9101345) are duplicates of kinds 7 and 8: map them to `CARD_BAG` and `EQUIP_BAG` in `item_use._apply` (one line each). Kinds 21 (item bag) and 24 (talisman bag) have no bag in this server, so keep them refused.
- Kinds 9, 10, 11 (resource piles "Đống ..."; `use_effect [8]` = hours of production): give `8 * hourly rate` of food, metal or energy; needs a rate rule (the harbor building tables) before it is meaningful.
- Kind 13 (stamina-like "Thuốc tinh lực" for the commander system), 14 (soul bag), 6 and 16 (arena and god-field challenge letters), 17 (title items), 18 (event coins), 20: depend on systems that are out of scope; keep refused.

### 6.5 What must change to open views 21 and 26

1. Register `item.view` and `item.exchange` (new `sahht_server/exchange.py` with `HANDLERS`) in `app.SESSION_HANDLERS`.
2. `data/scope_2018.json`: replace views 21 and 26 by `{"module": "item", "reason": "Đổi đồng đội / Đổi trang bị (game_function_pop.lua, tags 100002 and 508): item.view, item.exchange"}`. Module `item` is already open (phase 0), so `closed_views()` stops listing them.
3. Check `python3 -m tools.audit_scope` and `tests/test_scope.py`.
4. The `module: item` rule also keeps view 21 and 26 consistent with the test that every module with a handler is open.
5. Emulator check: give the test account 20 hero shards (`python3 -m tools.admin give`, item 1001) and 1000 food, open "Đổi đồng đội", exchange, and confirm the shards vanish and the hero appears without re-login.

## 7. Shape traps, in one list

1. `notify.*` and `friend.*` list fields (`messages`, `friends`, `user`) must always be JSON arrays that are present; the client does `#` or `getFormatBuffer()` on them without a guard.
2. `notify.read` / `auto_read` replace the scene's whole list with the reply, so they must return `messages` (the remaining mails) as well as `reward`.
3. `gift` of a mail is `[]` for a plain notice, never `null` or missing; a plain notice must still be claimable through `notify.read`.
4. `alerts` is overwritten wholesale by every `user.main_page` reply; `notify` must be recomputed there every time.
5. `friend.friends` must send all four counters together; `accept_action_point` without `accept_action_point_top` is a Lua compare error.
6. `friend.remove_friend` must reply with `friends` (UNGUARDED), and every friend-reply `uid` must be a string.
7. `friend.read_message` replies carry the whole friend state (`messages`, `friends`, the four counters) plus `reward`; stamina arrives through `user_status.action_point`.
8. Message `sort` may only be `action_point`, `add_friend` or `agree_friend`; anything else draws a blank row.
9. `gacha_freetimes`: a value of `0` means "free now"; the whole table replaces the client's copy, so always send every pool; absent or `-1` means paid.
10. `item.view` must send `exchange_log` (UNGUARDED index) even when empty, and `items` entries are stack lists, with zero-count items omitted.
11. `item.exchange` must return the full `item.view` shape again plus `_client_cache_update`; only sorts 1 and 2 are servable.
12. `gift.*` is dead code: no live caller and no `rate_loot` data, leave it closed.
13. Opening a module is a two-line scope change, but `test_every_module_with_a_handler_is_open` forces it to happen in the same commit as the handlers.
