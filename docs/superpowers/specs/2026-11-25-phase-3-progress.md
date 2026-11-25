# Tiến độ giai đoạn 3: chiến đấu đầy đủ

Cập nhật lần cuối: 2026-11-25.
Spec: `2026-11-25-phase-3-combat.md`.
Plan: `../plans/2026-11-25-phase-3-combat-plan.md`.

## Trạng thái chung

| Đợt | Trạng thái |
|---|---|
| 0. Công cụ đo và nghiên cứu U1-U6 | XONG |
| 3.1 Kĩ năng quái | XONG (spec, engine, mô phỏng, test) - chờ emulator |
| 3.2 Chỉ số phụ | XONG (engine, trang bị, chiến lực, test) - chờ emulator |
| 3.3 Kĩ năng hoán đổi | XONG (migration, handler, engine, test) - chờ emulator |
| 3.4 Kĩ năng đội trưởng | XONG (migration, handler, nộ khí, khung trận, test) - chờ emulator |
| G1-G2. Đá quý (kho, gắn, hợp thành, phân giải, tiến cấp) | XONG (store, handler, chỉ số vào trận, test) - chờ emulator |
| G3. Đá vận mệnh (`gem_fate.*`, huyết thạch) | CHƯA - cần spec nghiên cứu riêng |
| H. Thống soái | CHƯA - cần chủ dự án duyệt |

Bộ test: 275 test, tất cả xanh (`python3 -I -m unittest discover -s tests -t .`).

## Đợt 0: công cụ và số đo

### 0.1 Kiểm kê kĩ năng quái

`tools/audit_enemy_skills.py` (mới):

- duyệt 8384 trận campaign thường, 3317 công trình, 120 thành phố;
- 166 id kĩ năng quái khác nhau, 0 id thiếu trong `skill_detail.config`;
- 150 id mới cần spec; 16 id 4 chữ số (`110`, `330`, `410`, `710`, `820`, `1310`,
  `1420`, `1720`, `1830`, `2430`, `3820`, `3930`, `4020`, `4310`, `4720`, `5320`) đã có
  spec trong `data/skill_specs.json` vì chúng cũng là kĩ năng gốc của tướng;
- 44 id 900xx chiếm 87,8% lượt dùng; các id còn lại là 4xxxxx và ba id 600xx/800xx.

### 0.2 Đường cơ sở

`tools/simulate_campaign.py` (mới): đội mẫu cố định (5300, 100, 200, 300, 400) ở đúng cấp
của quái, tiến hóa tối đa, kĩ năng cấp 1, mỗi trận `random.Random(fight id)`.

| Mốc | Tỉ lệ thắng | 1xx | 2xx | Số khung trung vị | Thời gian |
|---|---|---|---|---|---|
| Trước 3.1 | 59,0% | 70,5% | 0,0% | 58 | 7,0 s |
| Sau 3.1 | 58,0% | 69,3% | 0,0% | 58 | 7,4 s |
| Sau 3.2 | 58,0% | 69,3% | 0,0% | 58 | 7,7 s |

- Thành phố 100-145 vẫn thắng 100% sau cả hai đợt: người chơi mới không bị chặn.
- Tụt mạnh nhất ở cuối chương thường: 169 từ 76,4% xuống 49,4%, 168 từ 95,7% xuống 86,0%.
- 2xx vốn đã 0% ở đường cơ sở vì quái ở đó mạnh hơn hẳn đội mẫu thuần chỉ số gốc; đây là
  giới hạn của đội mẫu, không phải hồi quy.
- 8384 trận chạy xong không lỗi, không vòng lặp vô hạn, trung bình dưới 1 ms/trận.

### 0.3 U2/U3: bảng id thuộc tính và công thức

Nguồn: `game_config.lua` `PUBLIC_ABILITY_TABLE` / `PUBLIC_ABILITY_NAME_TABLE` (bản gốc ở
`decompiled/lua`, không phải bản `game_pop/` cũ).

| id | Chỉ số | Ghi chú |
|---|---|---|
| 1-5 | `patk`, `matk`, `def`, `speed`, `hp` | trang bị chỉ dùng 1-5 |
| 6-9 | `crit`, `hr` (chính xác), `subhurt` (giảm thương), `dr` (né) | phần trăm, điểm |
| 101-105 | phần trăm của 1-5 | chỉ Ngọc Linh Hồn dùng |
| 201-204 | `fire`, `water`, `wind`, `earth` | sát thương nguyên tố |
| 301-304 | `fire_dfs`, `water_dfs`, `wind_dfs`, `earth_dfs` | phòng nguyên tố |

- `suit.config` `effect_2/3/4` dùng cả 1-5 và 201-304; server trước đây bỏ 201-304.
- `atts` (phụ ma) lưu theo **tên** (`fire`..`earth_dfs`).
- `bind_data` (vận mệnh) chỉ có khóa 1-5, giá trị là phần trăm.
- Rèn (`equip_set_random.sort` 6-9) là `crit/hr/subhurt/dr`; giá trị là số thực phần trăm
  (0,9 = 0,9%).
- Client **không** có công thức bạo kích, chính xác/né, giảm thương hay nguyên tố: nó chỉ
  phát lại số server gửi. Vì vậy các luật dưới đây là luật của server, ghi cờ.
- Chiến lực: `getCombatValue` cộng 8 chỉ số nguyên tố 1:1 **ngoài** hệ số kĩ năng
  (`COMBAT_ABILITY_TABLE.card`); bạo kích/chính xác/né/giảm thương không vào chiến lực.

### 0.4 U4/U5/U6: kĩ năng đội trưởng và hoán đổi

- `leader_skill.open|train|set_skill|add_tree_point|wash_down|train_force` (URL đã có).
  `data` phải có `available_skill` (id -> cấp), `leader_skill` (`skill_1..3`), `skill_point`
  (`{"1":[a,b],...}`), `available_tree`. Thiếu một khóa là lỗi Lua.
- `leader_skill_develop.config[skill].star_{1..5}` là giá; `leader_skill.config.max_level`,
  `cd`, `ready_time`, `script` (tệp `skill_effect/leader_skill/<script>.lua`), `icon`.
- Chỉ 12 trong 96 dòng có `script` kèm tệp hiệu ứng; 15 dòng có `script` nhưng thiếu tệp;
  69 dòng là nút thụ động (`script` rỗng).
- Giao diện chỉ vẽ 4 nhánh (cấp 0/10/20/30); nhánh 5-8 không có tab.
- Trận: `battle.init.atk_skill[1..3]` / `dfd_skill[1..3]` là id kĩ năng đội trưởng,
  `atk_role`/`dfd_role` là id `role_detail` (0 = ẩn thanh nộ). Khung `anger`
  `{src:0|1, value:0..100}` vẽ thanh nộ; khung `skill_hero`
  `{src, name, skillid, des, hurt}` phát kĩ năng; `value` là tuyệt đối, trần 100.
- `cards.select_skill_index` trả `data.skill[1..5]`; `set_battle_skill` nhận
  `card_id`, `skill_ids` = 3 số ô cách nhau bởi `_` (client luôn gửi thêm một `_` ở cuối).
  `avail`: 0 khóa, 1 mở nhưng không vào trận, 2 đang dùng. Chọn 3 ô = 3 ô `avail` 2.
- `skill_num == 5` mới hiện nút đổi; ô 4-5 là kĩ năng **thay thế** (chọn 3 trong 5), không
  cộng thêm lượt.

## Đợt 3.1: kĩ năng quái

- `data/enemy_skill_specs.json`: 150 spec, cùng schema `skill_spec.py`.
- `skills.py` tìm spec ở cả hai tệp; trùng khóa giữa hai tệp là lỗi khởi tạo.
- `campaign._defenders` gắn `skill1..3` của quái (`[id, cấp]`) và engine chạy như kĩ năng tướng.
- Mở rộng DSL: `effect100`/`attr100` (bảng ghi phần trăm x100), `effect+20`/`effect-20`
  (cộng trừ sau khi giải), `sure_hit`, `crit_bonus`, điều kiện `target_not_race`,
  `ally_has_race`, `ally_lacks_race`.
- Sát thương nguyên tố "own" lấy nguyên tố mạnh nhất của người đánh và trừ đúng phòng nguyên
  tố đó của đích (trước đây `element_dfs("own")` trả 0).
- Quái dùng attr của chính nó; `enemy_detail` nhiều dòng có nguyên tố 0 nên phần cộng thêm
  bằng 0, đúng dữ liệu.
- Không bao giờ gửi `pre_battle` cho quái.

## Đợt 3.2: chỉ số phụ

- `equipment.STAT_BY_ABILITY` mở rộng 6-9 và 201-304; `bonus()` trả thêm `crit`, `hit`,
  `subhurt`, `dodge` và 8 chỉ số nguyên tố từ hiệu ứng bộ, phụ ma (`atts`) và rèn 6-9.
- `equipment_forge` lưu đúng tên chỉ số cho rèn 6-9 (trước đây ghi nhầm thành `hp`).
- `progression.card_combat` cộng nguyên tố 1:1 ngoài hệ số kĩ năng, đúng `getCombatValue`.
- `battle`: `subhurt` giảm phần trăm sát thương cuối; `hit`/`dodge`/`crit` vẫn như trước;
  tướng lấy `crit/hr/dr` từ trang bị trên nền 10/100/0.
- `equipment.apply_fate` và `fate_percent` vẫn chỉ nhân 5 chỉ số cơ bản (đúng config).

## Đợt 3.3: kĩ năng hoán đổi

- Migration 6 (`battle_skill_slots`), lưu 3 ô đã chọn; mặc định 1_2_3.
- `progression.SKILL_SLOTS = 5`, `BATTLE_SKILLS = 3`; `card_document` gửi `s_1..s_5` cho
  tướng 5 kĩ năng, `avail` 2 cho 3 ô đang dùng, 1 cho ô còn lại; tướng 3 kĩ năng vẫn chỉ có
  `s_1..s_3`.
- Handler `cards.select_skill_index`, `cards.set_battle_skill`, `cards.unlock_skill`.
- Bỏ override `skill_num` 3 trong `config_overrides`; nút đổi hiện lại.
- `campaign._card_skills` chạy đúng các ô `avail == 2` (3 ô đã chọn).

## Đợt 3.4: kĩ năng đội trưởng

- `data/leader_skill_specs.json`: 12 kĩ năng có tệp hiệu ứng; `sahht_server/leader_skill.py`
  kiểm spec và dựng kĩ năng theo cấp.
- Migration 7 (`leader_skills`): cấp đã học và 3 ô đã gắn.
- Handler `leader_skill.open`, `.train` (giá `star_{cấp+1}`, `is_max=1` mua tới khi hết tiền),
  `.set_skill`. `add_tree_point`/`wash_down`/`train_force` để đóng (`error_not_open`).
- Engine: nộ khí 0-100; +10 khi đồng đội hành động, +5 khi đồng đội bị đánh; đủ 100 thì phát
  kĩ năng đầu tiên đã hết `ready_time`/`cd`, phát khung `skill_hero`, đặt lại nộ 0.
- `battle.init` gửi `atk_skill` (3 id), `dfd_skill` [0,0,0], `atk_role` 1, `dfd_role` 0.
- Mở module `leader_skill` và view 15 trong `scope_2018.json`.
- `STARTER_WALLET` thêm 1000 `star` vì vòng lặp ngày (giai đoạn 1) chưa có nguồn tinh tú.

## Nhánh G: đá quý (G1, G2)

Nghiên cứu (2026-11-25, đọc `game_data.lua`, `game_util.lua`, `gem_system_*`, `game_gem_advanced*`, `ui_gem_split`):

- `cards.open` gửi `gem` (khóa -> số lượng) và `gem_pos` ("0".."9" -> 4 khóa, "0" là ô trống).
  Khóa là `"<id gem.config>"` hoặc `"<cấp tiến cấp>-<id>"` cho đá đã tiến cấp.
  Đá cùng khóa là một chồng, không có thể hiện riêng.
- `gem_pos` được lưu cùng `cards.set_alignment` qua các trường `gem_1i`/`gem_2i` (như `equip_1i`); phản hồi gửi lại `gem_pos`.
  Ô 0 là đá tấn công (`career` 1), ô 1-3 là đá phòng thủ (`career` 2), theo `gemInGemPos`.
- Chỉ số đá (`getGemCombatValue`): `value + thưởng tiến cấp` cho `ability`, `value2 + thưởng 2` cho `ability2`; thưởng lấy từ dòng `gem_evolution[cấp].ability` có cùng id.
  Chỉ số cộng chung đường với trang bị (`gems.add_stats` trong `team_combat` và `campaign._attackers`), nên nguyên tố vào chiến lực 1:1 và vào trận.
- Phần thưởng loại 19 là `[19, id, số lượng]` (`Loot.gems`); toast dùng `reward.gem` (danh sách id lặp), cache dùng `gem._gem.update/remove`.
- `gem.synthesis`: `gem_num` lần, mỗi lần tốn `gem_num` đá `need_gem` (đá chưa tiến cấp trước, rồi tiến cấp thấp trước), `iron` kim khí và `need_item`.
- `gem.resolve` (`gems=<khóa>_<số lượng>` lặp): mỗi viên trả một lần tung đều trong `exchange` `[min, max]`, nhận dạng `metalcore` (nhãn "xilian" của màn).
- `gem.evolution`: tốn `gem_evolution[cấp kế].metal` và `gem_material`; thành công `rate`%, thất bại rơi về `false_back` và hoàn `gem_material_return`; `super_evo=1` tốn nhân `super_multiple` và luôn thành công.
  Phản hồi `success` ("true"/"false") và `got_gem` (khóa kết quả).
- Chỉ dùng đá chưa gắn: đá đang gắn không bị tiêu hao.
- `gem.upgrade` không làm: màn `gem_system_strengthen_scene` đọc `exp`, `lv_max`, `eaten_exp` mà đá của bản này không có (đá là chồng số lượng); server trả `error_not_open`.
- Scope: mở module `gem` (view 129, 130, 203); view 181 (đội hình thần giới) chuyển sang module `god_field` đang đóng; `gem_fate` vẫn đóng.

Luật tự đặt của nhánh G: `metalcore` là phần thưởng phân giải (dựa vào tên biến `metal_core_*` của màn); tiến cấp thường là tung `randrange(100) < rate`; tiến cấp "super" luôn thành công và tốn nhân đôi cả kim khí lẫn vật phẩm (client chỉ so vật phẩm với `cost_core * max_rate`); hoàn `gem_material_return` khi thất bại.
Đá tiến cấp không hoàn lại nguyên liệu khi phân giải.

Nguồn đá: phần thưởng loại 19 trong `box.config` (364 dòng) và các cấu hình sự kiện; `item.use` mở hộp đi qua `Loot`, nên đá rơi ra như mọi phần thưởng khác.
Nguyên liệu: vật phẩm 303 (Tinh Hoa Linh Hồn đặc cấp) cho hợp thành và 304 (TH-Hư Ảo) cho tiến cấp; server chưa có nguồn riêng cho hai vật phẩm này ngoài hộp và cửa hàng.

Test: `tests/test_gems.py` (22 test).

### G3: đá vận mệnh (chưa làm)

Đây là một hệ riêng (huyết thạch): 6 cấu hình `equip_gem_fate*` (30 đá, 40 kĩ năng, 120 dòng điểm hóa), các lệnh `gem_fate.synthesis_gem_fate`, `using_gem_fate`, `remove_gem_fate`, `empowering`, `printing`, `transfer`, và các khóa `gem_fate`, `_fate_word`, `_gem_special`, `_fate_stone`, `word_round` của `cards.open`.
Khoảng 2400 dòng giao diện (`game_upFateGem_main`, `game_bloodStone_*`, `game_select_bloodStone*_pop`) chưa đọc.
Cần spec nghiên cứu riêng trước khi cài.

## Luật tự đặt (ghi cờ để đổi một chỗ)

Tất cả nằm ở `battle.py` (chiến đấu), `equipment.py`/`progression.py` (chỉ số),
`leader_skill.py` (đội trưởng):

1. Bạo kích: `crit` phần trăm, sát thương x1,5. Client không có công thức.
2. Trúng/tránh: `max(5, hit - dodge)` phần trăm. Client không có công thức.
3. Giảm thương: `subhurt` trừ thẳng phần trăm sát thương cuối.
4. Sát thương nguyên tố: `điểm nguyên tố * scale% - phòng nguyên tố`, không đi qua phòng
   thường; đòn đánh thường **không** tự cộng nguyên tố (không tìm thấy luật gốc; mọi mô tả
   đều nói rõ "tạo thêm X% ST thuộc tính").
5. Nộ khí: +10 mỗi lượt đồng đội, +5 mỗi lần đồng đội bị đánh, trần 100.
6. Sát thương kĩ năng đội trưởng là `chỉ số tổng hợp * effect%`, không trừ phòng thường,
   có đi qua khiên/bất tử và `subhurt` của đích.
7. `pre_skill` của kĩ năng đội trưởng bị bỏ qua vì các nút điều kiện không có script hiệu
   ứng; chỉ 12 kĩ năng có tệp mới học được.
8. Ô kĩ năng 4-5 của tướng 5 kĩ năng mở sẵn (nguyên bản tốn 1888/2888 xu để mở).
9. `crit` nền của tướng là 10 và `hit` 100, vì `character_detail` không có cột nào.

## Còn lại

- Chạy emulator cho cả bốn đợt (3.1.6, 3.2.7, 3.3.5, 3.4.6): chơi ải đầu và cuối chương,
  mở màn đổi kĩ năng của tướng 5 kĩ năng, học/nâng cấp/gắn/phát kĩ năng đội trưởng.
- Cập nhật `server/README.md`, `server/SKILLS.md` và mục "Not done" của `CLAUDE.md`.
- G (đá quý) và H (thống soái): chờ chủ dự án duyệt.
