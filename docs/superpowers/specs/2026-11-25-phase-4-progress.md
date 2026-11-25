# Tiến độ giai đoạn 4: PvE phụ

Cập nhật lần cuối: 2026-11-25.
Độ khó chiến dịch: `2026-11-25-phase-4-difficulty.md`.
Bộ test: 312 test, tất cả xanh.

## Trạng thái

| Hạng mục | Trạng thái |
|---|---|
| Độ khó chiến dịch (tướng đời mới, ải mốc, boss) | XONG, đã xem trên emulator |
| Sảnh hoạt động `active.index` (hàng 40, 50, 60, 70, 80) | XONG, đã xem trên emulator |
| Cuộc chiến giành tài nguyên (nút 106) | XONG, đã đánh một trận trên emulator |
| Thử thách ngày (108), cực hạn (109), EXP (105) | XONG trong code và test, cùng engine với tài nguyên |
| Thử thách sinh tồn (107) | XONG trong code và test, chưa xem màn hình trên emulator |
| Ải tinh anh (800) | XONG, đã mở tab và đánh một trận trên emulator |
| Quét tự động của chiến dịch thường (`auto_recapture`, `auto_sweep_building`, `clear_sweep_log`) | CHƯA |
| Vùng Đất Vô Chủ (`public_land`, hàng 150, cấp 80) | CHƯA |
| Kho Báu Roger (`search_treasure`, nút 114) | CHƯA |
| Tháp (`pagoda`, `pyramid`, `maze`, `nightmare_tower`, `new_fight_forever`, `mine`, `mining`) | ĐỂ ĐÓNG, xem lí do bên dưới |

## Đã làm

- `sahht_server/active.py`: sảnh và bốn hoạt động theo chương.
  Mỗi hàng có đúng một chương "hôm nay" (thứ trong tuần chọn chương 100-160 và 200-230), vì sảnh đọc `index[chương]` không có nil guard.
  Lượt chạy bắt đầu ở bước 0 và tốn một lượt; lượt chạy dở sống qua nửa đêm; mua thêm lượt cần VIP; quét cần chiến lực bằng `combat_need`.
  Phần thưởng trả ở bước cuối: các dòng 3 phần tử chắc chắn, một lần quay trong các dòng 4 phần tử có trọng số, và cặp thưởng lần đầu.
- `sahht_server/survival.py`: bậc thang 150 cấp, ba lượt hồi sinh, đặt lại 09:00 và 21:00, "Đột tiến" tới `best - 10`.
- `sahht_server/elite.py`: một lượt đánh một thành phố (301-320, chấp nhận cả 401-420), ba lượt mỗi ngày và mua thêm bằng xu (`pay.16`), thưởng `jingyingfirst` lần đầu và `jingyingsweep` các lần sau.
  Tab mở bằng cấp người chơi qua `config_overrides` (`guide_team` 64).
  Client gửi `hard_open?city=301&chapter=201`, tức họ 3xx.
- `config_overrides.py`: ẩn các hàng sảnh chưa phục vụ (`is_see`), cắt bậc sinh tồn còn 150 cấp (151-200 không có trận), mở nút tinh anh.
- `campaign.py`: `run_battle` và `battle_exp` dùng chung; `_enemy_ids` bốc ứng viên có trọng số cho ô quái dạng `[[id, trọng số], ...]`.
- `store.py`: bảng `active_runs`, `elite_attempt`, `elite_cleared`, `elite_done` (hai migration mới).
- Phạm vi: module `active` mở (giai đoạn 4), view 6 (nút Hoạt động) mở.
- Quái hoạt động chưa qua `Difficulty`: giữ chỉ số của APK, vì `combat_need` của chúng theo thang gốc.
  Quái tinh anh có bậc riêng: thành phố thường cùng cấp, x1,6 sức mạnh, thêm 40% ô quái là tướng.

## Chưa làm và lí do

- Quét tự động chiến dịch thường: cần `sweep_log` toàn người chơi trong mọi `private_city.open` và ba handler.
  Nút bị chặn ở client bởi VIP và cấp (view 107, 111, cấp 35-45).
- Vùng Đất Vô Chủ: 13 phương thức dùng chung một tài liệu `public_land_data`, cần loại thưởng hạt giống (22), bảng DB mới và bot cho cướp/trộm.
  Mở được ở cấp 80, hoặc hạ `active.config` 150 và `farm_open` để thử.
- Kho Báu Roger: cần hai móc vào engine (máu khởi đầu thấp hơn tối đa, máu cuối từng quân) và mô hình máu chưa xác định; bản đồ lấy từ `map.config`.
- `pyramid` và `maze` chỉ vào được từ màn chính của sự kiện `open_door`, `nightmare_tower` và `new_fight_forever` cần ba đội "god field", `pagoda` là sự kiện nạp có ngày 2024-2026, `mine` và `mining` không có màn hình hoặc là sự kiện.
- `active.top` (bảng xếp hạng sinh tồn) và hàng sảnh 100 (Roger) đang ẩn.
- Xác minh trên emulator còn thiếu: màn sinh tồn, quét "Nhận nhanh", mua lượt, ải tinh anh đến lúc thành phố hoàn tất.
