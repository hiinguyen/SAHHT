# Giai đoạn 3: kế hoạch chiến đấu đầy đủ

Ngày: 2026-11-25.
Spec: `../specs/2026-11-25-phase-3-combat.md`.
Tiến độ thực tế ghi ở: `../specs/2026-11-25-phase-3-progress.md` (tạo khi bắt đầu đợt đầu tiên, cập nhật sau mỗi bước, không ghi ở đây).

## Tiền đề

- Phase 2: A0/A1 (tutorial đội 2) và E6 còn mở; không chặn phase 3 nhưng nên đóng A0/A1 trước vì cả hai chạm vào engine trận qua đội tutorial.
- Chạy cả bộ test xanh trước khi bắt đầu: `cd server && python3 -I -m unittest discover -s tests -t .`.
- Chỉ commit khi chủ dự án yêu cầu.

## Vòng lặp chuẩn mỗi đợt

1. Nghiên cứu: đọc Lua và config của đợt, ghi khóa client đọc không kiểm nil và các luật chưa biết vào spec.
2. Viết test thất bại trước (RED).
3. Cài đặt tối thiểu (GREEN).
4. Chạy cả bộ test.
5. Mở view trong `server/data/scope_2018.json` nếu đợt có màn mới.
6. Chạy emulator (`tools/cycle.sh`), đọc `LUA ERROR`, chụp màn hình.
7. Cập nhật tiến độ, `server/README.md`, `server/SKILLS.md` và mục "Not done" của `CLAUDE.md`.

## Đợt 0: đường cơ sở và công cụ đo

- [ ] 0.1 Nghiên cứu U1: viết `tools/audit_enemy_skills.py` đếm id kĩ năng quái (mọi trận campaign thường) chưa có spec, sắp theo số lần xuất hiện; in thêm `skill_type`, `desc` và đề xuất mẫu DSL.
- [ ] 0.2 Mô phỏng đường cơ sở: một script chạy 8384 trận bằng đội mẫu theo cấp thành phố, ghi tỉ lệ thắng và số hiệp trung vị vào tiến độ (để so sau 3.1 và 3.2).
- [ ] 0.3 Nghiên cứu U2, U3: lập bảng id thuộc tính sang chỉ số (từ `equip_att*`, `suit`, `enchant`, `equip_set_*`, `equip_gem_fate*`, `role_attri_add`), đọc công thức trong `game_util.lua` và `game_battle_*`; ghi vào spec cùng cờ "tự đặt" cho chỗ không có nguồn.
- [ ] 0.4 Nghiên cứu U4, U5, U6: đọc `leader_skill.*` (màn, URL, khung phản hồi), đọc `cards.select_skill_index` và `set_battle_skill`; ghi hình dạng dữ liệu vào spec.

Tiêu chí xong: tiến độ có số đo cơ sở, spec có phần "Kết quả nghiên cứu" cho U1-U6, chủ dự án duyệt các luật tự đặt.

## Đợt 3.1: kĩ năng quái (ước lượng: lớn, làm theo lô)

Cần 0.1 và 0.2.

- [ ] 3.1.1 Thêm `data/enemy_skill_specs.json` và cho `skills.py` tìm ở cả hai file; mở rộng `skill_spec.py` kiểm cả hai.
  Test: id quái được tìm thấy, id không tồn tại báo lỗi, hai file không trùng khóa.
- [ ] 3.1.2 Lô 1: 12 id nhiều nhất (phủ khoảng một nửa lượt dùng); test engine với một quái dùng từng id (sát thương, `cd`, `rate` cố định bằng mock).
- [ ] 3.1.3 Lô 2 đến N: theo thứ tự từ công cụ kiểm kê, mỗi lô khoảng 40 id, cho tới khi kiểm kê báo 0 id thiếu.
  Op nào DSL chưa có thì thêm vào `skill_spec.py`/`battle.py` kèm test và ghi vào `SKILLS.md`.
- [ ] 3.1.4 Chạy cả 8384 trận: không lỗi, không vòng lặp vô hạn, thời gian chạy một trận trong ngưỡng (ghi ngưỡng ở tiến độ).
- [ ] 3.1.5 So tỉ lệ thắng với đường cơ sở; báo chủ dự án nếu tụt mạnh ở các thành phố đầu (người chơi mới phải qua được).
- [ ] 3.1.6 Emulator: chơi các ải đầu và một ải cuối chương; đọc khung `skill` có phát, không có `LUA ERROR`.
- [ ] 3.1.7 Tài liệu.

Rủi ro: kĩ năng quái dùng khung hoặc tên mà client chưa có hiệu ứng thì bị bỏ im lặng (an toàn); kĩ năng có `pre_battle` sai khung có thể làm client sập (`CLAUDE.md`), nên không bao giờ gửi `pre_battle` cho quái.

## Đợt 3.2: chỉ số phụ (ước lượng: lớn)

Cần 0.3. Không phụ thuộc 3.1 nhưng nên sau để đo riêng từng thay đổi.

- [ ] 3.2.1 Test: `battle_unit` nhận các trường mới từ quái (`crit`, `hr`, `dr`, `subhurt`, nguyên tố, `*_dfs`) và từ `equipment.bonus()`.
- [ ] 3.2.2 `equipment.bonus()` tách phần chỉ số phụ khỏi nhóm cơ bản; test từng nguồn: suit `att_type` trên 5, phụ ma, tẩy luyện và rèn ngoài nhóm cơ bản, vận mệnh phần trăm.
- [ ] 3.2.3 Engine: né tránh, chính xác, bạo kích (có thể phát khung `crit` nếu client có), giảm thương; test với tung cố định bằng mock.
- [ ] 3.2.4 Sát thương nguyên tố của đòn thường và `attr_damage`; test hai bên có và không có nguyên tố phòng thủ.
- [ ] 3.2.5 Chiến lực màn chính cộng chỉ số phụ; đối chiếu với công thức client.
- [ ] 3.2.6 Mô phỏng 8384 trận lần hai; ghi chênh lệch.
- [ ] 3.2.7 Emulator: trang bị phụ ma và rèn lên tướng, xem chiến lực và kết quả trận.
- [ ] 3.2.8 Tài liệu, bỏ các dòng "stored but never applied" trong README và `SKILLS.md`.

Rủi ro: công thức gốc chưa rõ (U3); ghi mọi chỗ tự đặt, tập trung vào một module để đổi một chỗ.

## Đợt 3.3: kĩ năng hoán đổi

Cần 0.4.

- [ ] 3.3.1 Migration lưu kĩ năng đã chọn; test migration trên DB cũ (`user_version` tăng đúng, dữ liệu cũ nguyên).
- [ ] 3.3.2 Test: `cards.select_skill_index` và `cards.set_battle_skill` đổi lựa chọn, từ chối kĩ năng chưa mở khóa, `cards.open` phản ánh lựa chọn.
- [ ] 3.3.3 Handler, đăng ký vào `handlers.SESSION_HANDLERS`.
- [ ] 3.3.4 Engine dùng kĩ năng đã chọn; spec kĩ năng ô 4-5 đã có trong `skill_specs.json` (kiểm tra tướng 5 kĩ năng nào còn thiếu).
- [ ] 3.3.5 Bỏ override `skill_num` 3; emulator: mở màn đổi, đổi kĩ năng, vào trận, xem khung `skill` đúng.
- [ ] 3.3.6 Tài liệu.

## Đợt 3.4: kĩ năng đội trưởng

Cần 0.4 và có thể cần 3.2 (một số kĩ năng gây sát thương nguyên tố).

- [ ] 3.4.1 Lập bảng 96 kĩ năng: tên, `script`, có tệp `skill_effect/leader_skill/<name>.lua` trong APK hay không, loại hiệu ứng; chỉ làm cái có tệp.
- [ ] 3.4.2 Migration và bảng kĩ năng đội trưởng của người chơi; test migration.
- [ ] 3.4.3 Handler `leader_skill.*` theo kết quả 0.4; test học (điều kiện `pre_skill`, giá), nâng cấp (trần `max_level`), từ chối.
- [ ] 3.4.4 Nộ khí và phát trong engine; thêm DSL cho kĩ năng đội trưởng (hoặc spec riêng `data/leader_skill_specs.json`); op `rage` có tác dụng.
- [ ] 3.4.5 Khung dữ liệu trận cho kĩ năng đội trưởng, chạy trên emulator; không gửi `pre_battle`.
- [ ] 3.4.6 Mở view `leader_skill` trong `scope_2018.json`; emulator: học, nâng cấp, phát trong một trận.
- [ ] 3.4.7 Tài liệu.

## Nhánh G: đá quý (ước lượng: lớn, chia 3)

Chỉ bắt đầu sau 3.2; cần chủ dự án duyệt giữ trong giai đoạn 3.

- [ ] G0 Nghiên cứu hình dạng `gem`, `gem_pos`, các khóa client đọc không kiểm nil (`game_data.lua` quanh 3800-3835, `setGemDataByJsonData`); viết `phase-3-gems.md`; duyệt trước khi cài.
- [ ] G1 Kho đá, gắn, tháo, tổng hợp (`gem.synthesis`).
- [ ] G2 Nâng cấp, tiến hóa, phân giải (`gem.upgrade`, `gem.evolution`, `gem.resolve`).
- [ ] G3 Đá vận mệnh (`gem_fate.*`).
- [ ] Mỗi nhóm đi đủ vòng lặp chuẩn; mở các view 129, 130, 181, 196, 203, 226 theo nhóm; chỉ số đá cộng qua đường 3.2.

## Nhánh H: thống soái (ước lượng: vừa)

Chỉ bắt đầu sau 3.2; ưu tiên thấp nhất.

- [ ] H0 Nghiên cứu màn `game_ability_commander`, hình dạng `commander_attrs`, `commander_available_skill`; viết `phase-3-commander.md`.
- [ ] H1 `commander.index`, `commander.synthesis` (24 công thức `commander_recipe`).
- [ ] H2 Quyết định (chủ dự án) có làm cướp mảnh cho NPC hay không.
- [ ] H3 Chỉ số thống soái vào chiến lực và trận.
- [ ] H4 Mở view 16; emulator; tài liệu.

## Thứ tự tóm tắt

0 (nghiên cứu và đo), 3.1, 3.2, 3.3, 3.4, G, H.
Đợt 3.3 độc lập với 3.1 và 3.2 nên có thể đổi chỗ nếu cần mở nút đổi kĩ năng sớm.
Sau mỗi đợt, hỏi chủ dự án có commit hay không.

## Rủi ro chung

- Không có script gốc của server, nên mọi luật tung và công thức chỉ số là suy luận từ config và Lua; ghi cờ và gom vào một module để đổi một chỗ.
- Khóa client đọc không kiểm nil chỉ lộ khi chạy emulator; dự trù ít nhất hai vòng sửa khóa cho mỗi màn mới.
- Làm quái mạnh lên có thể chặn người chơi mới; luôn đo bằng mô phỏng trước và sau, không chỉnh chỉ số quái để bù.
- Gửi sai khung trận có thể làm native engine sập (xem `pre_battle` trong `CLAUDE.md`); mọi khung mới phải thử trên emulator trước khi coi là xong.
- `battle.py` đã 673 dòng; thêm logic mới vào module riêng (ví dụ `battle_stats.py`, `leader_skill.py`) để mỗi file dưới 800 dòng.
- Emulator có thể đang đăng nhập tài khoản khác; kiểm tra tên hiển thị trước khi seed dữ liệu.
