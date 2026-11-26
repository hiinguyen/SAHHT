# Giai đoạn 1: nhiệm vụ ngày và thành tựu (module `reward`)

Ngày: 2026-11-26.
Trạng thái: bản nghiên cứu, chưa viết code. Nguồn: Lua đã giải mã trong `decompiled/lua`, config trong `decompiled/apk/assets/config`.
Mọi dòng "không guard" nghĩa là client đọc trường đó mà không kiểm tra nil, thiếu là lỗi Lua.

## 1. Màn hình nào thật sự dùng method nào

Bản client Việt hóa đã tự sửa phần này (các chú thích `SHHHT: B8`).
`game_pop/game_daily_wanted.lua` đã bị "về hưu": hàm `create` của nó bỏ qua dữ liệu và gọi thẳng `reward.diary_index`, rồi mở `game_daily_task_pop`.
Vì vậy mọi nút "Nhiệm vụ" trên màn chính cuối cùng đều dẫn đến một popup duy nhất: `game_pop/game_daily_task_pop.lua` (nhiệm vụ ngày, 10 dòng và 4 rương điểm hoạt động).
Nút 41, nút 35 khi `alerts.reward == true`, tab 4 của popup và hàng 90004 của thư ký vẫn phát `reward.index` TRƯỚC (nút 35 mặc định đi thẳng `reward.diary_index`).
Callback chỉ chạy khi status là `"0"` có `data`, nên `reward.index` phải trả thành công thì các đường đó mới mở được popup.

| Method | Ai gọi | Kết luận |
|---|---|---|
| `reward.diary_index` | `game_main_scene.lua` 1146/1158 (nút 35), `game_daily_wanted.create`, `game_daily_wanted` tab 3, `ui_secretary_detaile.lua` 365 (hàng 90005, view 4), `open_door_main_scene.lua` | CẦN. Màn nhiệm vụ ngày. |
| `reward.diary_score_award` | `game_daily_task_pop.lua` 274 (chạm rương) | CẦN. |
| `reward.index` | `game_main_scene.lua` 1125/1153 (nút 41 và nút 35 khi `alerts.reward == true`), `game_daily_task_pop.lua` 65 (nút 4), `ui_secretary_detaile.lua` 359, `game_small_map_scene.lua` 943 (nút `m_rate_btn` ở mọi thành phố thường trừ 100/101), `game_normal_tips_pop.lua` 121, `game_task_scene.lua` (chết) | CẦN. Hai vai trò: (a) tín hiệu thành công cho chuỗi mở popup nhiệm vụ ngày (nội dung bị bỏ qua); (b) dữ liệu "Treo thưởng" của `game_ui/game_offer.lua` từ bản đồ nhỏ. |
| `reward.wanted_award` | `game_offer.lua` 277 | CẦN nếu làm treo thưởng ở bản đồ nhỏ. |
| `reward.once_index` | `game_main_scene.lua` 1177 (nút 10067 Phúc lợi), `game_fuli_activity_scene.createAwardUI`, `ui_secretary_detaile.lua` 90003 (`game_new_reward`) | CẦN. Thành tựu. |
| `reward.once_award` | `game_fuli_subui_award.lua` 130/139, `game_new_reward.lua` | CẦN. |
| `reward.gift_award` | `game_activity.lua` 298 (tab "Sinh tồn vật tư", view 49) | KHÔNG thuộc nhiệm vụ. Giữ đóng cùng view 49. |
| `reward.daily_award`, `activate_daily_task`, `inactivate_daily_task`, `refresh_daily_task`, `daily_score_award` | chỉ trong `game_daily_wanted.lua` (UI không bao giờ dựng nữa) và `game_task_scene.lua`/`game_task_pop.lua` (không ai `enterGameUi`) | KHÔNG dùng. Không cần handler; đóng bằng `error_not_open`. |
| `reward.daily_score_index`, `get_daily_reward`, `get_score_reward`, `fast_finish_daily_award` | có khóa trong `game_url_config.lua`, không có nơi nào gọi | KHÔNG dùng. |
| `reward.receive_version_reward` | không ai gọi (chỉ khóa URL; nút quà bản mới chỉ đọc `alerts.has_version_reward`) | KHÔNG dùng. |
| `reward.opening_index`, `opening_award` | `game_opening_pop.lua`/`game_vipguide_pop.lua`, nút kaifu (tag 1032, view 10) | KHÔNG thuộc phạm vi. View 10 đang đóng, giữ nguyên. |

Hệ quả: tập handler tối thiểu là 7 method: `reward.index`, `reward.diary_index`, `reward.diary_score_award`, `reward.once_index`, `reward.once_award`, `reward.wanted_award` (và `reward.gift_award` không làm).

## 2. Các cổng hiển thị (view id) mà màn nhiệm vụ kiểm

Tên gốc trong `inreview.config`: 3 "Lĩnh thưởng" (领奖), 4 "Hằng ngày" (日常), 5 "Nhiệm vụ" (任务), 8 "Lĩnh thưởng đếm ngược" (倒计时领奖).
Các lý do hiện ghi trong `data/scope_2018.json` cho view 3, 4, 8 là sai (chúng không phải "mẹo trên bản đồ nhỏ"). Nguyên nhân thật:

| View | Dùng ở | Tác dụng |
|---|---|---|
| 3 | `game_main_scene.top_btn_name_tab` (nút Phúc lợi `m_conbtn_fuli`); `ui_secretary_detaile` hàng 90003 | Hiện nút Phúc lợi, từ đó mở `game_fuli_activity_scene` (thành tựu nằm trong đó). |
| 4 | `game_main_scene.lua` 2230 (nút Nhiệm vụ `m_task_btn`); `ui_secretary_detaile` hàng 90005 | Hiện nút Nhiệm vụ ngày. |
| 8 | `game_main_scene.lua` 2145 (chấm đỏ `alerts.once` trên nút Phúc lợi); `game_fuli_activity_scene` tab "online" (`InReviewID = 8`) | Tab thưởng online và chấm đỏ thành tựu. |
| 50, 51 | `game_fuli_activity_scene` tab "level" và "advanture" (`InReviewID`) | Hai tab thành tựu cấp độ và thu hồi. Hiện không có trong `views` nên mặc định hiện. |
| 5 | tab "arena" của Phúc lợi (`InReviewID = 5`); hàng 90004 của thư ký (đã ẩn) | Thành tựu hạng đấu trường. GIỮ ĐÓNG (đấu trường chưa có). |
| 9, 49, 126, 151, 11, 173, 37, 41 | các tab khác của Phúc lợi (điểm danh, sinh tồn vật tư, thẻ tháng, kế hoạch trưởng thành, thông báo, VIP, mã quà, mã mời) | Phải ĐÓNG hết (đang đóng). |
| 184 | tab "quartervip" (thẻ quý) của Phúc lợi (`InReviewID = 184`) | Hiện KHÔNG có trong `views` nên mặc định HIỆN khi mở view 3, và tab này gọi `pay_award.index`. Phải thêm vào scope và đóng. |

Lỗi của công cụ kiểm: `tools/audit_scope.py` dòng 29, `VIEW_RE` chỉ bắt `InReviewId`, trong khi Phúc lợi và `game_hero_info_pop.lua` viết `InReviewID` (chữ D hoa).
Vì vậy các view 5, 11, 37, 173 bị ghi "không nơi nào trong Lua gọi view này" và 184, 18, 19, 20, 33, 34 không được liệt kê.
Sửa regex thành `InReview[Ii][Dd]` rồi chạy `--draft` để xem phần chênh.

Điều kiện hiển thị khác trên màn chính (cấp độ):
- Nút Nhiệm vụ chỉ hiện khi `level >= 3`; dưới 3 bị `setVisible(false)`.
- Với `level >= 3` và không phải lần đăng nhập đầu trong ngày (cờ cục bộ `m_task_btn_date`), nút bị ẨN nếu `alerts.reward == nil và alerts.diary == nil` (dòng 2224). Vì vậy `alerts` phải luôn có ít nhất một trong hai khóa.
- Chấm đỏ Phúc lợi từ `alerts.once == true` chỉ hiện khi `level >= 3` và view 8 mở.

## 3. Thay đổi để mở (server)

Cổng trong `scope.py`: `module_open` chỉ ảnh hưởng `closed_views()` (danh sách `inreview` của `user.main_page`).
Việc handler có chạy hay không do `app._resolve` quyết định: có handler đăng ký trong `SESSION_HANDLERS` thì chạy, không có thì quiet/`error_not_open`.
Vì vậy phải làm cả hai việc:

1. Tạo `sahht_server/quests.py` với `HANDLERS = {("api", "reward.index"): ..., ...}` và thêm `**quests.HANDLERS` vào `SESSION_HANDLERS` trong `app.py` (dòng 22-30).
2. Trong `data/scope_2018.json`:
   - đổi `modules.reward.open` thành `true` (mở view 3, 4, 8);
   - sửa `reason` của module và của view 3, 4, 8 cho đúng;
   - thêm `"184": {"open": false, "reason": "tab thẻ quý của Phúc lợi, pay_award chưa làm"}`;
   - thêm `"50": {"module": "reward", ...}` và `"51": {"module": "reward", ...}` cho rõ (không bắt buộc);
   - sửa reason của view 5, 11, 37, 173 cho đúng ("tab Phúc lợi `InReviewID`").
3. Không đổi `modules.wanted` (phase `null`, là hệ truy nã `wanted.*` khác). Treo thưởng của bản đồ nhỏ thuộc `reward.index`/`reward.wanted_award`, nên nằm trong module `reward`.
4. `tools/audit_scope.py`: sửa `VIEW_RE`, và thêm `reward_once`, `diaryscore`, `wanted` vào `server_reward_sources` (xem mục 8) để bài test "không phần thưởng nào dẫn đến tướng sau 38700" phủ cả nguồn thưởng mới.
5. `data/scope_2018.json` hiện không có mục `quiet` cho `reward.*`; không cần thêm.

Khuyến nghị thứ tự: mở view 4 + 3 + 8 cùng lúc với module (không tách được vì chung module), nhưng có thể giữ tab online đóng bằng cách tách view 8 thành `{"open": false}` cho đến khi có bộ đếm online (mục 5.3).

## 4. Nhiệm vụ ngày: `reward.diary_index` và `reward.diary_score_award`

### 4.1 Config

`reward_diary.config` (10 dòng, khóa "1".."10"): `num` (số lần cần), `reward_score` (điểm cho MỖI lần), `story`, `target_data` `[1]`, `target_sort` (loại sự kiện).
`diaryscore.config` (khóa là ngưỡng điểm): `"20": [[1,0,20000]]` (lương thực), `"50": [[2,0,20000]]` (kim loại), `"80": [[9,0,100]]` (xu), `"100": [[9,0,200]]`.

| id | target_sort | Sự kiện | num | điểm/lần | tối đa | Server hiện có? |
|---|---|---|---|---|---|---|
| 1 | 78 | Thám hiểm (đánh) công trình bất kỳ, càn quét không tính | 5 | 5 | 25 | CÓ (`campaign.recapture`) |
| 2 | 28 | Huấn luyện đồng đội (`school.*`) | 3 | 8 | 24 | KHÔNG |
| 3 | 24 | Nâng cấp kỹ năng đồng đội | 2 | 8 | 16 | CÓ (`cards.card_skill_levelup`) |
| 4 | 27 | Cải tạo thuộc tính đồng đội (`game_hero_culture_scene`) | 1 | 10 | 10 | KHÔNG |
| 5 | 35 | Cường hóa trang bị | 2 | 10 | 20 | CÓ (`factory.equip_levelup`, `equip.all_equip_levelup_auto`) |
| 6 | 38 | Khiêu chiến đấu trường | 2 | 10 | 20 | KHÔNG |
| 7 | 74 | Ác Long Tấn Công (world boss) | 1 | 15 | 15 | KHÔNG |
| 8 | 68 | Tham gia chiến tranh tài nguyên | 2 | 10 | 20 | CÓ (`active.py` chương 1) |
| 9 | 76 | Tham gia ải kinh nghiệm | 2 | 10 | 20 | CÓ (`active.py` chương 80) |
| 10 | 77 | Tham gia thử thách sinh tồn | 1 | 15 | 15 | CÓ (`survival.py`) |

Tổng tối đa 185. Với riêng các sự kiện đã có (1, 3, 5, 8, 9, 10) tổng là 25+16+20+20+20+15 = 116, đủ mở cả 4 rương (20, 50, 80, 100).
Thiết kế: `quests.py` giữ hằng `LIVE_SORTS = {78, 24, 35, 68, 76, 77}` và `diary.result` CHỈ liệt kê các dòng có `target_sort` thuộc tập này; thêm sort vào tập khi hook tương ứng được nối. Như vậy không có dòng nào mà nút "Tới" dẫn đến màn đóng.
Reset: mỗi ngày 00:00 giờ server (chữ trên popup: "mỗi ngày 00:00 tạo mới"). Dùng `shop.period(DAILY, now)` để ra khóa ngày.

### 4.2 `reward.diary_index`

Request: không tham số.
Response `data` (đã đối chiếu với `game_daily_task_pop.lua`):

```json
{
  "diary": {"result": {"1": 1, "3": 1, "5": 1, "8": 1, "9": 1, "10": 1}},
  "diary_done": {"1": 2, "3": 0, "5": 0, "8": 0, "9": 0, "10": 0},
  "diaryscore": 10,
  "diaryscore_done": [20],
  "diary_boxes": [
    {"slot": 1, "score": 20, "done": true},
    {"slot": 2, "score": 50, "done": false},
    {"slot": 3, "score": 80, "done": false},
    {"slot": 4, "score": 100, "done": false}
  ]
}
```

Bẫy hình dạng:
- `data.diary` KHÔNG guard (`diary.result or {}` chỉ guard `result`). `diary` phải là object.
- Mỗi khóa trong `diary.result` phải có giá trị truthy (client viết `local itemData = result[tempId]`; `0` trong Lua là truthy, `false`/null thì hiện "Dữ liệu và cấu hình bị lỗi"). Dùng `1`.
- `diary_done` nằm TRÊN CÙNG của `data`, không nằm trong `diary`. Khóa là id dòng dạng chuỗi. Dòng thiếu đọc như 0. Hoàn thành khi `diary_done[id] >= num` (client tự ẩn nút).
- `diaryscore` ở trên cùng (`or 0`). Nên chặn ở 100 (`min(100, tổng)`) vì thanh tiến độ và chữ "còn thiếu N điểm" không có ngưỡng cao hơn.
- `diaryscore_done`: mảng số nguyên các ngưỡng đã nhận (`game_util:valueInTeam(score, list)`). Khi gửi `diary_boxes` thì cờ `done` của nó thắng; cả hai phải nhất quán.
- `diary_boxes` là phần mở rộng của bản client Việt (hàm `shhhtB8Boxes`): hoặc đủ CẢ 4 slot (`slot` 1..4, `score`, `done` kiểu bool hoặc 1) hoặc client bỏ cả mảng và quay về 20/50/80/100 cố định. Slot i ứng với ngưỡng thứ i theo thứ tự tăng (20, 50, 80, 100 từ khóa của `diaryscore.config`). Luôn gửi đủ 4.
- Điểm tính ở server: `diaryscore = min(100, sum(min(diary_done[id], num) * reward_score))`. Sự kiện vượt `num` không cộng thêm.

### 4.3 `reward.diary_score_award`

Request (GET): `score` (chuỗi, ngưỡng) và, khi server gửi `diary_boxes`, thêm `slot` (chuỗi "1".."4"). Client gửi `{slot=, score=}`.
Kiểm: `score` là khóa của `diaryscore.config`; nếu có `slot` thì phải bằng chỉ số của ngưỡng; `diaryscore >= score`; chưa nhận hôm nay. Sai thì `fail("error_param", ...)` hoặc một lỗi chuỗi kèm `msg` tiếng Việt (client hiện popup và bỏ callback).
Response `data` (client đọc cả bốn khóa, `tData.reward` đi vào `game_util:rewardTipsByDataTable`):

```json
{
  "reward": {"food": 20000},
  "diaryscore": 20,
  "diaryscore_done": [20],
  "diary_boxes": [{"slot": 1, "score": 20, "done": true}, ...],
  "_client_cache_update": {}
}
```

`reward` dùng đúng dạng toast do `rewards.grant(...).reward` sinh ra. Nếu thưởng có vật phẩm thì kèm `granted.cache` vào `_client_cache_update`. Tiền tệ đổi qua `user_status` (app tự thêm).
Cờ đã nhận lưu bằng counter có chu kỳ ngày (mục 7).

## 5. Thành tựu: `reward.once_index` và `reward.once_award`

### 5.1 Config `reward_once.config` (107 dòng)

Khóa là id; dải id quyết định tab trong Phúc lợi: `<= 1000` online, `1001-1999` cấp độ, `2001-2999` thu hồi, `3001-3999` đấu trường (client dùng đúng các ngưỡng này, đừng đổi).
Trường: `target_sort`, `target_data` (mảng một số), `reward` (mảng `[type, id, count(, level)]`), `story`, `open_sort`/`open_data` (đều `1`/`1`: luôn mở).

| Dải | target_sort | Điều kiện | Số dòng |
|---|---|---|---|
| 1..26 | 79 | Tổng thời gian online (giây): 720, 1440, 1920, 3000, ... 108000, rồi 259200 cho id 17..26 | 26 |
| 1001..1031 | 1 | `level >= target_data[0]` (4, 7, ..., 100); 1032 có ngưỡng 200 và thưởng rỗng (dòng chúc mừng, không bao giờ đạt) | 32 |
| 2001..2020 | 2 | Thu hồi 100% thành phố `target_data[0]` (103, 107, ... 179: "x-4" của chương); 2021 là dòng chúc mừng ngưỡng 200 (target_sort 1) | 21 |
| 3001..3027 | 69 | Hạng đấu trường tốt nhất `<= target_data[0]` (1000 xuống 1); 3028 là dòng chúc mừng | 28 |

Bẫy: `refreshCurData` và `createAwardUI` lặp qua MỌI dòng của config và đọc `self.result[tostring(cid)][3]` KHÔNG guard.
Do đó `once.result` phải chứa đủ 107 khóa, kể cả 26 dòng online và 28 dòng đấu trường chưa dùng (cho trạng thái 0), nếu không client lỗi nil khi mở Phúc lợi.

### 5.2 Response

`reward.once_index` request: không tham số. Response `data`:

```json
{"once": {"result": {"1": [120, 720, 0], "1001": [5, 4, 1], "2001": [40, 100, 0], "3001": [0, 1000, 0]}}}
```

Mỗi phần tử là mảng 3: `[giá trị hiện tại, ngưỡng, trạng thái]`. Trạng thái `0` chưa đạt, `1` có thể nhận, `2` đã nhận.
- online: `[giây đã online, ngưỡng, trạng thái]`. Chỉ phần tử đầu tiên chưa nhận mới hiện nút (và đếm ngược `ngưỡng - giá trị`); các phần tử sau không có nút.
- cấp độ: `[level, ngưỡng, trạng thái]`.
- thu hồi: `[phần trăm thu hồi (0..100), 100, trạng thái]`.
- đấu trường: `[hạng tốt nhất, ngưỡng, trạng thái]`; chưa có đấu trường nên `[0, ngưỡng, 0]`.
Client cũng đọc `item[1]`, `item[2]` chỉ ở dòng online; các dòng khác chỉ dùng `item[3]`.

`reward.once_award`: request `award_id` (id dòng, số nguyên dạng chuỗi). Điều kiện: dòng tồn tại, trạng thái hiện tại là `1`. Response `data`:

```json
{"reward": {"food": 5000}, "once": {"result": {...đủ 107 khóa...}}, "_client_cache_update": {...}}
```

Client gán lại `self.result = data.once.result` rồi vẽ lại, nên phải gửi lại CẢ bản đồ (không guard `data.once.result`).
Nhận rồi thì trạng thái `2`. Nhận lần nữa trả lỗi chuỗi kèm `msg`.

### 5.3 Quy tắc từng dải

- Cấp độ: suy ra từ `players.level`, không cần bộ đếm. Nhận = đánh dấu đã nhận (lifetime counter `once:<id>` = 1).
- Thu hồi (2001-2020): suy ra từ `cleared_buildings`; thành phố đó đã thu hồi 100% tức là mọi công trình của `campaign._city_plan(city).buildings` nằm trong tập đã clear. Dùng `campaign._regain(plan.buildings, cleared)` (trả phần trăm).
- Online: cần bộ đếm giây online. Đề xuất: lifetime counter `online:seconds` cộng `min(now - last_seen, 120)` mỗi lần có request phiên hợp lệ (hook trong `app._dispatch` sau khi xác thực phiên), cùng counter `online:last`. Các id 17..26 cùng ngưỡng 259200 giây (72 giờ) nên sẽ cùng chín một lúc; đây là điều chưa rõ trong bản gốc (có thể bộ đếm reset sau mỗi lần nhận). Quyết định cần chủ dự án: giữ cộng dồn trọn đời (đơn giản) hoặc đặt lại sau mỗi lần nhận. Trong lúc chưa quyết, đóng view 8 và vẫn trả 26 dòng online với trạng thái `0`.
- Đấu trường: để `[0, ngưỡng, 0]` và giữ view 5 đóng cho đến khi có đấu trường.
- Phần thưởng kiểu 117 (`[117, cardId, số lượng, cấp]`, dòng 1004 và 1007) KHÔNG được `rewards.Loot.add` hỗ trợ. Cần thêm: tạo thẻ rồi `store.update_card(uid, id, lv=cấp, exp=0, step=0)`. Và `audit_scope.reachable_cards` chỉ xét `kind == CARD (5)`; thêm 117 để kiểm tra tướng trong phạm vi.
- Mọi kiểu thưởng còn lại trong `reward_once`, `diaryscore` (1, 2, 4, 5, 6, 7, 9, 10, 14, 15, 16, 17, 19, 27, 100) đã có trong `CURRENCY_BY_TYPE`/`Loot.add`. Đã kiểm tra: mọi id thẻ, trang bị (kiểu 7) và vật phẩm (kiểu 6) trong `reward_once` đều tồn tại trong `character_detail`, `equip`, `item`; mọi id thẻ kiểu 5 là `<= 38700`.

## 6. Treo thưởng (bản đồ nhỏ): `reward.index` và `reward.wanted_award`

`game_ui/game_offer.lua` được mở từ nút `m_rate_btn` trong mọi thành phố thường (trừ 100 và 101) và từ `game_normal_tips_pop`.

`reward.index` request: không tham số. Response `data`:

```json
{"wanted_data": {"result": {"1021": [0, 100, 0], "1042": [0, 2, 0]}}}
```

- `wanted_data.result` KHÔNG guard (`init` đọc `t_params.gameData.wanted_data.result`).
- Mỗi giá trị là `[hiện tại, cần, đã đạt]`. Ý nghĩa client dùng: `v[2] == 0` hoặc khóa vắng mặt nghĩa là ĐÃ NHẬN (hiện "Đã nhận"); `v[2] > 0` đang tiến hành, thanh `v[1]/v[2]`; `v[3] == 1` có thể nhận (nút "Nhận"); ngược lại nút "Khiêu chiến".
- Hệ quả bẫy lớn: khóa vắng mặt = đã nhận. Nên phải gửi MỌI id treo thưởng chưa nhận (570 id, gồm cả chưa đạt), chỉ bỏ id đã nhận.
- Dữ liệu danh sách theo thành phố nằm ở `map_main_story.<id>.wanted`; client hiện chỉ khi `level >= open_level` của thành phố.
- Chuỗi mở popup nhiệm vụ ngày cũng gọi `reward.index` nhưng bỏ qua nội dung; response trên vẫn dùng chung.

`wanted.config` (570 id): `target_sort` 100 (118 dòng: thu hồi 100% thành phố `target_data[0]`, `target_data1 = [100]`), 103 (226 dòng: đánh trận cuối của công trình `target_data[0]` thắng với HP còn lại lớn hơn `target_data1[0]` = 80 phần trăm, càn quét không tính) và 106 (226 dòng: thắng công trình `target_data[0]` trong không quá `target_data1[0]` = 2 hiệp). Thưởng kiểu 15, 10, 1, 4, 6, 7.
- Sort 100: giá trị = `min(100, phần trăm thu hồi)`, cần = 100.
- Sort 103 và 106: cần ghi lại kết quả trận cuối. Hiện `campaign.run_battle` không trả số hiệp và HP còn lại; cần cho `battle.Battle` công bố `round` và tổng HP còn lại tỷ lệ (nó đã giữ `round`, `MAX_ROUNDS`), rồi `campaign.recapture` ghi lifetime counter `wanted:<id>` = 1 khi đạt. Hiển thị: `[0, cần, 0]` khi chưa đạt, `[cần, cần, 1]` khi đạt (client không cần giá trị trung gian).
- `reward.wanted_award`: request `award_id`. Điều kiện: id có trong config, đã đạt, chưa nhận. Response: `{"reward": {...}, "wanted": {"result": {...}}, "_client_cache_update": {...}}`. Client lấy `temp.wanted.result` (KHÔNG guard) rồi vẽ lại.
- `private_city.open` có thể trả `wanted: 1` để hiện hiệu ứng nhắc trên nút (client chỉ đọc `data.wanted or 0`); không bắt buộc.

Phân giai đoạn khuyến nghị: bước 1 (bắt buộc cùng `reward.index`): sort 100 thật, 103/106 chưa đạt được (luôn `[0, cần, 0]`, nút "Khiêu chiến" dẫn vào công trình, không lỗi). Bước 2: nối thống kê trận.

## 7. Thiết kế bộ đếm tối thiểu (không cần migration)

Bảng `counters(player_id, name, period, value)` có khóa `(player_id, name)`; `counter()` trả 0 khi `period` khác, `set_counter()` ghi đè cả `period`. Đây chính là bộ đếm theo ngày: lưu `period = ngày`, sang ngày thì tự về 0.
Quy ước tên (mọi tên đều dưới `quest:` hoặc `once:` để không đụng `gacha:*`, `shop:*`, `sweep:*`):

| Tên | Chu kỳ | Ý nghĩa |
|---|---|---|
| `quest:<target_sort>` | ngày | số lần sự kiện hôm nay (dùng cho `diary_done`) |
| `diary_box:<score>` | ngày | 1 nếu rương ngưỡng đó đã nhận hôm nay |
| `once:<id>` | "" | 1 nếu thành tựu đã nhận |
| `online:seconds`, `online:last` | "" | giây online cộng dồn và thời điểm request cuối |
| `wanted:<id>` | "" | 1 nếu treo thưởng đã đạt |
| `wanted_claimed:<id>` | "" | 1 nếu treo thưởng đã nhận |

Không cần bảng mới: mọi thứ khác (cấp độ, thu hồi) suy ra từ `players` và `cleared_buildings`. Nếu sau này cần lịch sử hoặc nhiều nhiệm vụ song song, thêm migration NỐI ĐUÔI (không sửa migration đã áp dụng), ví dụ `_QUESTS` thêm vào cuối `MIGRATIONS` (hiện kết thúc ở `_CARD_BREAK`).
Hàm dùng chung đề xuất (trong `quests.py`): `record(svc, uid, sort, now, amount=1)` đọc `counter` rồi `set_counter(..., value + amount, period)`; mọi lần gọi nằm trong transaction của request nên an toàn.

## 8. Điểm móc (hook) cần cộng bộ đếm

| Sự kiện | Hàm | Điều kiện đếm |
|---|---|---|
| sort 78 thám hiểm | `campaign.recapture`, trong nhánh `if won:` (ngay sau `_victory`) | mỗi trận thắng, kể cả bước giữa của công trình nhiều bước. `sweep.auto_recapture`, `elite.*`, `active.*` KHÔNG đếm (đúng chữ "càn quét không tính"). Quyết định cần xác nhận: đếm trận thắng hay mọi trận; mặc định đếm trận thắng. |
| sort 24 nâng kỹ năng | `cards.skill_levelup`, sau khi `set_card_skill` | mỗi request thành công |
| sort 35 cường hóa trang bị | `equipment_actions.factory_equip_levelup` (sau `set_equipment_level`) và `all_equip_levelup_auto` | factory: 1 mỗi request thành công; auto: số món được nâng |
| sort 68 tài nguyên | `active._start_or_continue` khi bắt đầu lượt (step 0) và `active._sweep` thành công, chương `1` | mỗi lượt tham gia |
| sort 76 ải kinh nghiệm | như trên, chương `80` | mỗi lượt tham gia |
| sort 77 sinh tồn | `survival.forever_fight` (sau khi xác thực, thắng hay thua) và `survival.auto_forever_fight` | mỗi lần gọi thành công |
| online | `app._dispatch`, sau `_session_player` hợp lệ | cộng `min(now - last, 120)` giây |
| wanted 103/106 | `campaign.recapture` nhánh thắng, bước cuối | cần thống kê trận (mục 6) |
| sort 28, 27, 38, 74 (chưa có nguồn) | sau này: `school.*`, `cards` cải tạo, `arena.*`, `world_boss.*` | thêm vào `LIVE_SORTS` khi nối |

Thành tựu cấp độ và thu hồi và treo thưởng sort 100 không cần hook (suy ra).

## 9. Chấm đỏ (`alerts`) trong `user.main_page`

Hiện `handlers.user_main_page` trả `"alerts": {"is_double": False}`. Client chỉ cập nhật `m_alertsData` khi nhận `user.main_page`, nên chấm đỏ mới chỉ làm mới lần vào lại màn chính.
Thêm vào `alerts`:
- `diary`: số nguyên, số rương điểm hoạt động có thể nhận (điểm đủ, chưa nhận). LUÔN gửi (kể cả 0) để nút Nhiệm vụ không bị ẩn.
- `reward`: bool; gửi `false`. (Đặt `true` sẽ ép nút 35 đi qua `reward.index` rồi lại sang popup nhiệm vụ ngày: vô nghĩa. Nếu muốn nhắc treo thưởng thì dùng `wanted: 1` trong `private_city.open`.)
- `once`: bool, true nếu có thành tựu ở trạng thái 1 (chỉ hiện khi view 8 mở).
Không gửi `daily`, `month`, `active`, `opening`, `has_version_reward` (thuộc module khác).

## 10. Kiểm thử đề xuất

- `tests/test_quests.py` (nối kiểu test hiện có): `diary_index` ngày mới đủ khóa; hook cộng đúng và không đếm sweep; sang ngày về 0; `diary_score_award` từ chối khi chưa đủ điểm, nhận một lần, trả `reward` và `diary_boxes` nhất quán; `once_index` có đủ 107 khóa; `once_award` cấp độ/thu hồi/online; thưởng 117 tạo thẻ cấp 8; `reward.index` có `wanted_data.result` và id đã nhận vắng mặt.
- Test phạm vi: `closed_views()` không chứa 3, 4, 8 sau khi mở và chứa 184, 5, 9, 49, 126, 151.
- Emulator: tài khoản `testplayer1` lên cấp 3, bấm nút Nhiệm vụ (cần nút hiện), đánh một công trình rồi vào lại, nhận rương 20; mở Phúc lợi (chỉ còn tab Cấp độ và Thu hồi, cộng Online nếu mở view 8), nhận thành tựu cấp 4; vào bản đồ nhỏ của thành phố thường, bấm nút treo thưởng. Ghi `server/data/requests.jsonl` và logcat không có `attempt to`.

## 11. Các bẫy hình dạng cần nhớ

- `reward.index` phải thành công dù nội dung bị bỏ qua, nếu không nút Nhiệm vụ/"Nhận quà hằng ngày" không mở được popup.
- `once.result` phải đủ 107 khóa, mỗi khóa `[giá trị, ngưỡng, trạng thái]`; thiếu một khóa là lỗi nil khi mở Phúc lợi.
- `once_award` phải gửi lại cả `once.result`, và `reward` ở dạng toast.
- `diary.result`, `diary_done`, `diaryscore` ở các tầng khác nhau: `diary_done` ngang hàng với `diary`, không nằm trong nó.
- `diary_boxes` phải đủ 4 slot, nếu không client âm thầm quay về 20/50/80/100.
- Khóa treo thưởng vắng mặt nghĩa là ĐÃ NHẬN.
- `alerts` phải có `diary` hoặc `reward`, nếu không nút Nhiệm vụ bị ẩn từ lần đăng nhập thứ hai trong ngày.
- View 184 phải được thêm và đóng trước khi mở view 3, nếu không tab thẻ quý xuất hiện và gọi API chưa có.
- Thưởng kiểu 117 chưa được `Loot.add` hỗ trợ.
- Chấm đỏ chỉ làm mới khi gọi `user.main_page`.
