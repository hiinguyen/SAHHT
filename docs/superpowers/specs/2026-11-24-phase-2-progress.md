# Tiến độ giai đoạn 2: trang bị

Cập nhật lần cuối: 2026-11-25.
Spec gốc: `2026-11-24-phase-2-equipment.md`.
Spec và plan phần còn lại (đợt A-H): `2026-11-25-phase-2-remaining-spec.md`, `../plans/2026-11-25-phase-2-remaining-plan.md`.

## Đợt 1: trang bị cơ bản

Xong (xem spec gốc).

## Đợt 2: tiến hóa trang bị (`equip.evolution`, view 23)

Trạng thái: XONG (2026-11-25).

### Phân tích (xong)

- Client: `game_ui/equip_evolution.lua`, URL `/api/?method=equip.evolution`, tham số `equip_id`.
  Tham số `is_buy=1` chỉ dùng khi view 170 mở (mua đủ nguyên liệu bằng xu); view 170 vẫn đóng nên server từ chối.
- Config: `equip.config[c_id].evolution` là c_id mới, `evolution_id` là khóa vào `equip_evolution.config`.
- `equip_evolution.config[evolution_id]` có `metal` và `equip_material_1..3`, mỗi cái là `[[loại, id, số lượng]]`.
  Loại 6 là vật phẩm trong túi, loại 7 là trang bị cùng `c_id`.
- Client đếm nguyên liệu loại 7 bằng `getEquipCountByCid`: cùng `c_id`, khác trang bị đang chọn, và không đang mặc.
  Server dùng đúng luật này.
- Sau khi tiến hóa client chỉ gọi `refreshUi` từ dữ liệu cache, nên phản hồi cần `_client_cache_update` (trang bị đổi, nguyên liệu bị xóa, vật phẩm đổi) và `user_status` (metal).

### Việc cần làm

- [x] Test thất bại trước (RED): 4 test trong `EquipmentTests`, config giả trong `tests/test_flow.py`
- [x] Handler `equip.evolution` trong `equipment_actions.py` (giữ id và cấp, đổi `c_id`)
- [x] Store: `set_equipment_config`
- [x] Mở view 23 trong `data/scope_2018.json`
- [x] Chạy cả bộ test: 171 test OK
- [x] Kiểm chứng trên emulator
- [x] Cập nhật spec gốc, CLAUDE.md và README

### Nhật ký

- Đã đọc Lua, config và code hiện có.
- Handler: nguyên liệu loại 7 lấy bản sao cấp thấp nhất trước (cùng `c_id`, không phải món đang tiến hóa, không đang mặc); loại 6 trừ từ túi; metal trừ qua `pay`.
  Mọi thứ nằm trong một transaction, thiếu bất cứ gì thì rollback và trả `error_not_enough`.
- Trang bị giữ nguyên id, cấp và vị trí đang mặc; chỉ `c_id` đổi.
- Cả bộ test xanh (171 test).
- Emulator (tài khoản `p0tester1`, nâng cấp 45 vì nút "Tiến hóa trang bị" của client mở ở cấp 45 theo `button_open.config`):
  - Màn `equip_evolution` lần đầu lỗi `game_data.lua:6479` (thiếu `equip_pos_1..3`), sau đó `game_data.lua:1685` (thiếu `bonus_equip_pos`).
    Cả hai đều do client đọc không kiểm nil khi vẽ icon trang bị; `cards.open` giờ gửi lưới rỗng cho chúng (có test).
  - Chọn súng 10101: hiện nguyên liệu 1/1 và 20/20, tiêu hao 1000, phẩm chất Lục sang Lam.
  - Bấm "Tiến hóa": súng thành 10102 (HP 192, công 128), kim khí 10000 sang 9000, vật phẩm 100001 về 0, bản sao nguyên liệu bị xóa, không có lỗi Lua; màn hình tự làm mới và hiện công thức bậc Tím.
- Giới hạn: bộ trang bị, tinh luyện, rèn, phụ ma vẫn chưa tính vào chiến lực; `is_buy` (view 170) trả `error_not_open`.
- Cả bộ test xanh (171 test), `tools.audit_scope` chạy được.

## Đợt 3: tinh luyện trang bị (`equip.st_levelup`, view 24)

Trạng thái: XONG (2026-11-25).

### Phân tích (xong)

- Client: `game_ui/game_equip_refining.lua` (nút `btnId 608`), URL `/api/?method=equip.st_levelup`, tham số `equip_id` (comment trong `game_url_config.lua` nhắc thêm `sort`, màn này không gửi).
- Phản hồi: `data.success` (`"true"` là thành công, khác là thất bại), rồi `refreshUi` đọc trang bị từ cache nên cần `_client_cache_update` (trường `st_lv`) và `user_status` (`metal`, `metalcore`).
- `equip_st.config` hàng `N` (1..10): `metal`, `metalcore`, `rate` (% thành công), `false_back`, và `patk/matk/def/speed = [loại, %]`.
  Giá và tỉ lệ lấy từ hàng cấp kế (`st_lv + 1`); khi thất bại, `st_lv` rơi về `false_back` của hàng cấp hiện tại (cấp 0 thì ở lại 0).
  Cấp 1-7 có `false_back` bằng chính cấp đó nên không tụt, cấp 8-10 tụt về 7.
- Cấp tối đa là 10; tiêu hao trừ cả khi thất bại.
- Phần thưởng tinh luyện là chỉ số phụ (bạo kích, chính xác, giảm thương, né tránh theo `sort` của trang bị), engine trận chưa có các chỉ số này nên chưa tính vào chiến lực.

### Việc cần làm

- [x] Test thất bại trước (RED): 3 test trong `EquipmentTests` (xúc xắc cố định bằng `mock.patch` `random.randrange`)
- [x] Store: `set_equipment_st_level`
- [x] Handler `equip.st_levelup`
- [x] Mở view 24 trong `data/scope_2018.json`
- [x] Chạy cả bộ test: 174 test OK
- [x] Kiểm chứng trên emulator (cả thành công và thất bại)
- [x] Cập nhật spec gốc, CLAUDE.md và README

### Nhật ký

- Đã đọc Lua và config.
- Handler `equip_st_levelup` (`equipment_actions.py`): trừ kim khí và `metalcore` của hàng cấp kế, tung `random.randrange(100) < rate`; thành công lên 1 cấp, thất bại về `false_back` của hàng cấp hiện tại; trả `data.success` là `"true"`/`"false"` cùng `_client_cache_update`.
  Cấp 10 trả `error_max_level`, thiếu tài nguyên thì rollback và trả `error_not_enough`.
- Nút "Tinh luyện" nằm trong popup "Trang bị" của màn chính (menu `backpack`), ẩn khi view 24 đóng.
- Emulator (`p0tester1`, trang bị 10102 đặt sẵn `st_lv = 7`):
  - Màn hiển thị "Thất bại giảm xuống đến: 7", tiêu hao 5000 / 90 (hàng 8): khớp cách hiểu `false_back` là cấp rơi về.
  - Lần 1 thành công: 7 → 8, kim khí 10000 → 5000, metalcore 1000 → 910, màn tự làm mới (8 sao, hàng kế 5000 / 100).
  - Lần 2 thất bại (tỉ lệ 20%): 8 → 7, mất 5000 kim khí và 100 metalcore, màn về 7 sao; không có lỗi Lua.
- Giới hạn: phần thưởng tinh luyện (bạo kích, chính xác, giảm thương, né tránh) chưa vào chiến lực và trận vì engine chưa có các chỉ số này.

## Các đợt còn lại

Spec và plan: `2026-11-25-phase-2-remaining-spec.md`, `../plans/2026-11-25-phase-2-remaining-plan.md`.
Trạng thái 2026-11-25: code và test của A, Z, B, D, C, E, F xong (202 test); các bước emulator và mở view còn chờ.

### Đợt A: dọn nợ

A0/A1 (tutorial đội 2): `guide.config["2"]` chỉ mở nút 602 (cường hóa) và 601 (xem trang bị), không gọi API mới ngoài `factory.equip_levelup` đã có; chưa chạy lại trên emulator.

A2 (bộ trang bị): `equipment.bonus` cộng `suit.config` theo đúng `game_util.getEquipSuit`.
Một món khớp một `part` khi trang bị ở ô `sort` của part có cùng `equip_id` với config của part (nên món đã tiến hóa vẫn tính).
`effect_2/3/4` bật khi số món khớp đạt 2/3/4; `att_type` 1-5 vào `patk, matk, def, speed, hp`, trên 5 là thuộc tính nguyên tố (chưa vào trận).
Test: 2 món và 4 món, cộng một test chiến lực trên màn chính.

A3 (sức chứa): `equip_max` cố định 100 (chốt với chủ dự án); `rewards.grant` từ chối `error_equip_full` khi thêm trang bị vượt 100, nên gacha và mọi phần thưởng loại 7 đều bị chặn và rollback.
Test: túi đầy thì gacha và `grant` đều bị từ chối, ví không đổi.

A3 (khóa trang bị): client không có URL khóa; bỏ khỏi phạm vi (như spec).

### Đợt Z: cột `extra`

Migration 5 `ALTER TABLE equipment ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'`; `Store.equipment_rows` giải mã `extra`, thêm `equipment_extra` và `set_equipment_extra`.
`equipment.document` hợp nhất `extra`, bỏ khóa `_*` và `*_pending`; `equip_forge_temp` vẫn gửi vì popup rèn đọc từ cache.
Test migration trên DB cũ (đã cập nhật test cũ để bỏ cột trước khi chạy lại migration) và test document có/không có `extra`.

### Đợt B: tách (`equip.exchange`, view 25)

Module `equipment_split.py`; đọc `equip_id` lặp từ `Request.lists`, tối đa 11 món.
Từ chối món đang mặc, món có `bind_card`, id trùng, id không thuộc người chơi; cả lô rollback nếu một món sai.
Thưởng mỗi món: `metal` đều trong `equip_exchange[exchange_id].metal` cộng hoàn cường hóa và hoàn tinh luyện; `metalcore` tương tự; `exchange_id` lấy từ `equip.config`, thiếu thì dùng `quality`.
Test: số kim khí/metalcore khớp công thức, cache `remove`, các đường từ chối, rollback.

### Đợt D: tẩy luyện (`equip.equip_refine`, `equip.auto_refine`, view 148)

Module `equipment_refine.py`; trạng thái `extra.equip_refine` luôn có đủ `hp, patk, matk, def, speed`.
Mỗi lần gọi trừ tài nguyên theo `refine_{min|mid|max}_cost` nhân số lần; `is_save=0` không lưu, `is_save=1` lưu (client gọi lại nên tung lần mới).
Mỗi thuộc tính chọn khoảng theo trọng số rồi đều trong khoảng, cộng dồn và chặn theo `refine_control_1/2`.
Phản hồi `data.equip_refine` là mức đổi của lần gọi cho đúng hai thuộc tính.
`auto_refine` trả `can_refine_info`/`max_refine_info` với `need_times`, `refine_stone_need`, `coin_need`, `metal_need`, `metal_cost`, `refine_stone_cost`; thực hiện trừ từng lần, `handle_sort=1` tới trần, `2` đúng số trả được.
`bonus()` cộng `equip_refine` cho hai thuộc tính của món.
Test: preview không lưu, lưu có `hp`, chặn trần, giá 5 lần, thiếu đá rollback, truy vấn và thực hiện auto, chiến lực.

### Đợt C: phụ ma (`equip.enchant` và 3 lệnh, view 131)

Module `equipment_enchant.py`; giá mỗi lần `enchant.config[quality].piece`, trừ `user_status.enchant`.
Lần đầu: 1 khóa tấn công cho `sort` 1-2 hoặc 2 khóa phòng thủ cho `sort` 3-4, lưu `extra.enchant_pending`, trả `data.enchant_attrs`.
`save_init_enchant`: `is_save=1` ghi `is_enchant`/`atts` và trả `data.cur_atts`; `is_save=0` bỏ lần chờ.
Các lần sau: cộng đều `1..rate`, chặn `atk_max`/`def_max`, trả `cur_atts` và `enchant_attrs`.
`remove_enchant` xóa trạng thái, trả `data.enchant` bằng tổng mảnh đã tiêu cho món (`extra._enchant_spent`).
`auto_enchant`: `sort=-1` trả `need_times`, `can_times`, `enchant_cost`, `need_enchant`, `cur_atts`; `sort` 0/1/2 thực hiện.
Test: chờ lưu, lưu/hủy, cộng dồn và trần, hai khóa phòng thủ, gỡ hoàn mảnh, truy vấn auto.
Giới hạn: nguyên tố chưa vào trận và chiến lực.

### Đợt E: rèn (`equip.equip_forge_*`, view 167)

Module `equipment_forge.py`; `equip_forge_index` trả cả document; `equip_forge_level` nhận `"nhỏ_vừa_lớn"`, cộng 10/100/500 điểm, tiêu đá, dư chuyển cấp, trần 10, tính lại thuộc tính khi lên cấp.
`equip_forge_refresh`: `sort` 0/1/2 chọn loại đá, giá `equip_set_cost[sort+1].cost` gồm đá và sắt; `is_save=0` trả `equip_forge_temp` trong cache, `is_save=1` ghi `equip_forge` và `is_equip_forge`.
Ba thuộc tính khác nhau chọn theo `equip_sort` và `weight`.
Test: index, dư kinh nghiệm, preview/lưu, tính lại khi lên cấp, cộng vào bonus và thiếu đá rollback.

### Đợt F: vận mệnh (`equip.fate_equip_*`, view 182/193)

Module `equipment_fate.py`; gắn tốn 10 `min_fate_stone`, đặt `bind_card`, `bind_data` đủ hai khóa, `gem_fate [0,0,0,0]`.
`cards.open` và cache của thẻ gửi `bind_equip` (sort -> id) để client cộng `bind_data`; chiến lực nhân phần trăm theo từng thuộc tính sau khi cộng đồ.
Làm mới chọn dòng `equip_fate` theo `equip_quality` và `refresh_range1/2`, giá là tổng `refresh[sort-1]`, tung theo trọng số `refresh_equip_{min|mid|max}_fate{1|2}` rồi đều trong khoảng; trả `bind_data_temp`, `fate_range`, cache.
`auto_fate_equip_levelup` tung tới khi hết đá (tối đa 100 lần) và trả `leveup_times`.
Gỡ trả 10 `min_fate_stone` và xóa các khóa; không trả đá nâng cấp.
Test: gắn, làm mới, chiến lực, gỡ, auto.

### Kiểm chứng emulator (2026-11-25, tài khoản `p0tester1` / Hokage18, cấp 70)

Tài khoản được đặt cấp 70 và seed kim khí, đá các loại; thêm bộ Luffy 100101/100201/100301/100401 (bộ 1010, có `refine_id`).

- Tách (view 25): màn mở, chọn món hiện ước lượng 4000-4600 kim khí / 3600-4000 metalcore; bấm Phân giải, món biến mất, ví +4248 kim khí +3694 metalcore, không lỗi Lua.
- Tẩy luyện (view 148): danh sách chỉ có món `refine_id > 0`; chọn món, "Tẩy luyện 1 lần" trừ 3 đá và hiện HP +11, Tốc độ +6; bấm Đổi (lưu) ghi `equip_refine` có `hp`, `speed`.
- Rèn (view 167): "Auto thêm" chọn 400 đá thô, Rèn lên cấp 1 (0/28000), Tạo mới hiện 3 thuộc tính (2 dòng "(Địch)" âm và 1 dòng dương), Lưu ghi `equip_forge`.
  Lần đầu mở popup rèn báo `game_equip_forge_pop.lua:353 next(equip_forge)`; đã sửa: `equip_forge` (có thể rỗng) luôn được gửi từ cấp 1 trở lên, kèm test.
- Vận mệnh: popup "Nâng cấp trang bị vận mệnh" ban đầu rỗng (chưa món nào gắn). Gắn qua API đúng giao thức, sau đó mở lại: món đã gắn hiện trong danh sách, "Làm mới 1 lần" trừ 10 đá và hiện Tốc độ/HP mới cùng khoảng -2%~+9%.
- Phụ ma (view 131): "Phù phép" lần đầu trả Địa công +57 và chuyển sang Lưu/Hủy; Lưu ghi `is_enchant`/`atts`; phù phép tiếp +10 (57→67); "Phù phép nhanh" hiện đúng hộp thoại (cần 60 lần, 4800 mảnh, thêm 11120 xu) và "Cao nhất" chạy 60 lần, Địa công lên 4985.

Không còn `LUA ERROR` nào khác sau khi sửa. View 25, 131, 148, 167, 182, 193 đã chuyển sang `module: "equip"` trong `data/scope_2018.json`.

### Còn lại của phase 2

- A0/A1: chạy tutorial đội 2 trên tài khoản mới để xác nhận 13 bước, rồi bỏ ghi chú "phải bỏ qua đội 2" nếu qua được.
- E6: nếu màn tách cần nhãn "đá" thì trả thêm phần đá rèn đã dùng (client đọc `equip_forge_level.exp`), hiện mới hiển thị.
- Đợt G (đá quý) và H (thống soái) chuyển sang phase 3; mỗi đợt cần spec nghiên cứu riêng.

