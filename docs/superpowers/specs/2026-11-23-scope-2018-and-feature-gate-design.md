# Giai đoạn 0: phạm vi 2018 và cổng tính năng

Ngày: 2026-11-23.
Thuộc lộ trình: `2026-11-23-roadmap-2018.md`.

## Mục tiêu

Sau giai đoạn này, người chơi không bao giờ chạm vào một API stub.
Mỗi API client gọi rơi vào đúng một trong ba trường hợp: có handler thật, là API chạy ngầm được trả một thân rỗng đã kiểm chứng, hoặc bị đóng và client hiện popup "Tính năng chưa mở".
Nút của tính năng ngoài phạm vi hoặc chưa làm bị ẩn khỏi màn hình khi client cho phép.
Không có tướng sau 2018 nào lọt vào tay người chơi.
Nạp giả chạy được từ màn VIP.
Schema SQLite có cơ chế migration để các giai đoạn sau thêm bảng an toàn.

## Sự thật về client làm nền cho thiết kế

- `user.main_page` là phản hồi duy nhất thực sự mang cổng tính năng.
  `game_data.updateMainPageByJsonData` đọc `inreview` (danh sách view ID bị đóng; mỗi lần nhận, client xóa danh sách cũ rồi đặt lại) và `server_inreview_close` (cộng thêm vào cùng danh sách).
  `game_data.isViewOpenByID(id)` trả `false` cho mọi ID trong danh sách, và các nút dùng nó để ẩn mình.
- `active_switch` chỉ được đọc trong `game_data.responseGameData`, hàm này không được gọi ở đâu.
  Hệ quả: `isActiveOpenByID` luôn trả `false`, nên các nút sự kiện kiểu `active_inreview` (501-520) đã luôn ẩn; giai đoạn này không cần làm gì với chúng.
- Các nút mở theo cấp trong `button_open.config` (bang hội cấp 10, Dung hợp cấp 10, ...) không nhất thiết gắn với một view ID, nên không phải nút nào cũng ẩn được.
- Phản hồi có `status` khác `"0"` và có `msg` làm client hiện `game_error_pop` với nội dung `msg` và không gọi callback của màn hình (`shared/network.lua`, nhánh `else` cuối).
  Đây là lối thoát an toàn cho nút không ẩn được.
  Ngược lại, stub hiện tại trả `status 0` với `data` rỗng làm màn hình chạy tiếp và lỗi Lua vì thiếu trường.
- Bản Việt Nam không có cổng thanh toán.
  `native_helper.buyProduct` so `user_status.ticket` ("Vé vàng", 1 vé = 10.000 VND) với giá gói, hỏi xác nhận, rồi gọi `payment.use_ticket` với `cpOrderId = <orderid>_<số ngẫu nhiên>`.
  `orderid` do `ui_vip.lua` tạo theo dạng `<uid>_<server>_<index>_<time>_<channel>`, trong đó `index` là khóa của `charge.config` (22 gói).
  Sau khi mua, màn VIP gọi `shop.vip_buy_step` và đọc `data.step` (đếm số phần tử), `data.double_pay` (mảng ID gói đã nạp lần đầu), và tùy chọn `data.month_award`, `data.week_award`.
- `user_status.ticket` hiện lấy từ ví và bằng 0, nên bấm mua gói nạp chỉ hiện "Không đủ Vé vàng".
- `charge.config` có 22 gói; không gói nào có `is_double = 1`.
  Các gói "Túi Xu" (3-11) có `open_gift = 0` và chỉ cho xu cùng `vip_exp`; các gói còn lại (thẻ tháng, thẻ tuần, kế hoạch trưởng thành, thẻ mùa, đổi phiếu, ...) có `open_gift` khác 0 hoặc `is_show = 0` và mang phần thưởng riêng chưa có hệ thống nào xử lý.
- `vip.config` có các dòng `"0"` đến `"17"`; `need_exp` của dòng L là tổng kinh nghiệm tích lũy để lên L+1 (`ui_vip.lua` tính `need_more = need_exp - vipExp` và đọc dòng của cấp hiện tại không có nil guard).
- `box.config` có 441 tham chiếu tới tướng sau 2018, nhưng từ các nguồn server cấp (shop, thưởng ải, túi khởi đầu) chỉ đi tới được 11 hộp, và không hộp nào trong đó cho tướng sau 2018.
  `gacha.py` đã lọc tướng theo `skills.LAST_HERO_ID = 38700`.
- Mọi tướng người chơi nhận được, trừ bộ khởi đầu cố định (5300, 100, 200), đều đi qua `rewards.grant`.

## Thiết kế

### 1. Bảng phạm vi `server/data/scope_2018.json`

Một file JSON do người viết tay và review, là nguồn sự thật duy nhất về phạm vi.
Ví dụ minh họa cấu trúc (giá trị không phải dữ liệu thật):

```json
{
  "card_id_max": 38700,
  "city_order_max": null,
  "modules": {
    "private_city": {"phase": 0, "open": true},
    "equip":        {"phase": 2, "open": false},
    "arena":        {"phase": 6, "open": false},
    "god_field":    {"phase": null, "open": false, "reason": "liên server"}
  },
  "quiet": {
    "<module>.<method>": {"body": {"list": []}, "evidence": "lua/<file>.lua:<dòng>"}
  },
  "views": {
    "37": {"module": "arena"},
    "10": {"open": false, "reason": "nút sự kiện giới hạn thời gian"}
  }
}
```

- `modules`: mọi module API của client (phần trước dấu chấm trong `method`, khoảng 140 module) phải có mặt.
  `phase` là số giai đoạn sẽ làm, hoặc `null` nếu vĩnh viễn ngoài phạm vi.
  `open` được bật bằng tay khi một tính năng xong; module có `phase: null` không bao giờ được `open`.
- `quiet`: các API mà client tự gọi ngầm (không do người chơi bấm), kèm thân phản hồi rỗng đã đối chiếu với Lua và dòng Lua làm bằng chứng.
- `views`: mọi view ID trong `inreview.config` (133) và `server_inreview.config` (21) phải có mặt.
  Mỗi ID hoặc gắn với một module (`"module"`, mở khi module mở), hoặc là nút chỉ có giao diện, không gắn API nào, và được đặt mở/đóng trực tiếp (`"open"` kèm `"reason"`).
- `card_id_max` phải bằng `skills.LAST_HERO_ID`: bộ skill spec phủ đúng phạm vi tướng.
- `city_order_max`: thứ tự chiến dịch lớn nhất trong phạm vi (giá trị của `cityid_cityorderid.config`); `null` nghĩa là cả 160 thành phố đều trong phạm vi.

Quy tắc phân loại module:
- Ngoài phạm vi (`phase: null`): mọi module liên server (`server_*`, `god_field*`, `guild_high_war`, `cosmic_war`, `universe_*`, `servers_fight`, `world_one`), sự kiện nạp và quay thưởng (`cb_*`, các loại roulette, `super_rich`, `large_super_*`, `monopoly`, `richman`, `world_cup_*`, `redpacket`, ...), SDK bên thứ ba (`yunxin`), và mọi module chỉ phục vụ nội dung sau 2018.
- Trong phạm vi: các module ứng với các giai đoạn 1-6 của lộ trình.
- Module đã có handler (`user`, `cards`, `gacha`, `shop`, `item`, `private_city`, và `payment` sau giai đoạn này): `phase: 0, open: true`.

Việc đầu tiên của plan là sinh bản nháp của bảng này bằng công cụ kiểm kê (mục 6), rồi người dùng review bảng trước khi làm tiếp.

### 2. Module `sahht_server/scope.py`

Nạp `scope_2018.json` một lần, kiểm tra cấu trúc khi khởi động (thiếu trường hoặc sai kiểu thì server không khởi động), và cung cấp:

- `card_in_scope(c_id) -> bool`.
- `city_order_in_scope(order) -> bool`.
- `quiet_body(method) -> dict | None`.
- `closed_views() -> list[int]`: các view ID đang đóng (module của nó chưa mở, hoặc `"open": false`), sắp xếp tăng dần.
- `module_open(module) -> bool`.

Module này chỉ đọc dữ liệu phạm vi, không chứa luật game.

### 3. Chính sách điều phối API trong `app.py`

Thay nhánh stub hiện tại bằng thứ tự sau, cho các service `/api/`, `/pay/`, `/dataosha/`:

1. Có handler đăng ký: gọi handler như hiện nay.
2. Có trong `quiet`: trả `status 0` với thân đã ghi trong bảng, log `"quiet": true`.
3. Service `/dataosha/` (thống kê của client): trả `status 0` rỗng, log `"quiet": true`.
4. Còn lại: trả `{"status": "error_not_open", "msg": "Tính năng chưa mở.", "data": {}}`, log `"closed": true`.

Service `/login/` giữ nguyên: method lạ vẫn trả `refused`.
Trường `stub` biến mất khỏi log; một dòng `closed` sinh ra mà người chơi không bấm gì là dấu hiệu một API ngầm cần được đưa vào `quiet`.

### 4. Cổng tính năng trong `user.main_page`

`user_main_page` thêm `"inreview": scope.closed_views()` vào `data`.
Gửi toàn bộ danh sách mỗi lần, vì client xóa danh sách cũ khi nhận.
Các view của `server_inreview.config` nằm chung danh sách này; không gửi `server_inreview_close` riêng.
Nút mở theo cấp mà không gắn view ID nào thì vẫn hiện, và chạm vào sẽ ra popup ở mục 3 cho tới khi giai đoạn của nó xong.

### 5. Chặn nội dung sau 2018

- `rewards.grant` gọi `scope.card_in_scope` cho từng tướng và ném `Refused("error_scope", ...)` cho tướng ngoài phạm vi, làm cả giao dịch rollback.
  Đây là lưới an toàn cho lỗi dữ liệu; theo kiểm tra hiện tại nó không bao giờ kích hoạt.
- `gacha.py` lọc tướng bằng `scope.card_in_scope` thay cho `LAST_HERO_ID`, để phạm vi chỉ có một nguồn.
- Danh sách thành phố theo thứ tự chiến dịch (dùng cho cả bản đồ thế giới lẫn việc kiểm tra thành phố hợp lệ) bỏ các thành phố có `city_order_in_scope` sai.
- Một test đi từ mọi nguồn thưởng server cấp (hàng shop, thưởng ải, túi khởi đầu), lần theo vật phẩm hộp (`is_use = 1`, hộp là `use_effect[0]`) qua mọi tầng hộp lồng hộp, và khẳng định không đường nào dẫn tới tướng ngoài phạm vi.
  Test không quét phẳng cả `box.config`, vì các hộp không đi tới được có chứa tướng sau 2018.
- Giới hạn đã biết: màn đồ giám (`game_lllustrations_scene`) đọc thẳng `character_detail.config` của APK, nên vẫn liệt kê tướng sau 2018 ở trạng thái chưa sở hữu.
  Config phải giống hệt APK, nên giai đoạn này chấp nhận điều đó.

### 6. Công cụ kiểm kê `server/tools/audit_scope.py`

Chạy bằng `python3 -m tools.audit_scope`, chỉ đọc, in báo cáo:

- Mọi `method` trong `lua/game_url_config.lua`, gom theo module, đánh dấu: có handler, `quiet`, hay đóng.
- Module, view ID chưa có trong bảng phạm vi.
- Với mỗi view ID: tên trong `inreview.config` và các file Lua gọi `isViewOpenByID`/`isViewShowByID` với ID đó, để người review biết view ấy là nút nào.
- Danh sách nút mở theo cấp (`button_open.config`) cùng chữ khóa của chúng, làm checklist cho bước E2E 2 và 3.
  ID của nút và view ID là hai không gian số khác nhau, nên công cụ không cố ghép chúng; E2E là nơi kiểm nút nào ẩn được.
- Thành phố: thứ tự chiến dịch, ID, `open_level`, và mọi tướng mà thưởng của nó dẫn tới, để quyết định `city_order_max`.
- Chế độ `--draft` in ra một `scope_2018.json` nháp theo quy tắc ở mục 1, để người viết sửa tay chứ không tự ghi đè file thật.

### 7. Nạp giả

- `user_status` thêm `"ticket": FREE_TICKETS` (hằng số 9999; gói đắt nhất là 300 vé) và lấy `vip`, `vip_exp` từ dữ liệu thật thay cho `_FIXED_STATUS`.
  Vé không bao giờ bị trừ; đây là chỗ duy nhất định nghĩa "nạp miễn phí".
- `payment.use_ticket` (handler mới trong module `sahht_server/payment.py`):
  1. Tách `cpOrderId` theo dấu `_`; sai dạng thì trả `error_param`.
  2. `uid` trong mã phải bằng người chơi của phiên; khác thì trả `error_param`.
  3. `index` phải là khóa của `charge.config`; không thì trả `error_param`.
  4. Nếu `cpOrderId` đã có trong bảng `payments` thì trả thành công mà không cấp gì (client có thể gửi lại).
  5. Gói có `open_gift != 0` hoặc `is_show == 0` trả `error_not_open` với `msg` "Gói này chưa mở."; phần thưởng riêng của chúng thuộc Giai đoạn 1.
  6. Gói có `buy_times > 0` và người chơi đã mua đủ số lần thì trả lỗi với `msg` rõ ràng.
  7. Trong một giao dịch: cộng `coin + gift_coin` xu; nếu `is_double == 1` và đây là lần đầu nạp gói này thì cộng thêm `coin` (khớp chữ "Nạp tiền lần đầu tặng <coin> Xu" của client; config hiện không có gói nào như vậy, nhưng luật đi theo config); cộng `vip_exp` vào ví; ghi một dòng vào `payments`.
- Cấp VIP không lưu riêng mà tính từ `vip_exp`: số dòng của `vip.config` có `need_exp ≤ vip_exp`, chặn ở khóa lớn nhất (17) để màn VIP luôn đọc được dòng của cấp hiện tại.
- `shop.vip_buy_step` trả `{"step": [], "double_pay": [3, 5], "month_award": 0, "week_award": 0}`, với `double_pay` là danh sách số nguyên (tăng dần) các gói đã nạp ít nhất một lần, lấy từ bảng `payments`.
  Client duyệt nó bằng `for i=1,#temp` và so với ID gói kiểu số (`ui_vip.refreshTable`), nên đây phải là mảng số, không phải map.
  `step` (gói quà VIP đã mua) để rỗng cho tới giai đoạn làm shop VIP.

### 8. Migration SQLite

- `store.py` giữ một danh sách migration có thứ tự; migration 1 là `_SCHEMA` hiện tại (vẫn `IF NOT EXISTS`, nên DB đang dùng được coi là đã ở bản 1).
- Khi mở DB: đọc `PRAGMA user_version`, chạy từng migration còn thiếu trong một giao dịch, rồi cập nhật `user_version`.
- Migration 2 thêm bảng `payments(order_id TEXT PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES players(id), charge_id TEXT NOT NULL, created_at INTEGER NOT NULL)`.
  `vip_exp` lưu như một loại tiền trong `wallet` (khóa `(player_id, currency)`), không cần cột mới.
- DB mới hơn bản server biết (`user_version` lớn hơn số migration) làm server từ chối khởi động thay vì ghi đè.

## Xử lý lỗi

- Bảng phạm vi sai cấu trúc, module `phase: null` mà `open: true`, hay `quiet` thiếu `body`: server không khởi động và in rõ lý do.
- Tham số nạp sai: trả lỗi có `msg` tiếng Việt, client hiện popup, không cấp gì.
- Tướng ngoài phạm vi trong thưởng: rollback, trả lỗi, và ghi log để sửa dữ liệu.

## Kiểm thử

Unit và integration (trong `server/tests/`, viết trước khi cài đặt):

- Bảng phạm vi phủ đủ: mọi module trong `game_url_config.lua` và mọi view ID trong hai config inreview đều có mặt.
- Module có handler thì `open: true`; module `phase: null` thì không `open`; mọi `quiet` có `body` và `evidence`.
- Điều phối: method có handler, method `quiet`, method `/dataosha/`, method đóng trả đúng `status`, `msg` và đúng cờ log.
- `user.main_page` trả `inreview` bằng `closed_views()`.
- Không nguồn thưởng nào dẫn tới tướng có ID > 38700; `grant` một tướng ngoài phạm vi thì rollback.
- Nạp: lần đầu gói có `is_double` được nhân đôi, lần hai không (với config giả lập); cùng `cpOrderId` gửi hai lần chỉ cấp một lần; `uid` sai, `index` sai, `cpOrderId` sai dạng bị từ chối; gói có `open_gift` bị từ chối; VIP lên cấp đúng ngưỡng và dừng ở cấp tối đa; `buy_times` được tôn trọng; `vip_buy_step.double_pay` phản ánh các lần nạp.
- Migration: một DB tạo bằng schema cũ được nâng lên bản 2 và giữ nguyên dữ liệu; DB có `user_version` cao hơn bị từ chối.

E2E trên emulator (điều kiện xong của giai đoạn):

1. Gỡ app, cài lại, tạo tài khoản mới, đi hết tutorial đội 1 như trước (không hồi quy).
2. Màn chính: chụp màn hình; mọi nút đang hiện hoặc mở được màn hình chạy đúng, hoặc hiện popup "Tính năng chưa mở".
3. Ở cấp 10, chạm một nút mở theo cấp chưa làm (ví dụ bang hội): hiện popup, không lỗi Lua.
4. Màn VIP hiện 9999 Vé vàng; mua "Túi Xu 1100": xu tăng 1100, thanh VIP tăng 1100 và lên VIP 1; chạm "Thẻ tháng": hiện popup "Gói này chưa mở.".
5. Logcat không có `LUA ERROR`, `failed:`, `attempt to`.
6. `requests.jsonl` không có dòng `closed` nào mà người chơi không chủ động bấm.

Sau khi xong, cập nhật bảng "What works" trong `server/README.md` và phần Protocol của `CLAUDE.md` (cổng `inreview`, popup `error_not_open`, luồng Vé vàng).

## Ngoài phạm vi của giai đoạn này

- Các gói nạp có `open_gift` (thẻ tháng, thẻ tuần, kế hoạch trưởng thành, thẻ mùa, đổi phiếu), quà nạp tuần và tháng, shop VIP: Giai đoạn 1.
- Đặc quyền VIP trong từng tính năng (số lần mua stamina, auto-fight, ...): được dùng khi tính năng tương ứng được làm.
- Cài đặt bất kỳ module nào của Giai đoạn 1-6.

## Rủi ro

- Danh sách `quiet` có thể thiếu một API ngầm; dấu hiệu là dòng `closed` không do người chơi bấm trong E2E, và cách sửa là thêm nó vào `quiet` với thân đã đối chiếu Lua.
- Một view ID có thể điều khiển nhiều nút hoặc gắn sai module; công cụ kiểm kê liệt kê nơi dùng từng ID để review, và E2E bước 2 kiểm lại trên màn hình thật.
- Quy tắc nhân đôi lần đầu dựa trên chữ hiển thị của client và hiện không gói nào dùng tới; nếu sau này thấy một trường khác cho phần thưởng lần đầu thì dùng trường đó.
