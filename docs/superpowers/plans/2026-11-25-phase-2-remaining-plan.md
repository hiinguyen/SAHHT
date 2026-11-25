# Giai đoạn 2: kế hoạch cho phần còn lại

Ngày: 2026-11-25.
Spec chi tiết: `../specs/2026-11-25-phase-2-remaining-spec.md`.
Tiến độ thực tế ghi ở: `../specs/2026-11-24-phase-2-progress.md` (cập nhật sau mỗi bước, không ghi ở đây).
Trạng thái 2026-11-25: code và test của A, B, Z, D, C, E, F xong (202 test).
Emulator đã chạy tách, tẩy luyện, phụ ma, rèn và vận mệnh; view 25, 131, 148, 167, 182, 193 đã mở trong scope.
Còn A0/A1 (tutorial đội 2) và E6 (hoàn đá khi tách); G/H chuyển phase 3.

## Cách làm mỗi đợt (vòng lặp chuẩn)

Mỗi đợt đi đủ các bước sau, mỗi bước xong thì tick vào file tiến độ:

1. Đọc Lua và config của đợt (danh sách khóa client đọc không kiểm nil).
2. Viết test thất bại trước trong `server/tests/test_gameplay.py` (class `EquipmentTests`) và, nếu cần, thêm config giả vào `FIXTURE_CONFIGS` ở `server/tests/test_flow.py`.
3. Cài đặt tối thiểu cho test xanh.
4. Chạy cả bộ test: `cd server && python3 -I -m unittest discover -s tests -t .`.
5. Mở view trong `server/data/scope_2018.json` (module `equip`, bỏ `open: false`).
6. Chạy emulator (`tools/cycle.sh`, đặt `players.level` đủ lớn, seed tài nguyên trong `sahht.db`), đọc `LUA ERROR`, chụp màn hình, thử cả đường thành công và thất bại.
7. Cập nhật tiến độ, `server/README.md` (bảng tính năng và mục "Not done") và `CLAUDE.md` (mục "Not done").

Quy ước cứng: chỉ commit khi chủ dự án yêu cầu; mỗi đợt không chờ đợt sau.

## Đợt A: dọn nợ (ước lượng: nhỏ)

Mục tiêu: gỡ rủi ro trước khi thêm tính năng.

- [ ] A0. Chạy tutorial đội 2 trên tài khoản mới ở emulator (13 bước, id 28-40), ghi bước nào gọi API gì.
- [ ] A1. Nếu A0 lỗi: sửa theo từng khóa thiếu (test trước), rồi xóa ghi chú "phải bỏ qua đội 2" trong `CLAUDE.md`.
- [x] A2. Đọc công thức bộ trang bị (`suit`, `equip_set_*`) trong `game_util.lua`; bổ sung vào spec; cài `equipment.bonus()` có suit; test: 2 và 4 món cùng bộ.
- [x] A3. Giới hạn sức chứa: chốt `equip_max` (câu hỏi 3 trong spec); chặn `equip_gacha`, `grant()` có trang bị và các đường tạo trang bị khác khi đầy; test từng đường; xác nhận cách client báo đầy.

Tiêu chí xong: tài khoản mới đi hết tutorial đội 2; chiến lực khớp với bonus bộ; túi đầy bị từ chối ở mọi đường tạo trang bị.

## Đợt Z: nền cho thuộc tính mở rộng (làm ngay trước đợt đầu tiên cần nó, tức D)

- [x] Z1. Quyết định câu hỏi 1 (cột JSON `extra`).
- [x] Z2. Thêm migration (nối vào `MIGRATIONS`, không sửa migration cũ): `ALTER TABLE equipment ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'`.
- [x] Z3. `Store.equipment_extra(uid, equip_id)` và `Store.set_equipment_extra(uid, equip_id, extra)`; test migration trên DB cũ (`user_version` tăng đúng, dữ liệu cũ nguyên vẹn).
- [x] Z4. `equipment.document()` hợp nhất `extra`, bỏ khóa `*_pending`; test document có và không có `extra`.

## Đợt B: tách (`equip.exchange`, view 25) (ước lượng: nhỏ)

- [x] B1. Test: nhiều `equip_id` lặp qua `Request.lists`; phần thưởng nằm trong khoảng của `equip_exchange` cộng hoàn phí cường hóa và tinh luyện (tung cố định bằng mock); trang bị bị xóa, `remove` có trong cache; từ chối món đang mặc, món có `bind_card`, id trùng hoặc không thuộc người chơi; toàn bộ rollback nếu một món sai.
- [x] B2. Handler `equip_exchange`, đăng ký `equip.exchange`; đặt trong module mới `equipment_split.py` để `equipment_actions.py` không phình.
- [x] B3. Mở view 25; emulator: màn tách ở cấp 26, chọn vài món, xác nhận số kim khí và metalcore khớp phản hồi.
- [x] B4. Tài liệu.

Rủi ro: client gửi `equip_id` dạng chuỗi truy vấn thô; kiểm tra bằng `requests.jsonl` trước khi viết test.

## Đợt D: tẩy luyện (`equip.equip_refine`, `equip.auto_refine`, view 148) (ước lượng: vừa)

Cần Z. Làm trước C vì cộng được vào chiến lực.

- [x] D1. Seed: trang bị có `refine_id > 0` và `refine_stone` trong ví.
- [x] D2. Test: tung xem trước không lưu và không đổi dữ liệu; lưu ghi `equip_refine` có đủ `hp`; chặn theo `refine_control`; trừ tiền đúng loại (`type` 1-3); thiếu `refine_stone` thì rollback.
- [x] D3. Tung: chọn khoảng theo trọng số rồi đều trong khoảng, hai thuộc tính; `sort` lặp 1, 5, 10 lần.
- [x] D4. `auto_refine`: truy vấn (số lần cần và số lần đủ) và thực hiện (`handle_sort` 1, 2).
- [x] D5. `equipment.bonus()` cộng `equip_refine`; test chiến lực tăng đúng.
- [x] D6. Mở view 148; emulator: tung 1 lần, 5 lần, lưu, tung nhanh; đối chiếu chiến lực trên màn chính.
- [x] D7. Tài liệu (giới hạn: cờ bạo kích bổ sung chưa tính).

## Đợt C: phụ ma (`equip.enchant` và 3 lệnh khác, view 131) (ước lượng: vừa)

Cần Z.

- [x] C1. Test cho từng lệnh: lần đầu tung (chờ lưu) rồi lưu và hủy; phụ ma tiếp theo cộng và chặn theo `atk_max/def_max`; gỡ hoàn mảnh và xóa `is_enchant`; `auto_enchant` truy vấn và thực hiện (ba giá trị `sort`); thiếu mảnh thì rollback.
- [x] C2. Cài đặt trong module mới `equipment_enchant.py`.
- [x] C3. Chốt luật tự đặt (câu hỏi 2) và ghi vào spec.
- [x] C4. Mở view 131; emulator: lần đầu, lưu, phụ ma tiếp, tự động, gỡ.
- [x] C5. Tài liệu (giới hạn: nguyên tố chưa vào trận).

## Đợt E: rèn (`equip.equip_forge_*`, view 167) (ước lượng: vừa)

Cần Z.

- [x] E1. Đọc thêm `equip_set_rate` hàng 6-9 và cách client tính giá trị ở `getNextProperty`; bổ sung vào spec.
- [x] E2. Test: `equip_forge_index` trả document đủ khóa; lên cấp bằng đá (dư chuyển cấp sau, trần cấp 10); làm mới xem trước và lưu; 3 thuộc tính khác nhau theo trọng số; thiếu đá thì rollback.
- [x] E3. Cài đặt module `equipment_forge.py`.
- [x] E4. `bonus()` cộng thuộc tính rèn thuộc nhóm `hp, patk, matk, def, speed`.
- [x] E5. Mở view 167; emulator ở cấp 60; thử cả ba loại đá.
- [ ] E6. Nối nhãn "đá" của đợt B (hoàn đá khi tách) nếu cần.
- [x] E7. Tài liệu.

## Đợt F: vận mệnh (view 182/193) (ước lượng: vừa)

Cần Z; không cần E.

- [x] F1. Xác nhận tên URL gắn và gỡ trong `game_url_config.lua`; đọc client cộng `bind_data` thế nào.
- [x] F2. Test: gắn (tốn 10 đá, đặt `bind_card`, `bind_data` đủ hai khóa); gỡ; làm mới theo ba loại đá; `bind_temp` và `fate_range` có mặt.
- [x] F3. Cài đặt module `equipment_fate.py`.
- [x] F4. Cập nhật đợt B: tách từ chối món đã gắn.
- [x] F5. Mở view 182/193; emulator; tài liệu.

## Đợt G: đá quý (ước lượng: lớn, chia 3)

- [ ] G0. Nghiên cứu: hình dạng `gem`, `gem_pos`, các khóa client đọc không kiểm nil, cách đá cộng chỉ số; viết `specs/2026-11-25-phase-2-gems.md`; duyệt trước khi cài đặt.
- [ ] G1. Kho đá, gắn, tháo, tổng hợp (`gem.synthesis`).
- [ ] G2. Nâng cấp, tiến hóa (`gem.upgrade`, `gem.evolution`), phân giải (`gem.resolve`).
- [ ] G3. Đá vận mệnh (`gem_fate.*`).
- [ ] Mỗi nhóm đi đủ vòng lặp chuẩn; mở view tương ứng sau mỗi nhóm.

## Đợt H: thống soái (ước lượng: vừa)

- [ ] H0. Nghiên cứu màn `game_ability_commander`, hình dạng `commander_attrs` và `commander_available_skill`; viết `specs/2026-11-25-phase-2-commander.md`.
- [ ] H1. `commander.index`, `commander.synthesis`.
- [ ] H2. Quyết định có làm `quick_rob` cho NPC hay không.
- [ ] H3. Chỉ số thống soái vào chiến lực.

## Không làm trong phase 2 (cần chủ dự án duyệt)

- Đúc (`equip.equip_building*`): thiếu 5 config trong APK, client lỗi ở bước chọn nguyên liệu, cấp mở 110.
- Xưởng (`factory.*` trừ `equip_levelup`): không có UI gọi tới.
- Cướp mảnh thống soái giữa người chơi (`rob`, `search`, `protect`, `enemies`).
- Chỉ số phụ (nguyên tố, bạo kích, chính xác, giảm thương, né tránh) trong engine trận: thuộc phase khác.

## Thứ tự tóm tắt

A, B, Z, D, C, E, F, G (G0 đến G3), H.
Sau mỗi đợt, hỏi chủ dự án có commit hay không.

## Rủi ro chung

- Khóa client đọc không kiểm nil chỉ lộ ra khi chạy emulator; dự trù ít nhất hai vòng sửa khóa cho mỗi đợt.
- Luật tung tự đặt có thể khác server gốc; ghi mọi chỗ tự đặt trong spec để sau này đổi ở một nơi.
- Emulator có thể đang đăng nhập tài khoản khác `testplayer1`; kiểm tra tên hiển thị trước khi seed dữ liệu.
- `equipment_actions.py` đang gần 200 dòng; mỗi tính năng mới tách module riêng để file luôn tập trung và dưới giới hạn 800 dòng.
