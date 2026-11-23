Lộ trình đề xuất (mỗi giai đoạn có spec và plan riêng)

Giai đoạn 0 - Phạm vi và cổng tính năng (làm trước tiên, mọi thứ sau dựa vào nó)

- Kiểm kê phạm vi, ghi thành server/data/scope\_2018.json: mỗi module API, view ID, thành phố, tướng được đánh dấu trong/ngoài phạm vi, kèm bằng chứng.

  Quy tắc: tướng ≤ 38700; thành phố có quái và drop chỉ dùng nội dung ≤ 2018; loại hết server\_\*, god\_field\*, cosmic, universe\_\*, cb\_\*, roulette, richman...

- Cổng tính năng: server gửi server\_inreview\_close và active\_switch theo bảng trên, nên nút ngoài phạm vi hoặc chưa làm sẽ biến mất.

- Lọc nội dung: gacha, shop và phần thưởng không cho ra tướng hay vật phẩm sau 2018.

- Nạp giả: bấm gói nạp là nhận kim cương và điểm VIP ngay; VIP, thẻ tháng, quà nạp lần đầu chạy theo config.

- Cơ chế migration cho SQLite, vì schema sẽ phình ra qua các giai đoạn.

Giai đoạn 1 - Vòng lặp hằng ngày: nhiệm vụ ngày và thành tựu, điểm danh, thư, bạn bè, các loại item.use còn lại, lượt gacha miễn phí, thanh "Điểm thu hồi".

Giai đoạn 2 - Trang bị: equip, equip\_pos, cường hóa, tiến giai, tinh luyện, tách, phụ ma, gacha trang bị, đá quý (cấp 40), Thống soái (606), tutorial đội 2.

Giai đoạn 3 - Chiến đấu đầy đủ: skill của quái (900xx), sát thương nguyên tố (từ trang bị), skill đội trưởng, skill hoán đổi của tướng 5 skill.

Giai đoạn 4 - PvE phụ: ải tinh anh (800), thử thách ngày (108), ải kinh nghiệm (105), thử thách cực hạn (109), sinh tồn (107), tranh tài nguyên (106), Vùng Đất Vô Chủ (110), Kho Báu Roger (114), các tháp trong phạm vi.

Giai đoạn 5 - Phát triển tướng sâu: Dung hợp (122), cây thiên phú (605), cải tạo thuộc tính (509), trùng sinh (117), chuyển sinh (112), hiến tế (115), phân giải (116), đột phá và thức tỉnh; pet, huy hiệu, huân chương, linh hồn nếu Giai đoạn 0 xác nhận chúng có trước 2019.

Giai đoạn 6 - Đấu trường và bang hội: đấu trường lấy đối thủ là người chơi thật trong DB, thiếu thì bù bot (chơi một mình vẫn đủ bảng, sau này mở rộng không phải viết lại); shop đấu trường và xếp hạng; bang hội (tạo, xin vào, quyên góp, shop, boss bang), bang chiến với bang bot.