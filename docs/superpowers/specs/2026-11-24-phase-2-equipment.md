# Giai đoạn 2: trang bị

Ngày: 2026-11-24.
Trạng thái: đợt 1, 2 (tiến hóa) và 3 (tinh luyện) đã xong; các đợt sau còn lại.
Tiến độ chi tiết: `2026-11-24-phase-2-progress.md`.
Phần còn lại được viết lại thành spec và plan cụ thể: `2026-11-25-phase-2-remaining-spec.md` và `../plans/2026-11-25-phase-2-remaining-plan.md` (đánh số lại thành đợt A-H, thay cho danh sách 1-8 bên dưới).

## Mục tiêu

Người chơi mới nhận trang bị, mặc vào đội hình, cường hóa, và thấy chiến lực tăng.
Tutorial đội 2 chạy được thay vì phải bỏ qua.

## Đợt 1 đã làm

- Bảng `equipment` và `equipment_positions`; mỗi đội hình có 10 vị trí, 4 ô trang bị.
- `cards.open` gửi `equip` và `equip_pos`; `cards.set_alignment` lưu cả đội hình lẫn trang bị.
- Trang bị cộng `value1/value2 + level_add1/2 * (lv - 1)` vào đúng thuộc tính của tướng.
  Công thức chiến lực và đơn vị trong trận dùng cùng một helper.
- `equip_gacha.get_all_gacha` / `get_gacha` theo `equip_gacha.config`, có chuỗi mở khóa,
  giới hạn lượt, trọng số và điểm pity.
- `factory.equip_levelup` và `equip.all_equip_levelup_auto` theo `equip_strongthen.config`;
  cấp tối đa = min(251, cấp người chơi).
- `equip.sell` bán trang bị trong túi lấy `sell_metal`; trang bị đang mặc bị từ chối.
- Tân thủ nhận một vũ khí 10101 để tutorial đội 2 có thứ để mặc và cường hóa.
- Mở module `equip`, `equip_gacha`, `factory`; chỉ mở view 22 (cường hóa).
  Các view tiến hóa/tinh luyện/tách/phụ ma/rèn/đúc/vận mệnh vẫn đóng.

## Các đợt tiếp theo

1. Tiến hóa: `equip.evolution`, `equip_evolution.config`, view 23. XONG (đợt 2).
2. Tinh luyện: `equip.st_levelup`, `equip_st.config`, view 24. XONG (đợt 3).
3. Tách: `equip.exchange`, `equip_exchange.config`, view 25.
4. Phụ ma và tẩy luyện: `equip.enchant`, `equip.save_init_enchant`, `equip.remove_enchant`,
   `equip.auto_enchant`, `equip.equip_refine`, `equip.auto_refine`, view 131/148.
5. Rèn, vận mệnh và đúc: `equip.equip_forge_*`, `equip.fate_equip_*`,
   `equip.equip_building_*`, view 167/182/193/208.
6. Xưởng: `factory.factory_all`, `factory.equip_make`, `factory.quick_make`,
   `factory.cancel_make`, `factory.completion_equip`, view 208.
7. Đá quý: `gem.*`, `gem_fate.*`, view 129/130/181/196/203/226.
8. Thống soái: `commander.*`, view 16.

## Giới hạn đã biết

- Bộ trang bị (suit), tinh luyện, rèn, phụ ma chưa được cộng vào chiến lực hay trận đấu.
- Chưa có giới hạn `equip_max` thật; `user_status.equip_max` vẫn là 100 cố định.
- Trang bị không bị khóa; bán là mất, không có hoàn tác.

## Kiểm chứng đợt 1

`python3 -I -m unittest discover -s tests -t .`: 167 test OK.
Smoke với config thật: tân thủ có 10101, cường hóa lên cấp 4, mặc vào vị trí 0,
chiến lực tăng, bán trang bị đang mặc bị từ chối.
