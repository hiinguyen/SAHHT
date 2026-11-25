# Giai đoạn 3: chiến đấu đầy đủ (spec)

Ngày: 2026-11-25.
Plan triển khai: `../plans/2026-11-25-phase-3-combat-plan.md`.
Lộ trình gốc: `2026-11-23-roadmap-2018.md` (giai đoạn 3 đứng sau giai đoạn 2 vì chỉ số nguyên tố đến từ trang bị).

## Mục tiêu

Trận chiến của server khớp với game gốc ở bốn điểm mà hiện giờ đang bị đơn giản hóa:

1. Quái dùng kĩ năng (`skill1..3` dạng 900xx, 800xx, 400xx, 600xx) thay vì chỉ đánh thường.
2. Chỉ số phụ có tác dụng trong trận: sát thương nguyên tố, bạo kích, chính xác, né tránh, giảm thương.
3. Kĩ năng đội trưởng (nộ khí, `leader_skill.*`).
4. Kĩ năng hoán đổi của tướng có 5 kĩ năng (ô 4-5).

Phần chuyển từ giai đoạn 2 sang (đá quý, thống soái) nằm ở mục "Nhánh G và H".
Lý do gom vào đây: cả hai chỉ có ý nghĩa khi cộng chỉ số vào trận, nên chúng dùng đường chỉ số của mục 3.2.

## Hiện trạng đã xác nhận

Số liệu đọc từ `decompiled/apk/assets/config` ngày 2026-11-25:

- `skill_detail.config` có 11088 dòng, trong đó 499 id bắt đầu bằng 9.
- Quái trong `enemy_soldier_*.config` và `enemy_detail.config` dùng 487 id kĩ năng khác nhau.
  Trường là `skill1..3`, giá trị dạng `[id, cấp]`, ví dụ `[90001, 10]`.
- Mười hai id dùng nhiều nhất: 90001 (2681 lần), 80001 (1810), 40110 (1102), 40120 (1086), 40130 (1014), 90007 (694), 60020 (605), 60030 (605), 60040 (605), 90046 (459), 90044 (382), 90016 (363).
- Kĩ năng quái phổ thông là đòn đơn giản: 90001 và 90007 là `KBEFOREATTACK`, `rate` 100, `cd` 3, `effect` 150; 80001 có `rate` 40, `cd` 1, `effect` 120; 60020 có `rate` 30, `cd` 1, `effect` 120.
- `enemy_detail` đã có `crit`, `hr`, `dr`, `subhurt`, `fire/water/wind/earth` và `*_dfs`; engine chỉ đọc các cột nguyên tố khi một kĩ năng có `attr_damage`, nên quái hiện không dùng chúng.
- `leader_skill.config` có 96 kĩ năng (`base_effect1/2`, `add_effect1/2`, `cd`, `max_level`, `pre_skill`, `script`, `story`), kèm `leader_skill_tree.config` và `leader_skill_develop.config`.
  Client chạy hiệu ứng từ `skill_effect/leader_skill/<name>.lua` (`game_battle_skill.lua:1981`).
- Tướng 5 kĩ năng: client gọi `cards.select_skill_index` (`skills_strengthen_scene.lua`) và `cards.set_battle_skill` với `skill_ids` dạng `3_4_5` (`game_skills_exchange_pop.lua:85`).
  Server hiện báo `skill_num` 3 trong `config_overrides` để ẩn nút đổi.
- Engine: `battle.py` 673 dòng, `battle_unit.py` 186 dòng, `skills.py`, `skill_spec.py`; 589 spec trong `data/skill_specs.json`.
  Op `rage` trong `battle.py:447` đang bỏ qua.
- Cột nguyên tố từ trang bị đã được lưu: `suit.config` `att_type` trên 5, thuộc tính phụ ma (`atts`), thuộc tính rèn và tẩy luyện ngoài nhóm `hp, patk, matk, def, speed`, dòng vận mệnh.
  `equipment.bonus()` bỏ chúng khỏi chiến lực.

## Điều chưa biết (phải nghiên cứu trước khi cài)

- U1. Mỗi trong 487 id kĩ năng quái có `desc` đủ để viết spec bằng DSL hiện có không, hay cần thêm op mới.
- U2. Bảng id thuộc tính của trang bị (`att_type`, khóa `atts`, `bind_data`, `equip_forge`) ánh xạ sang chỉ số nào: nguyên tố tấn công, nguyên tố phòng thủ, bạo kích, chính xác, né tránh, giảm thương.
- U3. Công thức gốc của bạo kích, chính xác, né tránh, giảm thương (`crit`, `hr`, `dr`, `subhurt` của quái cho thấy thang đo, nhưng chưa biết đơn vị).
- U4. Nộ khí: tăng thế nào trong trận, trần bao nhiêu, khung dữ liệu nào client dùng để vẽ thanh nộ và phát kĩ năng đội trưởng.
- U5. API của kĩ năng đội trưởng (`leader_skill.open` và các lệnh học, nâng cấp), và cách client gửi lựa chọn kĩ năng vào trận.
- U6. Kĩ năng đổi của tướng 5 kĩ năng: ô 4-5 là kĩ năng mở khóa thêm hay thay thế ô 1-3, `cards.select_skill_index` lưu gì.

Mỗi điều chưa biết có một bước nghiên cứu riêng trong plan; kết quả ghi vào cuối spec này, không đoán.

## Thiết kế

### 3.1 Kĩ năng quái

Dùng lại DSL và engine của tướng (`SKILLS.md`); quái chỉ là nguồn spec thứ hai.

- `data/skill_specs.json` giữ spec của tướng, thêm `data/enemy_skill_specs.json` cho quái, cùng schema và cùng bộ kiểm tra `skill_spec.py`.
  Tách file vì khóa đều là id kĩ năng và nguồn dữ liệu khác nhau, nhưng `skills.py` tìm cả hai.
- Quái có kĩ năng cấp cố định theo `[id, cấp]` của cấu hình quái; `skills.py` đã nhận cấp.
- Công cụ kiểm kê `tools/audit_enemy_skills.py`: duyệt mọi trận campaign, đếm id kĩ năng quái không có spec, sắp theo số lần xuất hiện.
  Thứ tự viết spec theo công cụ này; mục tiêu là 100% id xuất hiện trong trận campaign thường (8384 trận) có spec.
- Kĩ năng quái không có animation phía client thì engine vẫn phát khung `skill` với tên không tồn tại; client bỏ qua im lặng (đã ghi trong `CLAUDE.md`), nên không gây lỗi nhưng mất hiệu ứng.
  Chỉ ghi nhận, không làm lại hiệu ứng.
- Quái hiện đánh thường mà vẫn qua mọi trận; thêm kĩ năng làm trận khó hơn.
  Quy tắc cân bằng: không đổi chỉ số quái để bù; chạy lại mô phỏng cả 8384 trận với đội mẫu cùng cấp và ghi tỉ lệ thắng trước và sau vào tiến độ.

### 3.2 Đường chỉ số phụ

Một nơi duy nhất tính chỉ số chiến đấu của một đơn vị: mở rộng `battle_unit.py` với các trường nguyên tố, bạo kích, chính xác, né tránh, giảm thương, và nạp từ hai nguồn qua cùng một hàm.

- Quái: cột trực tiếp của `enemy_detail`.
- Tướng: `equipment.bonus()` trả thêm các chỉ số này (tách khỏi nhóm `hp, patk, matk, def, speed`), sau đó nhân phần trăm vận mệnh như hiện nay.
- Engine áp dụng:
  - sát thương thường và kĩ năng vật lý/ma pháp đi qua né tránh, chính xác, bạo kích, giảm thương;
  - `attr_damage` dùng nguyên tố tấn công trừ nguyên tố phòng thủ của đích (đã có công thức trong `SKILLS.md`);
  - nguyên tố tấn công của tướng cộng thêm đòn đánh thường theo luật gốc (cần U3).
- Chiến lực trên màn chính cộng chỉ số phụ theo `combat_skill.config`/công thức client (cần đọc `game_util` trước).
- Mọi luật tự đặt (vì không có script gốc) ghi vào spec này kèm cờ, giống cách giai đoạn 2 làm, để đổi ở một chỗ.

### 3.3 Kĩ năng hoán đổi (tướng 5 kĩ năng)

- Lưu lựa chọn kĩ năng trận của từng thẻ (bảng `card_skills` đã có; thêm cột hoặc bảng theo U6, bằng migration mới, không sửa migration đã áp dụng).
- Handler `cards.select_skill_index`, `cards.set_battle_skill`; engine dùng kĩ năng đã chọn thay vì ô 1-3 cố định.
- Bỏ override `skill_num` 3 để nút đổi hiện ra; kiểm tra màn `game_skills_exchange_pop` trên emulator.

### 3.4 Kĩ năng đội trưởng

- Bảng lưu: kĩ năng đã học và cấp của người chơi (`leader_skill.config` cho giá và điều kiện `pre_skill`).
- Handler `leader_skill.*` (tên cụ thể sau U5), mở view `leader_skill` trong `scope_2018.json`.
- Engine: thanh nộ khí, điều kiện phát, hồi (`cd`), khung dữ liệu phát kĩ năng (tên kịch bản `script`/`name` để client chạy `skill_effect/leader_skill/<name>.lua`).
- Op `rage` của DSL tướng bắt đầu có tác dụng.
- Trong 96 kĩ năng, chỉ làm những cái có `script` mà APK có tệp hiệu ứng; còn lại ghi `note` và để đóng.

### Nhánh G và H (chuyển từ giai đoạn 2)

- G, đá quý (`gem.*`, `gem_fate.*`, view 129, 130, 181, 196, 203, 226): kho đá và vị trí gắn (khóa `gem`, `gem_pos` của `cards.open`), tổng hợp, nâng cấp, tiến hóa, phân giải, đá vận mệnh.
  Chỉ số đá cộng qua đường 3.2.
- H, thống soái (`commander.*`, view 16): `commander.index`, `synthesis`; `commander_attrs` và `commander_available_skill` của `cards.open`; chỉ số cộng qua đường 3.2.
  Không làm cướp mảnh giữa người chơi (`rob`, `quick_rob`, `search`, `protect`, `enemies`) trừ khi chủ dự án duyệt.
- Cả hai bắt đầu bằng một spec nghiên cứu riêng (`phase-3-gems.md`, `phase-3-commander.md`); hình dạng khóa `gem`, `gem_pos`, `commander_attrs` đến nay chưa xác nhận.

## Ngoài phạm vi giai đoạn 3

- Hiệu ứng hình ảnh mới cho kĩ năng quái thiếu animation.
- Kĩ năng thú cưng, huy hiệu, bang hội (giai đoạn 5 và 6): các tệp `pet_skill_*`, `badge_skill_*` để nguyên.
- PvP và đấu trường (giai đoạn 6): engine chỉ cần không phá khả năng chạy hai bên là người chơi, không làm thêm.
- `kaiqigu`, phần native, `.sam`: không đụng.

## Quyết định cần chủ dự án

1. Có giữ G và H trong giai đoạn 3 (khuyến nghị: có, làm sau 3.4) hay đẩy sang giai đoạn riêng.
2. Khi luật gốc không tìm được (U3), chấp nhận công thức tự đặt gần đúng và ghi cờ (khuyến nghị: chấp nhận).
3. Độ khó: cho phép trận khó hơn sau khi quái dùng kĩ năng (khuyến nghị: chấp nhận, đo bằng mô phỏng, không chỉnh chỉ số quái).
4. Thứ tự: kĩ năng quái trước, rồi chỉ số phụ, rồi hoán đổi, rồi đội trưởng (khuyến nghị theo plan).

## Tiêu chí xong của giai đoạn

- 100% id kĩ năng quái xuất hiện trong campaign thường có spec hợp lệ, cả 8384 trận chạy xong trong engine không lỗi.
- Tướng có chỉ số nguyên tố, bạo kích, chính xác, né tránh, giảm thương từ trang bị và các chỉ số đó đổi kết quả trận theo test.
- Tướng 5 kĩ năng đổi được kĩ năng trên emulator; nút đổi hiện.
- Kĩ năng đội trưởng học, nâng cấp và phát được trong một trận campaign trên emulator.
- Bộ test xanh, không `LUA ERROR` mới, `tools.audit_scope` khớp scope.
- Phần G và H, nếu giữ trong giai đoạn: mỗi màn mở được và chỉ số vào chiến lực.

## Kết quả nghiên cứu U1-U6

Đo ngày 2026-11-25 trên config và Lua đã giải mã. Số đo đầy đủ ở
`2026-11-25-phase-3-progress.md`.

### U1. Kĩ năng quái

- Campaign thường: 8384 trận, 41 687 lượt quái, 166 id kĩ năng, 0 id thiếu trong
  `skill_detail.config`.
- 150 id cần spec mới; 16 id 4 chữ số dùng chung spec tướng đã có.
- Mọi id đều có `skill_story` tiếng Việt dùng được; vài mô tả thiếu số (90001, 90002 chỉ
  nêu phần cộng thêm; 90037 bị cắt câu) nên lấy `effect` của config.
- 44 id 900xx là một khuôn chung: `max_lv` 1, `effect_lvchange` 0, `rate` 100, `cd` 3 hoặc 1.
- 21 nhóm trùng số liệu nhưng khác hành vi; chỉ 2 cặp trùng cả script, số và mô tả.

### U2. Bảng id thuộc tính

`game_config.lua` `PUBLIC_ABILITY_TABLE`: 1-5 chỉ số cơ bản, 6 `crit`, 7 `hr`, 8 `subhurt`,
9 `dr`, 101-105 phần trăm, 201-204 nguyên tố công, 301-304 nguyên tố phòng, 11-16 chỉ số
ẩn của đấu trường/bang. Trang bị chỉ sinh 1-5 ở `ability1/ability2`; hiệu ứng bộ dùng tới
201-304; phụ ma lưu theo tên; rèn 6-9 là bốn chỉ số phụ.

### U3. Công thức

Client không có công thức bạo kích, trúng/tránh, giảm thương hay nguyên tố; mọi số đều do
server gửi. Chỉ chiến lực có công thức: 5 chỉ số cơ bản nhân `combat_base` và hệ số kĩ năng,
8 chỉ số nguyên tố cộng 1:1 ngoài hệ số. Vì vậy các công thức chiến đấu là luật tự đặt, ghi
ở mục "Luật tự đặt" của tệp tiến độ.

### U4. Nộ khí

Thanh nộ là `ExtProgressTime` trần 100 (constructor native đặt `m_maxValue = 100`). Khung
`anger` `{src: 0|1, value}` đặt giá trị tuyệt đối; `skill_hero` đặt lại 0. Không có luật
tăng nộ trong client; `map_fight.enemy_rage`/`team_rage` đều 0 và không được đọc.

### U5. API kĩ năng đội trưởng

`leader_skill.open|train|set_skill|add_tree_point|wash_down|train_force`. `data` bắt buộc có
`available_skill`, `leader_skill`, `skill_point` (và `available_tree`). Giá học lấy từ
`leader_skill_develop.star_{cấp+1}`. Chỉ 12/96 dòng có `script` kèm tệp hiệu ứng; giao diện
chỉ có 4 nhánh đầu (cấp 0/10/20/30). Trận nhận 3 id ở `atk_skill`/`dfd_skill`, `atk_role`
là id `role_detail`.

### U6. Kĩ năng hoán đổi

`cards.select_skill_index` trả `data.skill[1..5]`. `cards.set_battle_skill` nhận
`card_id` + `skill_ids` là 3 số ô (client gửi kèm một `_` cuối). `avail` 0 khóa / 1 mở
nhưng không dùng / 2 đang dùng; chọn 3 ô đặt `avail` 2 cho 3 ô đó. Ô 4-5 thay thế chứ
không cộng lượt. `skill_num == 5` mới hiện nút đổi.
