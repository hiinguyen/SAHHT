# Giai đoạn 4: độ khó chiến dịch PvE

Ngày: 2026-11-25.
Mã: `server/sahht_server/difficulty.py`, kiểm thử `server/tests/test_difficulty.py`.

## Yêu cầu

Ải PvE phải khó hơn nhiều so với bản APK.
Các ải sau phải dùng tướng đời mới thay cho quái phổ thông (cảnh sát, zombie).
Các ải mốc (cấp 50, 60, 70, ...) phải khó hơn hẳn các ải xung quanh.

## Hiện trạng đo được

- Quái của 120 thành phố là quái phổ thông có tên và hoạt ảnh riêng (`jingcha`, `nanpingmin6`), không có tướng.
- Đội mẫu (5 tướng phẩm A, đúng cấp quái, tiến hóa tối đa) thắng 100% đến thành phố 145 và chỉ rớt từ chương 17.
- Boss có sẵn: `is_boss = 1` trong `enemy_detail` và `enemy_soldier_*`, nằm ở trận gắn nhãn "BOSS xuất hiện".

## Thiết kế

Mọi quái đi qua `campaign._enemy`, nên bản xem trước của client và trận của engine dùng cùng một quái đã tăng độ khó.
`Difficulty.harden(city, enemy_id, enemy)` là hàm duy nhất đổi quái.
Kết quả xác định theo `(thành phố, id quái)`: cùng một ô quái luôn là cùng một tướng.

- Năm thành phố đầu (`UNTOUCHED`, thứ tự 100-104) giữ nguyên: đó là màn hướng dẫn.
- Sức mạnh: `1 + 6,5 * (1 - exp(-3,5 * tiến độ))`, nhân `1 + 0,03 * số mốc đã qua`. Dốc ở đầu, phẳng ở cuối, vì quái cuối của APK vốn đã rất mạnh.
- Ải mốc: thành phố đầu tiên cần cấp 20, 30, ..., 120 (151, 161, 171, 180, ... ứng với cấp 50, 60, 70, 80). Nhân thêm 1,4 và thêm 30% ô quái thành tướng.
- Chỉ số: `hp` và `patk`/`matk` nhân theo sức mạnh, `def` nhân `sức mạnh^0,6`, `speed` tăng nhẹ, bạo kích và né cộng tối đa 25 điểm.
- Boss: `hp` x2,2, tấn công x1,25 (thêm x1,2 ở ải mốc), luôn là tướng từ thành phố thứ 8, rút từ đầu trên của dải đời tướng, kĩ năng cao hơn 3 cấp.
- Tướng thay quái: từ thành phố thứ 8, tỉ lệ ô quái thành tướng tăng đến 95% sau 55 thành phố.
  Dải đời tướng chạy theo tiến độ: tướng cũ ở đầu, tướng mới nhất (id <= 38700) ở cuối.
  Tướng lấy ngoại hình, tên, chủng tộc và ba kĩ năng gốc của chính nó (bậc tiến hóa theo tiến độ); chỉ số vẫn là của ô quái.
- Bể tướng: 160 tướng phẩm A và S, đã tiến hóa, không phải bản clone, có hoạt ảnh và spec kĩ năng mà engine chạy được.

## Đo bằng mô phỏng (`tools.simulate_campaign`, tỉ lệ thắng %)

Đội mạnh: 2300, 2200, 4100, 3600, 3300 (phẩm S, tiến hóa tối đa, đúng cấp quái, chưa có trang bị).
Đội yếu: 5300, 100, 200, 300, 400 (đội mẫu cũ).

| Thành phố | 110 | 120 | 127 (mốc) | 140 | 141 (mốc) | 150 | 151 (mốc) | 160 | 161 (mốc) |
|---|---|---|---|---|---|---|---|---|---|
| Đội yếu, APK gốc | 100 | 100 | 100 | 100 | 100 | 96 | 96 | 96 | 93 |
| Đội yếu, độ khó mới | 100 | 95 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| Đội mạnh, độ khó mới | 100 | 100 | 100 | 100 | 95 | 85 | 46 | 35 | 1 |

Đội mô phỏng không có trang bị, đá quý hay kĩ năng nâng cấp, nên từ thành phố 170 trở đi nó đã bất khả ngay từ bản APK.
Người chơi thật có trang bị và đá quý sẽ mạnh hơn: các hằng số đầu `difficulty.py` là chỗ chỉnh độ khó.

## Kiểm chứng trên emulator

Thành phố 171 (cấp 70, chương Úc): xem trước liệt kê chân dung tướng, trận chiến vẽ tướng đối thủ lv 74, logcat không có lỗi Lua.
