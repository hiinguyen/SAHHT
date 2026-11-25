# Giai đoạn 2: spec phần còn lại

Ngày: 2026-11-25.
Trạng thái: bản nháp để duyệt, chưa có dòng code nào.
Liên quan: `2026-11-24-phase-2-equipment.md` (spec gốc), `2026-11-24-phase-2-progress.md` (tiến độ), `../plans/2026-11-25-phase-2-remaining-plan.md` (kế hoạch thực hiện).

## 1. Hiện trạng

Đã xong và đã kiểm chứng trên emulator (đợt 1-3):

- Bảng `equipment` (`id, c_id, lv, st_lv`) và `equipment_positions`; `cards.open` gửi `equip`, `equip_pos`, `equip_pos_1..3`, `bonus_equip_pos`.
- Gacha trang bị, cường hóa, bán, tiến hóa (`equip.evolution`), tinh luyện (`equip.st_levelup`).
- Chỉ số cộng vào chiến lực và trận: chỉ `value1/value2 + level_add * (lv - 1)`.

Chưa làm, theo thứ tự đề xuất ở mục 4:

| Đợt | Tính năng | URL | View | Cấp mở trong client |
|---|---|---|---|---|
| A | Dọn nợ: bộ trang bị, sức chứa, tutorial đội 2 | `cards.*`, `equip.*` | - | - |
| B | Tách | `equip.exchange` | 25 | 26 |
| C | Phụ ma | `equip.enchant`, `save_init_enchant`, `remove_enchant`, `auto_enchant` | 131 | 40-45 |
| D | Tẩy luyện | `equip.equip_refine`, `equip.auto_refine` | 148 | 48 |
| E | Rèn | `equip.equip_forge_index/level/refresh` | 167 | 60 |
| F | Vận mệnh | `equip.fate_equip_*`, gắn và gỡ | 182, 193 | không giới hạn |
| G | Đá quý | `gem.*`, `gem_fate.*` | 129, 130, 181, 196, 203, 226 | chưa đọc |
| H | Thống soái | `commander.*` | 16 | chưa đọc |
| - | Đúc | `equip.equip_building*` | 208 | 110 (đề xuất hoãn) |
| - | Xưởng | `factory.*` | 208 | đề xuất bỏ |

## 2. Nguyên tắc chung cho mọi đợt

- Mỗi đợt theo đúng quy trình của dự án: đọc Lua, viết test thất bại trước, cài đặt, chạy cả bộ test, kiểm chứng trên emulator, rồi ghi tiến độ ra `2026-11-24-phase-2-progress.md`.
- Mở view chỉ sau khi handler của nó chạy được trên emulator; view đóng thì client ẩn nút (`inreview`).
- Trường mới của trang bị đi qua `equipment.document()` và `_client_cache_update.equip._equip.update`; `remove` luôn có mặt.
- Mọi thay đổi nhiều bước nằm trong một transaction; thiếu tài nguyên thì `Refused("error_not_enough")` để rollback.
- Xúc xắc đi qua `random.randrange` ở cấp module để test cố định bằng `mock.patch`.
- Client đọc nhiều khóa không kiểm nil khi vẽ icon trang bị; mỗi khi thêm màn mới phải chạy emulator và đọc `LUA ERROR` để bắt khóa còn thiếu (bài học từ `equip_pos_1..3` và `bonus_equip_pos`).
- Nút của client hiện theo cấp người chơi; để thử phải đặt `players.level` đủ lớn trong `sahht.db`, và nhớ emulator có thể đang đăng nhập tài khoản khác `testplayer1` (tên hiển thị cho biết).

### 2.1 Lưu trữ thuộc tính mở rộng của trang bị

Nhiều tính năng cần thêm khóa vào document trang bị (`is_enchant`, `atts`, `equip_refine`, `equip_forge_level`, `equip_forge`, `bind_card`, `bind_data`, `gem_fate`, và các bản chờ lưu).
Đề xuất một migration duy nhất thêm cột `extra TEXT NOT NULL DEFAULT '{}'` (JSON) vào `equipment`.
`st_lv` giữ nguyên là cột riêng.
Lý do: các khóa này luôn đọc và ghi cùng nhau theo từng trang bị, không cần truy vấn theo khóa, và thêm tính năng không cần thêm migration mới.
Store chỉ có hai hàm: đọc và ghi `extra` của một trang bị; luật nằm ở module tính năng.
`equipment.document()` hợp nhất `extra` vào document, trừ các khóa chờ lưu (đặt tên `*_pending`) không được gửi cho client.

### 2.2 Chỉ số trang bị trong chiến lực và trận

`equipment.bonus()` hiện chỉ cộng `value1/value2` theo cấp.
Mỗi đợt dưới đây ghi rõ phần nào cộng được vào `hp, patk, matk, def, speed`.
Các chỉ số phụ (bạo kích, chính xác, giảm thương, né tránh, nguyên tố) engine trận chưa có; các đợt vẫn lưu và gửi chúng cho client nhưng không đưa vào trận (ghi ở "Giới hạn" của đợt đó).

## 3. Spec từng đợt

### A. Dọn nợ của phase 2

A1. Bộ trang bị (suit).
Client tính bonus bộ từ `equip.config.suit` và các bảng `equip_set_*`; cần đọc đúng công thức trong `game_util.lua` rồi cộng vào `bonus()`.
Chưa đọc xong phần này, nên đợt A bắt đầu bằng một bước đọc, chưa phải cài đặt.

A2. Sức chứa.
`user_status.equip_max` đang cố định 100.
Cần từ chối gacha, phần thưởng trang bị và các việc tạo trang bị khác khi túi đầy; client dùng `equip_max - số trang bị` (`game_data.lua:4056`).
Quyết định cần chốt: giá trị `equip_max` theo VIP hay cố định.

A3. Khóa trang bị.
Không tìm thấy URL khóa trang bị trong `game_url_config.lua` (grep `equip_lock`, `lock_equip` không ra).
Kết luận tạm: client này không có khóa trang bị; bỏ khỏi phạm vi.

A4. Tutorial đội 2.
`guide.config["2"]` có 13 bước (id 28-40), bước 29 mở nút 602 và 601 (cường hóa và xem trang bị).
Các bước đầu có vẻ chỉ cần cường hóa, phần đã có; cần chạy emulator từ tài khoản mới để xác nhận và bỏ ghi chú "phải bỏ qua".
Tiêu chí xong: tài khoản mới đi hết 13 bước không có lỗi Lua và `guide["2"]` tiến đến bước cuối.

### B. Tách (`equip.exchange`, view 25)

Client: `game_ui/ui_equip_split.lua`.
Yêu cầu: `equip_id` lặp lại nhiều lần trong chuỗi truy vấn thô (`equip_id=1&equip_id=2`), tối đa khoảng 11 món (client chặn); server đọc qua `Request.lists`, không qua `params`.
Phản hồi đọc không kiểm nil: `data.reward`; client hiển thị bằng `rewardTipsByJsonData`, sau đó `refreshUi` từ cache, nên phải gửi `_client_cache_update.equip._equip.remove` và `user_status`.
Từ chối: món đang mặc, món có `bind_card` khác rỗng, món không thuộc người chơi, id trùng.
Phần thưởng cho mỗi món:

- `metal`: ngẫu nhiên đều trong `equip_exchange[exchange_id].metal` (khoảng `[min, max, 100]`) cộng hoàn phí cường hóa `sum(i = 1..lv-1) ceil(equip_strongthen[i].quality<q> * 0.01 * equip_strongthen[i].metal)` cộng `sum(i = 1..st_lv) equip_st[i].metal`.
- `metalcore`: ngẫu nhiên đều trong `equip_exchange[exchange_id].metalcore` cộng `sum(i = 1..st_lv) equip_st[i].metalcore`.
- Nhãn thứ ba của client ("đá") tính từ `equip_forge_level`; chỉ làm khi đợt E xong.

`exchange_id` lấy từ `equip.config[c_id].exchange_id`.
Công thức phía client dùng ngẫu nhiên để hiển thị ước lượng; server tung riêng và trả số thật trong `data.reward`.
Điều kiện mở: view 25 chuyển từ `open: false` thành `module: "equip"`; client chỉ mở nút ở cấp 26.
Giới hạn: màn có thêm tab tách thẻ (view 32) và tách đá quý (view 130), vẫn đóng.

### C. Phụ ma (`equip.enchant` và các lệnh liên quan, view 131)

Client: `game_ui/equip_enchanting.lua`.
Tiền tệ: `user_status.enchant` (mảnh Ma Quang); mỗi lần tốn `enchant.config[quality].piece` (80 cho phẩm chất 1-12).
Trạng thái trang bị: `is_enchant` (bool) và `atts` (map khóa `fire`, `fire_dfs`, `water`, `water_dfs`, `wind`, `wind_dfs`, `earth`, `earth_dfs` sang số); lần tung chờ lưu nằm trong `extra.enchant_pending`.
Luồng:

1. Phụ ma lần đầu (`is_enchant` sai): `equip.enchant(equip_id)` tung giá trị mới, lưu vào `enchant_pending`, trả `data.enchant_attrs` (đọc không kiểm nil).
2. `equip.save_init_enchant(equip_id, is_save)`: `is_save=1` ghi `is_enchant=true` và `atts` từ lần tung chờ, trả `data.cur_atts`; `is_save=0` bỏ lần tung.
3. Phụ ma lần sau (`is_enchant` đúng): `equip.enchant` cộng thêm một mức vào `atts`, chặn ở `atk_max` hoặc `def_max` của phẩm chất, trả `data.cur_atts` (tổng) và `data.enchant_attrs` (mức tăng), cả hai đọc không kiểm nil.
4. `equip.remove_enchant(equip_id)`: xóa `is_enchant` và `atts`, hoàn mảnh, trả `data.enchant` là số nguyên (đọc không kiểm nil).
5. `equip.auto_enchant(equip_id, sort)`: `sort=-1` là truy vấn, trả `need_times`, `can_times`, `enchant_cost`, `need_enchant`, `cur_atts` (đọc không kiểm nil); `sort` 0, 1, 2 thực hiện (2 là tối đa, 1 là theo số mảnh đang có, 0 là đủ mảnh).

Luật chọn khóa nguyên tố: trang bị `sort` 1-2 dùng khóa tấn công, `sort` 3-4 dùng khóa phòng thủ; một hoặc hai khóa mỗi trang bị; dùng `atk_rate`/`def_rate` làm biên tung `[1, max]`.
Chưa rõ (cần luật tự đặt): phân phối tung chỉ có biên, nên chọn đều trong `[min, max]`; `need_enchant` có bằng `piece` không; công thức xu cho phần mảnh còn thiếu (`floor((need_times - can_times) * need_enchant * cost)`, `cost = fast_material_cost["5"].cost`), tạm trừ vào `coin`.
Giới hạn: nguyên tố chưa vào trận; client mở nút ở cấp 40-45.

### D. Tẩy luyện (`equip.equip_refine`, `equip.auto_refine`, view 148)

Client: `game_ui/game_equip_succinct.lua`.
Danh sách chỉ gồm trang bị có `equip.config.refine_id > 0`.
Tiền tệ: `refine_stone` (loại 23), `coin` (loại 9), `metal` (loại 2), theo `equip_refine[refine_id].refine_{min,mid,max}_cost`.
Trạng thái trang bị: `equip_refine = {hp, patk, matk, def, speed, extra_break_1, extra_break_2}`.
Quan trọng: client đọc `equip_refine.hp` không kiểm nil (`game_util.lua:3556`), nên khi đã có `equip_refine` thì `hp` luôn phải có.
Lệnh tung (`equip.equip_refine`): tham số `equip_id`, `sort` (số lần 1, 5, 10), `type` (1 thấp, 2 vừa, 3 cao), `is_save`.
Phản hồi `data.equip_refine` phải có hai khóa thuộc tính của trang bị (`ability1`, `ability2` trong `equip.config`), giá trị là mức thay đổi của lần tung; thiếu khóa thì `:toInt()` lỗi.
`is_save=0` xem trước, không lưu; `is_save=1` lưu. Cần chốt trừ tài nguyên lúc tung hay lúc lưu; tạm trừ lúc tung.
Luật tung: chọn một trong ba khoảng theo trọng số của `refine_{type}_{1|2}`, rồi tung đều trong khoảng đó; giá trị tích lũy bị chặn bởi `refine_control_1/2`.
Cờ `extra_break_1/2` bật khi vượt ngưỡng `extra_break_1/2` của config.
`equip.auto_refine`: truy vấn (`is_buy=0`) trả `can_refine_info.need_times`, `max_refine_info.need_times`, `max_refine_info.refine_stone_need` (đọc không kiểm nil) cùng các khóa tùy chọn `coin_need`, `metal_need`, `metal_cost`, `refine_stone_cost`; thực hiện (`is_buy=1`, `handle_sort` 1 hoặc 2) chỉ cần `data`.
Vào chiến lực và trận: có, `equip_refine[patk|matk|def|speed|hp]` cộng vào đúng thuộc tính (client cộng ở `game_util.lua:6090-6102` và các chỗ tương tự); cờ bạo kích bổ sung chưa tính.
Chưa rõ: chỗ client chặn giá trị theo `refine_control_*`; ý nghĩa chính xác của `fast_refine_*`.

### E. Rèn (`equip.equip_forge_*`, view 167)

Client: `game_ui/game_equip_forge.lua`, popup `game_pop/game_equip_forge_pop.lua`.
Tiền tệ: `small_forge_stone`, `middle_forge_stone`, `high_forge_stone`, `metal`.
Trạng thái: `equip_forge_level = {lv, exp}` (tối đa cấp 10), `equip_forge` (map id thuộc tính sang `{tên: giá trị}`), `equip_forge_temp` (kết quả làm mới chờ lưu).
Lệnh:

- `equip_forge_index(equip_id)`: trả `data` là cả document trang bị; popup đọc `data.id`, `data.equip_forge` (qua `next`, không kiểm nil) và `data.equip_forge_level.lv`.
- `equip_forge_level(equip_id, forge_stone)`: `forge_stone` dạng `"nhỏ_vừa_lớn"`, ví dụ `"3_0_1"`; điểm kinh nghiệm mỗi đá là 10, 100, 500; cấp `L+1` cần `equip_set_level[L+1].need`, phần dư chuyển sang cấp sau; chỉ tốn đá. Phản hồi chỉ cần cache (client đọc lại trang bị từ cache).
- `equip_forge_refresh(equip_id, sort, is_save)`: `sort` 0, 1, 2 chọn loại đá; giá `equip_set_cost[sort+1].cost` (10 đá cộng 2000, 5000, 10000 kim khí). `is_save=0` trả `equip_forge_temp` trong `_client_cache_update`; `is_save=1` ghi `equip_forge`.

Sinh thuộc tính: mỗi trang bị có 3 thuộc tính khác nhau, chọn từ `equip_set_random` lọc theo `equip_sort` chứa `sort` của trang bị, theo trọng số của phẩm chất (60, 30, 7, 3).
Giá trị ở cấp `L`: `sort` 1-5 là `floor(ability + add<quality> * rate_num[sort])` với `add` từ `equip_set_level[L]`; `sort` từ 6 trở lên dùng bảng hệ số của `equip_set_rate` (cần đọc thêm).
Thuộc tính cộng được vào trận: `hp, patk, matk, def, speed`; còn `crit, hr, subhurt, dr, probability` chỉ lưu.
Chưa rõ: khi nào tính lại giá trị lúc lên cấp rèn; trừ tiền ở `is_save=0` hay `1`.
Client mở nút ở cấp 60.

### F. Vận mệnh (`equip.fate_equip_*`, gắn và gỡ, view 182/193)

Client: `game_pop/game_equip_fateUpRefresh_pop.lua`, `game_equip_fateUpBilling_pop.lua`, `game_equip_info_pop.lua`.
Trạng thái: `bind_card` (id thẻ hoặc chuỗi rỗng), `bind_data = {id thuộc tính: phần trăm}` (client đọc không kiểm nil nên phải có đủ hai khóa với mọi trang bị đã gắn), `gem_fate = [0,0,0,0]`, `bind_temp`.
Lệnh:

- Gắn: tham số `equip_id`, `card_id`; tốn `equip_fate["1"].cost` (10 Đá Vận Mệnh). Tên URL chính xác cần xác nhận lại trong `game_url_config.lua`.
- Gỡ: tham số `equip_id`; `equip_unbind.config` cho vật phẩm trả lại (chưa rõ ánh xạ phẩm chất); client cảnh báo không hoàn nguyên liệu.
- Làm mới (`fate_equip_levelup`) và `auto_fate_equip_levelup`: tham số `equip_id`, `sort` 1-3 (loại đá `min/mid/max_fate_stone`); mỗi lần tốn tổng `refresh[sort-1]` của hai thuộc tính (thường 10 đá). Phản hồi phải có `_client_cache_update.equip._equip.update[equip_id]` (có `bind_data`, `gem_fate`), `data.bind_data_temp` (map id thuộc tính sang mức đổi), `data.fate_range` (map id sang `[min, max]`), tùy chọn `data.leveup_times`.

Luật tung: lấy dòng `equip_fate` theo `equip_quality`; với mỗi thuộc tính chọn dòng đầu có `refresh_range >= giá trị hiện tại`; mức đổi tung theo trọng số `refresh_equip_{min,mid,max}_fate{1,2}` rồi đều trong `[lo, hi]`.
Chưa rõ: dòng nào áp dụng khi giá trị vượt mọi `refresh_range`; `auto_fate_equip_levelup` lặp đến khi nào.
Vào trận: `bind_data` gắn với thẻ; việc đầu tiên của đợt F là đọc client cộng nó ra sao trước khi quyết định có vào chiến lực hay không.

### G. Đá quý (`gem.*`, `gem_fate.*`)

Đã có config: `gem.config` (120 dòng: `ability`, `value`, `quality`, `evo_max`, `need_gem`, `need_item`, `iron`), `gem_evolution.config` (10 cấp: `metal`, `rate`, `false_back`, `gem_material`), các bảng `equip_gem_fate*`.
URL: `gem.synthesis` (`gem_id`, `gem_num`), `gem.upgrade` (`gem_id`, nhiều `element_id`), `gem.resolve` (`gems=cid_số lượng`, lặp lại), `gem.evolution` (`gem_id`, `super_evo`); `gem_fate.synthesis_gem_fate`, `using_gem_fate` (`major`, `gem_fates`), `remove_gem_fate`, `empowering`, `printing`, `transfer`.
Cần dựng trước: kho đá (khóa `gem` của `cards.open`) và vị trí gắn (`gem_pos`); hình dạng hai khóa này chưa xác nhận, đọc `game_data.lua` quanh dòng 3800-3835 và `setGemDataByJsonData`.
Đợt này lớn nhất, chia nhỏ: G1 (kho đá, gắn, tháo, tổng hợp), G2 (nâng cấp, tiến hóa, phân giải), G3 (đá vận mệnh).
Các view 129, 130, 181, 196, 203, 226 mở dần theo từng nhóm.
Chưa đọc đủ để viết luật chi tiết: bước đầu của G là nghiên cứu cấu trúc rồi viết spec riêng `phase-2-gems.md`.

### H. Thống soái (`commander.*`, view 16)

URL: `commander.index`, `synthesis` (`recipe`), `search`, `rob`, `quick_rob`, `protect`, `enemies`.
Config có sẵn: `commander_level`, `commander_recipe` (24 công thức ghép mảnh), `commander_type` (41 dòng: `add_patk`, `add_hp`, `add_firedfs`).
`rob`, `search`, `protect`, `enemies` là cướp mảnh giữa người chơi; máy chủ riêng chỉ có ít người thử, nên chỉ làm `index` và `synthesis`, còn `quick_rob` (cướp NPC) làm nếu cần.
`cards.open` còn cần `commander_attrs` và `commander_available_skill`; hình dạng chưa xác nhận.
Ưu tiên thấp nhất; viết spec riêng `phase-2-commander.md` sau khi đọc màn `game_ability_commander`.

### Đề xuất hoãn hoặc bỏ

- Đúc (`equip.equip_building*`, view 208): 5 config bắt buộc (`equip_building`, `building_suit`, `equip_building_quality`, `equip_building_old`, `equip_building_again`) không có trong APK; client gọi `game_data:getBuildingMetailListByTab` không tồn tại nên bước chọn nguyên liệu bị lỗi; cấp mở 110, cao hơn phạm vi 2018. Hoãn.
- Xưởng (`factory.factory_all`, `equip_make`, `quick_make`, `cancel_make`, `completion_equip`): không Lua nào gọi (chỉ `factory.equip_levelup` đã làm). Bỏ khỏi phase 2.

## 4. Thứ tự đề xuất và lý do

1. A (dọn nợ): nhỏ, gỡ rủi ro cho mọi đợt sau (tutorial, sức chứa, bộ trang bị).
2. B (tách): đơn giản, cho người chơi cách đổi trang bị thừa lấy kim khí.
3. D (tẩy luyện) rồi C (phụ ma): D cộng được vào chiến lực nên có giá trị thấy được; C chủ yếu là nguyên tố, chưa vào trận.
4. E (rèn), F (vận mệnh): cùng dùng `extra`, cấp mở cao (60 và không giới hạn).
5. G (đá quý): lớn, cần nghiên cứu thêm.
6. H (thống soái): thấp nhất.

## 5. Câu hỏi cần chủ dự án quyết

1. Có chấp nhận lưu thuộc tính mở rộng trong một cột JSON `extra` (mục 2.1)?
2. Luật tung cho phụ ma, tẩy luyện, rèn, vận mệnh không có trong Lua: dùng "chọn theo trọng số của config, rồi đều trong khoảng" như đã mô tả?
3. `equip_max`: cố định 100 hay theo VIP?
4. Đúc và xưởng: đồng ý hoãn và bỏ?
5. Đợt G và H: làm trong phase 2 hay chuyển sang phase 3 trong roadmap?

### 5.1 Đã chốt (2026-11-25, chủ dự án)

1. Đồng ý cột JSON `extra` (migration 5, `ALTER TABLE equipment ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'`).
   Store chỉ có `equipment_extra` và `set_equipment_extra`; luật nằm ở module tính năng.
   `equipment.document()` hợp nhất `extra`, bỏ các khóa bắt đầu bằng `_` (sổ sách nội bộ) và kết thúc bằng `_pending` (bản chờ lưu).
   `equip_forge_temp` vẫn được gửi vì popup rèn đọc nó từ cache của lần làm mới.
2. Đồng ý luật tự đặt "chọn khoảng theo trọng số của config, rồi đều trong khoảng".
   Mọi chỗ tự đặt ghi ở mục 7.
3. `equip_max` cố định 100 (`equipment.EQUIP_MAX`), chặn mọi đường tạo trang bị ở `rewards.grant` với `error_equip_full`.
4. Đồng ý hoãn Đúc và bỏ phần còn lại của Xưởng.
5. Đợt A, Z, B, D, C, E, F làm trong phase 2; G và H chuyển sang phase 3.

## 6. Hiện trạng triển khai (2026-11-25)

Đã cài và có test cho A, Z, B, D, C, E, F; đã chạy emulator cho cả năm màn mới nên view 25, 131, 148, 167, 182, 193 đã mở.

| Đợt | Module | Endpoint | Test |
|---|---|---|---|
| A | `equipment.py`, `rewards.py`, `player.py` | suit trong `bonus()`, `equip_max` 100 | 5 |
| Z | `store.py`, `equipment.py` | migration 5, `equipment_extra`, `set_equipment_extra` | 1 |
| B | `equipment_split.py` | `equip.exchange` | 2 |
| D | `equipment_refine.py` | `equip.equip_refine`, `equip.auto_refine` | 6 |
| C | `equipment_enchant.py` | `equip.enchant`, `equip.save_init_enchant`, `equip.remove_enchant`, `equip.auto_enchant` | 6 |
| E | `equipment_forge.py` | `equip.equip_forge_index/level/refresh` | 5 |
| F | `equipment_fate.py`, `cards.open` `bind_equip` | `equip.fate_equip_bind/unbind/levelup`, `equip.auto_fate_equip_levelup` | 5 |

Kiểm chứng emulator (2026-11-25, `p0tester1` cấp 70): tách, tẩy luyện, phụ ma, rèn, vận mệnh đều chạy, không còn lỗi Lua.
Lần đầu mở popup rèn thiếu `equip_forge` (client đọc `next()` không kiểm nil); đã sửa để `equip_forge` (kể cả rỗng) luôn có từ cấp rèn 1.

Sửa so với bản nháp:

- Đợt C: khóa nguyên tố theo `sort` như mô tả, nhưng chốt số khóa là 1 cho `sort` 1-2 và 2 cho `sort` 3-4, vì client lấy `atk_max` khi `cur_atts` có một khóa và `def_max` khi có hai.
- Đợt D: mỗi lần gọi đều trừ tài nguyên, kể cả `is_save=0`; nút "Lưu" của client gọi lại với `is_save=1` nên tung lần mới rồi mới ghi.
  Không có bản chờ lưu cho tẩy luyện.
- Đợt D: `equip_refine` luôn có đủ `hp, patk, matk, def, speed` (giá trị 0 khi chưa tung) để client đọc `equip_refine.hp` không kiểm nil.
- Đợt D: `need_times` của `auto_refine` tính theo biên trên của khoảng (giả định lần nào cũng tối đa), `can_times` theo số lần trả được; `handle_sort=1` tung tới trần, `2` tung đúng số trả được, trừ tiền từng lần và dừng khi hết.
- Đợt E: giá trị rèn của `sort` 1-5 là `floor(ability + add<quality> * rate[sort])`, `sort` 6-10 là `ability + add<quality> * rate_quality` theo `equip_set_rate`; dùng `add1` vì phẩm chất của dòng `equip_set_random`.
- Đợt E: thuộc tính rèn được tính lại khi lên cấp rèn (cấu hình không nói lúc nào, xem mục 7).
- Đợt F: đội hình nhận `bind_equip` (sort -> id) trong `cards.open` và `_client_cache_update`; chiến lực nhân `bind_data` theo từng thuộc tính sau khi cộng đồ trang bị, đúng thứ tự `getCombatValue`.
- Đợt F: gỡ trả lại 10 `min_fate_stone` (giá gắn) và không trả đá nâng cấp, đúng cảnh báo của client.

## 7. Chỗ tự đặt (đổi ở một nơi)

- Phụ ma: 1 khóa cho `sort` 1-2 (`fire/water/wind/earth` chọn ngẫu nhiên), 2 khóa cho `sort` 3-4 (`*_dfs`); mỗi lần cộng đều `1..atk_rate[1]`/`1..def_rate[1]`, chặn ở `atk_max`/`def_max`.
- Phụ ma: gỡ hoàn toàn bộ mảnh đã tiêu cho trang bị đó (`extra._enchant_spent`), không hoàn theo giá trị.
- Phụ ma: `need_times = ceil((max - cur) / 60)` (client ước lượng bằng 60), `can_times = floor(mảnh / piece)`.
- Tẩy luyện: `need_times = max(ceil((trần - hiện tại) / biên trên của khoảng))`.
- Tẩy luyện: không bán đá thiếu bằng xu; `handle_sort=1` chỉ tung tới khi hết tài nguyên.
- Rèn: thuộc tính tính lại khi lên cấp; `need` lấy từ `equip_set_level[lv+1]`; dừng ở cấp 10, kinh nghiệm dư bỏ.
- Rèn: trừ đá và sắt lúc làm mới (`is_save=0`), lưu miễn phí.
- Vận mệnh: `bind_data` không xuống dưới 0; `auto` tung tối đa 100 lần mỗi lệnh; `leveup_times` đếm số lần một thuộc tính vượt `refresh_range` sang dòng kế.
- Vận mệnh: gỡ trả 10 `min_fate_stone`.

