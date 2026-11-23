# Giai đoạn 0: phạm vi 2018 và cổng tính năng - kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Không API nào client gọi còn là stub: mỗi method có handler thật, là API ngầm được trả thân rỗng đã kiểm chứng, hoặc bị đóng bằng popup "Tính năng chưa mở"; nút ngoài phạm vi bị ẩn; không tướng sau 2018 nào được cấp; nạp giả chạy từ màn VIP.

**Architecture:** Một file dữ liệu `server/data/scope_2018.json` (do người review) là nguồn sự thật về phạm vi, được `sahht_server/scope.py` nạp và kiểm tra lúc khởi động rồi gắn vào `Services`.
Bộ điều phối trong `app.py` dùng nó để chọn handler, thân `quiet`, hoặc popup đóng; `user.main_page` gửi danh sách view bị đóng qua `inreview`; `rewards.grant`, `gacha.py` và danh sách thành phố dùng nó để chặn nội dung.
Nạp giả là module mới `payment.py` cùng bảng `payments`, được thêm qua cơ chế migration `PRAGMA user_version` mới của `store.py`.

**Tech Stack:** Python 3, chỉ thư viện chuẩn (`sqlite3`, `http.server`, `unittest`); client Lua đã giải mã trong `decompiled/lua`; emulator Android AVD `sahht`.

**Spec:** `docs/superpowers/specs/2026-11-23-scope-2018-and-feature-gate-design.md` (thuộc lộ trình `docs/superpowers/specs/2026-11-23-roadmap-2018.md`).

## Global Constraints

- Chỉ dùng thư viện chuẩn Python; không `pip install`.
- Không dùng ký tự gạch dài trong code, comment, chuỗi hay tài liệu; dùng dấu `-`.
- Trong file Markdown dài, mỗi câu một dòng.
- Không sửa `CHANGELOG.md` hay file tự sinh; không sửa APK gốc.
- Commit chỉ khi người dùng cho phép (CLAUDE.md của dự án); các bước "Commit" là điểm kiểm, bỏ qua nếu chưa được phép.
- Chạy toàn bộ test từ `server/`: `python3 -I -m unittest discover -s tests -t .` (không chạy `python3 -I -m unittest tests.x`, nó không import được package).
- Chạy một file test: `python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`.
- Chạy server không có `-I`: `python3 -m sahht_server.app --port 8080`.
- Chuỗi hiển thị cho người chơi bằng tiếng Việt; popup đóng có `msg` chính xác là `Tính năng chưa mở.`; gói nạp chưa mở có `msg` chính xác là `Gói này chưa mở.`.
- `card_id_max` = 38700 = `skills.LAST_HERO_ID`; `FREE_TICKETS` = 9999.
- Đọc file trích từ APK bằng `python3 -I`.
- Hook GateGuard có thể chặn lệnh Bash đầu tiên và lần Write/Edit đầu của mỗi file: nêu các sự thật nó hỏi rồi chạy lại đúng lệnh đó.
- Lúc bắt đầu, `python3 -I -m unittest discover -s tests -t .` cho `Ran 101 tests ... OK`; mọi task phải để toàn bộ test OK.

## Bản đồ file

| File | Trách nhiệm |
|---|---|
| `server/sahht_server/store.py` (sửa) | Migration theo `user_version`; bảng và method `payments`. |
| `server/sahht_server/scope.py` (mới) | Nạp, kiểm tra và truy vấn bảng phạm vi. Không chứa luật game. |
| `server/tools/audit_scope.py` (mới) | Kiểm kê client so với bảng phạm vi; sinh bản nháp; hàm đi theo phần thưởng dùng chung với test. |
| `server/data/scope_2018.json` (mới) | Bảng phạm vi đã review. |
| `server/sahht_server/handlers.py` (sửa) | `Services.scope`; `inreview` trong `user.main_page`. |
| `server/sahht_server/app.py` (sửa) | Chính sách điều phối handler / quiet / closed; log `quiet`/`closed`; nạp scope trong `build_server`. |
| `server/sahht_server/rewards.py`, `gacha.py`, `campaign.py` (sửa) | Chặn tướng và thành phố ngoài phạm vi. |
| `server/sahht_server/player.py` (sửa) | `FREE_TICKETS`, `vip_level`, `ticket`/`vip`/`vip_exp` trong `user_status`. |
| `server/sahht_server/payment.py` (mới) | `payment.use_ticket`, `shop.vip_buy_step`. |
| `server/tests/test_store.py`, `test_scope.py`, `test_payment.py` (mới); `test_flow.py`, `test_gameplay.py`, `test_campaign.py` (sửa) | Kiểm thử. |
| `server/README.md`, `CLAUDE.md` (sửa) | Tài liệu sau khi E2E qua. |

---

### Task 1: Migration SQLite và bảng `payments`

**Files:**
- Modify: `server/sahht_server/store.py` (sau khối `_SCHEMA` kết thúc ở dòng 100; `Store.__init__` dòng 107-115; thêm method cuối class)
- Create: `server/tests/test_store.py`

**Interfaces:**
- Consumes: không có.
- Produces:
  - `store.MIGRATIONS: tuple[str, ...]` (bản 1 là schema hiện tại, bản 2 thêm `payments`).
  - `Store.payment_exists(order_id: str) -> bool`
  - `Store.record_payment(uid: str, order_id: str, charge_id: str, now: int) -> None` (ném `sqlite3.IntegrityError` nếu `order_id` đã có)
  - `Store.payment_counts(uid: str) -> dict[str, int]` (charge_id -> số lần đã nạp)
  - `Store(...)` ném `RuntimeError` nếu `user_version` của DB lớn hơn `len(MIGRATIONS)`.

- [ ] **Step 1: Viết test thất bại**

Tạo `server/tests/test_store.py`:

```python
"""Schema migrations and the payments table."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sahht_server.store import MIGRATIONS, Store


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "game.db")

    def tearDown(self):
        self.tmp.cleanup()

    def version(self):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()

    def test_new_database_gets_every_migration(self):
        Store(self.path)
        self.assertEqual(self.version(), len(MIGRATIONS))
        db = sqlite3.connect(self.path)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        db.close()
        self.assertIn("payments", tables)

    def test_database_from_before_migrations_keeps_its_data(self):
        # Make a database the way the old server left it: schema 1 tables with data,
        # no payments table, user_version still 0.
        Store(self.path).create_account("old_player", "secret12")
        db = sqlite3.connect(self.path)
        db.execute("DROP TABLE payments")
        db.execute("PRAGMA user_version = 0")
        db.commit()
        db.close()
        store = Store(self.path)
        self.assertIsNotNone(store.player_for_account("old_player"))
        self.assertEqual(self.version(), len(MIGRATIONS))
        self.assertEqual(store.payment_counts(store.player_for_account("old_player")["uid"]), {})

    def test_database_newer_than_the_server_is_refused(self):
        db = sqlite3.connect(self.path)
        db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
        db.close()
        with self.assertRaises(RuntimeError):
            Store(self.path)


class PaymentStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.create_account("payer_one", "secret12")
        self.uid = self.store.player_for_account("payer_one")["uid"]

    def test_payments_are_counted_per_pack(self):
        self.assertFalse(self.store.payment_exists("order-a"))
        self.store.record_payment(self.uid, "order-a", "3", 100)
        self.store.record_payment(self.uid, "order-b", "3", 101)
        self.store.record_payment(self.uid, "order-c", "5", 102)
        self.assertTrue(self.store.payment_exists("order-a"))
        self.assertEqual(self.store.payment_counts(self.uid), {"3": 2, "5": 1})

    def test_an_order_id_is_recorded_once(self):
        self.store.record_payment(self.uid, "order-a", "3", 100)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_payment(self.uid, "order-a", "3", 101)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test để thấy nó thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_store.py'`
Expected: lỗi import `cannot import name 'MIGRATIONS' from 'sahht_server.store'`.

- [ ] **Step 3: Cài đặt migration**

Trong `server/sahht_server/store.py`, ngay sau khối `_SCHEMA = """..."""`, thêm:

```python
_PAYMENTS = """
CREATE TABLE IF NOT EXISTS payments (
    order_id   TEXT PRIMARY KEY,     -- the client's cpOrderId: a resend is not paid twice
    player_id  INTEGER NOT NULL REFERENCES players(id),
    charge_id  TEXT NOT NULL,        -- charge.config key
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_player ON payments(player_id, charge_id);
"""

# Applied in order; PRAGMA user_version is how many are applied. Migration 1 is the
# original schema (IF NOT EXISTS), so a database from before migrations is upgraded in
# place. Never edit an applied migration: append a new one.
MIGRATIONS = (_SCHEMA, _PAYMENTS)


def _statements(script: str) -> list[str]:
    """executescript() commits on its own, so migrations run statement by statement."""
    return [s.strip() for s in script.split(";") if s.strip()]
```

Thay thân `Store.__init__` bằng:

```python
    def __init__(self, db_path: str, ap_max: int = 120, ap_interval: int = 300):
        self.ap_max = ap_max
        self.ap_interval = ap_interval   # seconds per regenerated action point
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError(f"database schema {version} is newer than this server "
                                   f"({len(MIGRATIONS)}); refusing to open it")
            for number in range(version + 1, len(MIGRATIONS) + 1):
                with self.transaction():
                    for statement in _statements(MIGRATIONS[number - 1]):
                        self._db.execute(statement)
                    self._db.execute(f"PRAGMA user_version = {number}")
```

Cuối class `Store` (sau `set_building_steps`), thêm:

```python
    # ---- payments (free recharge) ------------------------------------------------

    def payment_exists(self, order_id: str) -> bool:
        return self._one("SELECT 1 FROM payments WHERE order_id = ?", (order_id,)) is not None

    def record_payment(self, uid: str, order_id: str, charge_id: str, now: int) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO payments(order_id, player_id, charge_id, created_at) VALUES (?, ?, ?, ?)",
                (order_id, _pid(uid), str(charge_id), now))

    def payment_counts(self, uid: str) -> dict:
        return {r["charge_id"]: r["n"] for r in self._all(
            "SELECT charge_id, COUNT(*) AS n FROM payments WHERE player_id = ? GROUP BY charge_id",
            (_pid(uid),))}
```

- [ ] **Step 4: Chạy test để thấy nó qua**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_store.py'`
Expected: `Ran 5 tests ... OK`.

- [ ] **Step 5: Chạy toàn bộ test (không hồi quy)**

Run: `cd server && python3 -I -m unittest discover -s tests -t .`
Expected: `OK`, không test nào lỗi.

- [ ] **Step 6: Kiểm DB thật được nâng cấp và giữ dữ liệu**

Run:
```bash
cd server
cp data/sahht.db build/sahht-before-migration.db
python3 -c "from sahht_server.store import Store; Store('data/sahht.db')"
python3 -I -c "import sqlite3; d=sqlite3.connect('data/sahht.db'); print(d.execute('PRAGMA user_version').fetchone()[0], d.execute('SELECT count(*) FROM accounts').fetchone()[0])"
python3 -I -c "import sqlite3; d=sqlite3.connect('build/sahht-before-migration.db'); print(d.execute('SELECT count(*) FROM accounts').fetchone()[0])"
```
Expected: dòng thứ nhất là `2 <n>`, dòng thứ hai là cùng `<n>`.

- [ ] **Step 7: Commit**

```bash
git add server/sahht_server/store.py server/tests/test_store.py
git commit -m "feat: schema migrations and the payments table"
```

---

### Task 2: Module `scope.py`

**Files:**
- Create: `server/sahht_server/scope.py`
- Create: `server/tests/test_scope.py` (phần unit; Task 3 và Task 5 thêm class)

**Interfaces:**
- Consumes: không có.
- Produces:
  - `scope.DEFAULT_PATH: Path` (`server/data/scope_2018.json`)
  - `scope.UNCLASSIFIED = "CHUA_PHAN_LOAI"` (dấu của mục nháp chưa review)
  - `scope.ScopeError(ValueError)`
  - `scope.Scope` (dataclass frozen) với trường `card_id_max: int`, `city_order_max: int | None`, `modules: dict`, `quiet: dict`, `views: dict[int, dict]`, và:
    - `Scope.load(path=DEFAULT_PATH) -> Scope`
    - `Scope.from_dict(raw: dict) -> Scope`
    - `card_in_scope(c_id) -> bool`
    - `city_order_in_scope(order) -> bool`
    - `quiet_body(method: str) -> dict | None` (bản sao, sửa không ảnh hưởng bảng)
    - `module_open(module: str) -> bool`
    - `closed_views() -> list[int]`

- [ ] **Step 1: Viết test thất bại**

Tạo `server/tests/test_scope.py`:

```python
"""The 2018 scope file: structure checks, queries, and the real file against the client."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from sahht_server.scope import Scope, ScopeError

VALID = {
    "card_id_max": 38700,
    "city_order_max": 3,
    "modules": {
        "cards": {"phase": 0, "open": True},
        "arena": {"phase": 6, "open": False},
        "god_field": {"phase": None, "open": False, "reason": "liên server"},
    },
    "quiet": {"notify.poll": {"body": {"list": []}, "evidence": "lua/game_ui/x.lua:10"}},
    "views": {
        "37": {"module": "arena"},
        "38": {"module": "cards"},
        "10": {"open": False, "reason": "nút sự kiện"},
        "11": {"open": True, "reason": "nút giao diện"},
    },
}


def with_change(change):
    raw = copy.deepcopy(VALID)
    change(raw)
    return raw


class ScopeQueryTests(unittest.TestCase):
    def setUp(self):
        self.scope = Scope.from_dict(VALID)

    def test_heroes_up_to_the_cutoff_are_in_scope(self):
        self.assertTrue(self.scope.card_in_scope(38700))
        self.assertTrue(self.scope.card_in_scope("100"))
        self.assertFalse(self.scope.card_in_scope(38800))

    def test_cities_up_to_the_cutoff_order_are_in_scope(self):
        self.assertTrue(self.scope.city_order_in_scope("3"))
        self.assertFalse(self.scope.city_order_in_scope(4))
        unlimited = Scope.from_dict(with_change(lambda r: r.update(city_order_max=None)))
        self.assertTrue(unlimited.city_order_in_scope(160))

    def test_closed_views_follow_their_module_or_their_own_flag(self):
        self.assertEqual(self.scope.closed_views(), [10, 37])

    def test_quiet_body_is_a_copy(self):
        body = self.scope.quiet_body("notify.poll")
        body["list"].append(1)
        self.assertEqual(self.scope.quiet_body("notify.poll"), {"list": []})
        self.assertIsNone(self.scope.quiet_body("arena.index"))

    def test_module_open(self):
        self.assertTrue(self.scope.module_open("cards"))
        self.assertFalse(self.scope.module_open("arena"))
        self.assertFalse(self.scope.module_open("no_such_module"))

    def test_load_reads_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scope.json"
            path.write_text(json.dumps(VALID), encoding="utf-8")
            self.assertEqual(Scope.load(path).closed_views(), [10, 37])


class ScopeValidationTests(unittest.TestCase):
    def assertRejected(self, change):
        with self.assertRaises(ScopeError):
            Scope.from_dict(with_change(change))

    def test_out_of_scope_module_cannot_be_open(self):
        self.assertRejected(lambda r: r["modules"]["god_field"].update(open=True))

    def test_module_needs_phase_and_open(self):
        self.assertRejected(lambda r: r["modules"]["arena"].pop("open"))
        self.assertRejected(lambda r: r["modules"]["arena"].update(phase="6"))

    def test_quiet_needs_body_and_evidence(self):
        self.assertRejected(lambda r: r["quiet"]["notify.poll"].pop("evidence"))
        self.assertRejected(lambda r: r["quiet"]["notify.poll"].update(body=[]))

    def test_view_needs_exactly_one_of_module_and_open(self):
        self.assertRejected(lambda r: r["views"]["37"].update(open=True))
        self.assertRejected(lambda r: r["views"].update({"39": {}}))

    def test_view_module_must_exist(self):
        self.assertRejected(lambda r: r["views"].update({"39": {"module": "nowhere"}}))

    def test_explicit_view_needs_a_reason(self):
        self.assertRejected(lambda r: r["views"]["10"].pop("reason"))

    def test_view_ids_are_numbers(self):
        self.assertRejected(lambda r: r["views"].update({"x": {"module": "cards"}}))

    def test_cutoffs_are_integers(self):
        self.assertRejected(lambda r: r.update(card_id_max="38700"))
        self.assertRejected(lambda r: r.update(card_id_max=True))
        self.assertRejected(lambda r: r.update(city_order_max=1.5))

    def test_missing_or_broken_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ScopeError):
                Scope.load(Path(tmp) / "missing.json")
            broken = Path(tmp) / "broken.json"
            broken.write_text("{", encoding="utf-8")
            with self.assertRaises(ScopeError):
                Scope.load(broken)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test để thấy nó thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`
Expected: `ModuleNotFoundError: No module named 'sahht_server.scope'`.

- [ ] **Step 3: Cài đặt `scope.py`**

Tạo `server/sahht_server/scope.py`:

```python
"""The 2018 content scope: which client modules, screens, heroes and cities this server serves.

Data only, read from data/scope_2018.json and checked once at startup. A module is the
part of an /api/ method before the dot. `open` is flipped by hand when a feature is done;
a module with `phase: null` is out of scope for good and can never be open.
"""

import copy
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "scope_2018.json"
UNCLASSIFIED = "CHUA_PHAN_LOAI"   # marks a draft entry nobody has reviewed yet


class ScopeError(ValueError):
    """The scope file is malformed; the server must not start with it."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScopeError(message)


def _check_module(name, entry) -> None:
    _require(isinstance(entry, dict), f"module {name}: must be an object")
    phase, is_open = entry.get("phase", "missing"), entry.get("open")
    _require(phase is None or _is_int(phase), f"module {name}: phase must be an integer or null")
    _require(isinstance(is_open, bool), f"module {name}: open must be true or false")
    _require(not (phase is None and is_open), f"module {name}: out of scope (phase null) but open")
    _require(isinstance(entry.get("reason", ""), str), f"module {name}: reason must be text")


def _check_quiet(method, entry) -> None:
    _require(isinstance(entry, dict), f"quiet {method}: must be an object")
    _require(isinstance(entry.get("body"), dict), f"quiet {method}: body must be an object")
    evidence = entry.get("evidence")
    _require(isinstance(evidence, str) and evidence.strip() != "", f"quiet {method}: evidence missing")


def _check_view(view, entry, modules) -> None:
    _require(view.isdigit(), f"view {view}: id must be a number")
    _require(isinstance(entry, dict), f"view {view}: must be an object")
    _require(("module" in entry) != ("open" in entry), f"view {view}: needs exactly one of module, open")
    if "module" in entry:
        _require(entry["module"] in modules, f"view {view}: unknown module {entry['module']}")
    else:
        _require(isinstance(entry["open"], bool), f"view {view}: open must be true or false")
        _require(isinstance(entry.get("reason"), str) and entry["reason"].strip() != "",
                 f"view {view}: a view not tied to a module needs a reason")
    _require(isinstance(entry.get("reason", ""), str), f"view {view}: reason must be text")


@dataclass(frozen=True)
class Scope:
    card_id_max: int
    city_order_max: int | None
    modules: dict
    quiet: dict
    views: dict          # view id (int) -> entry

    @classmethod
    def load(cls, path=DEFAULT_PATH) -> "Scope":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ScopeError(f"{path}: {exc}") from exc
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw) -> "Scope":
        _require(isinstance(raw, dict), "scope must be an object")
        card_max, city_max = raw.get("card_id_max"), raw.get("city_order_max", "missing")
        _require(_is_int(card_max), "card_id_max must be an integer")
        _require(city_max is None or _is_int(city_max), "city_order_max must be an integer or null")
        modules, quiet, views = raw.get("modules"), raw.get("quiet"), raw.get("views")
        for part, value in (("modules", modules), ("quiet", quiet), ("views", views)):
            _require(isinstance(value, dict), f"{part} must be an object")
        for name, entry in modules.items():
            _check_module(name, entry)
        for method, entry in quiet.items():
            _check_quiet(method, entry)
        for view, entry in views.items():
            _check_view(view, entry, modules)
        return cls(card_max, city_max, modules, quiet, {int(v): e for v, e in views.items()})

    def card_in_scope(self, c_id) -> bool:
        return int(c_id) <= self.card_id_max

    def city_order_in_scope(self, order) -> bool:
        return self.city_order_max is None or int(order) <= self.city_order_max

    def quiet_body(self, method: str) -> dict | None:
        entry = self.quiet.get(method)
        return None if entry is None else copy.deepcopy(entry["body"])

    def module_open(self, module: str) -> bool:
        return bool(self.modules.get(module, {}).get("open"))

    def closed_views(self) -> list:
        """Every view id the client must hide, for user.main_page's `inreview`."""
        def is_open(entry):
            return self.module_open(entry["module"]) if "module" in entry else entry["open"]
        return sorted(view for view, entry in self.views.items() if not is_open(entry))
```

- [ ] **Step 4: Chạy test để thấy nó qua**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`
Expected: `Ran 15 tests ... OK`.

- [ ] **Step 5: Commit**

```bash
git add server/sahht_server/scope.py server/tests/test_scope.py
git commit -m "feat: scope module for the 2018 content cut"
```

---

### Task 3: Công cụ kiểm kê và bảng phạm vi đã phân loại

**Files:**
- Create: `server/tools/audit_scope.py`
- Create: `server/data/scope_2018.json` (từ bản nháp, rồi phân loại tay)
- Modify: `server/tests/test_scope.py` (thêm import đầu file và class `ScopeFileTests` cuối file)

**Interfaces:**
- Consumes: `scope.Scope`, `scope.UNCLASSIFIED`, `scope.DEFAULT_PATH` (Task 2); `rewards.CARD`, `rewards.ITEM`; `shop.USE_BOX`; `skills.LAST_HERO_ID`; `app.SESSION_HANDLERS`.
- Produces (dùng ở Task 5 và Task 7):
  - `audit_scope.LUA_DIR`, `audit_scope.CONFIG_DIR: Path`
  - `audit_scope.load_config(name: str, config_dir=CONFIG_DIR) -> dict`
  - `audit_scope.url_keys(lua_dir=LUA_DIR) -> dict[str, tuple[str, str]]` (khóa URL -> (service, method))
  - `audit_scope.api_modules(keys) -> dict[str, set[str]]`
  - `audit_scope.view_configs(config_dir=CONFIG_DIR) -> dict[int, dict]`
  - `audit_scope.reward_triples(value) -> Iterator[list]`
  - `audit_scope.server_reward_sources(config) -> list[list]` (`config` là hàm `name -> dict`)
  - `audit_scope.reachable_cards(triples, items: dict, boxes: dict) -> set[int]`
  - `data/scope_2018.json` hợp lệ, không còn mục `CHUA_PHAN_LOAI`.

- [ ] **Step 1: Viết test thất bại cho dữ liệu thật**

Trong `server/tests/test_scope.py`, thay dòng `from sahht_server.scope import Scope, ScopeError` bằng:

```python
from sahht_server.scope import DEFAULT_PATH, UNCLASSIFIED, Scope, ScopeError
from sahht_server.skills import LAST_HERO_ID
from tools import audit_scope
```

Thêm class này ngay trước khối `if __name__ == "__main__":`:

```python
class ScopeFileTests(unittest.TestCase):
    """The real data/scope_2018.json against the real client."""

    @classmethod
    def setUpClass(cls):
        cls.scope = Scope.load(DEFAULT_PATH)
        cls.raw = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        cls.modules = audit_scope.api_modules(audit_scope.url_keys())

    def test_every_client_module_is_classified(self):
        self.assertEqual(sorted(set(self.modules) - set(self.scope.modules)), [])

    def test_every_view_id_is_classified(self):
        self.assertEqual(sorted(set(audit_scope.view_configs()) - set(self.scope.views)), [])

    def test_nothing_is_left_unreviewed(self):
        entries = [*self.raw["modules"].items(), *self.raw["views"].items(), *self.raw["quiet"].items()]
        left = [key for key, entry in entries if UNCLASSIFIED in json.dumps(entry, ensure_ascii=False)]
        self.assertEqual(left, [])

    def test_every_module_with_a_handler_is_open(self):
        from sahht_server.app import SESSION_HANDLERS
        handled = {method.split(".", 1)[0] for service, method in SESSION_HANDLERS if service == "api"}
        self.assertEqual(sorted(m for m in handled if not self.scope.module_open(m)), [])

    def test_hero_cut_matches_the_skill_specs(self):
        self.assertEqual(self.scope.card_id_max, LAST_HERO_ID)
```

- [ ] **Step 2: Chạy test để thấy nó thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`
Expected: `ImportError: cannot import name 'audit_scope' from 'tools'`.

- [ ] **Step 3: Viết `tools/audit_scope.py`**

Tạo `server/tools/audit_scope.py`:

```python
"""Inventory of what the client can call and show, checked against data/scope_2018.json.

    python3 -m tools.audit_scope            # report
    python3 -m tools.audit_scope --draft    # print a draft scope file to stdout

Read-only: it reads the decrypted Lua, the APK configs and the scope file. The draft is
printed, never written over the real file; every guess in it carries scope.UNCLASSIFIED
until a person has checked it.
"""

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from sahht_server.rewards import CARD, ITEM
from sahht_server.scope import DEFAULT_PATH, UNCLASSIFIED
from sahht_server.shop import USE_BOX
from sahht_server.skills import LAST_HERO_ID

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT.parent / "decompiled" / "lua"
CONFIG_DIR = ROOT.parent / "decompiled" / "apk" / "assets" / "config"
URL_RE = re.compile(r'(\w+)\s*=\s*"/(\w+)/\?method=([\w.]+)"')
VIEW_RE = re.compile(r"isView(?:Open|Show)ByID\(\s*(\d+)\s*\)")
URL_KEY_RE = re.compile(r'getUrlForKey\(\s*"(\w+)"\s*\)')
WINDOW = 30   # lines around a view check searched for the API calls that screen makes

OPEN_NOW = {"user", "cards", "gacha", "shop", "item", "private_city", "payment"}
OUT_PREFIXES = ("server_", "god_field", "guild_high_war", "cosmic", "universe_", "cb_",
                "world_cup", "large_super", "super_rich", "roulette", "new_roulette",
                "large_roulette", "diamond_wheel", "redpacket", "red_bag")
OUT_MODULES = {"yunxin", "servers_fight", "world_one", "monopoly", "super_tycoon_active",
               "super_luck", "luck_lottery", "jigsaw", "fire_chess", "idol_festival"}
OUT_REASON = "ngoài phạm vi 2018: liên server, sự kiện nạp/quay thưởng hoặc SDK"
# The roadmap's guess per phase; each one still needs checking against its screen.
PHASE_GUESS = {
    1: {"reward", "daily_award", "notify", "friend", "vip", "vip_reward", "pay_award",
        "recharge_package", "gift"},
    2: {"equip", "factory", "equip_gacha", "gem", "commander"},
    3: {"leader_skill"},
    4: {"pyramid", "maze", "nightmare_tower", "search_treasure", "public_land", "mine", "mining"},
    5: {"card_develop", "talent_skill", "sacrifice", "soul", "pets", "badge", "medal"},
    6: {"arena", "association", "guild_gvg", "team_boss"},
}


def load_config(name: str, config_dir=CONFIG_DIR) -> dict:
    path = Path(config_dir) / f"{name}.config"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def url_keys(lua_dir=LUA_DIR) -> dict:
    """game_url_config.lua: key -> (service, method)."""
    text = (Path(lua_dir) / "game_url_config.lua").read_text(encoding="utf-8", errors="replace")
    return {key: (service, method) for key, service, method in URL_RE.findall(text)}


def api_modules(keys: dict) -> dict:
    """/api/ methods grouped by module (the part before the dot)."""
    modules = collections.defaultdict(set)
    for service, method in keys.values():
        if service == "api" and "." in method:
            modules[method.split(".", 1)[0]].add(method)
    return dict(modules)


def view_configs(config_dir=CONFIG_DIR) -> dict:
    views = {}
    for name in ("inreview", "server_inreview"):
        for key, row in load_config(name, config_dir).items():
            views[int(key)] = {"config": name, "name": row.get("name", ""), "story": row.get("story", "")}
    return views


def view_refs(lua_dir=LUA_DIR) -> dict:
    """view id -> [(file, line, url keys used within WINDOW lines)]."""
    refs = collections.defaultdict(list)
    for path in sorted(Path(lua_dir).rglob("*.lua")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, 1):
            for view in VIEW_RE.findall(line):
                window = "\n".join(lines[max(0, number - 1 - WINDOW):number + WINDOW])
                refs[int(view)].append((str(path.relative_to(lua_dir)), number,
                                        URL_KEY_RE.findall(window)))
    return dict(refs)


def reward_triples(value):
    """Every `[type, id, count, ...]` list inside a config value."""
    if isinstance(value, list):
        head = value[:3]
        if len(head) == 3 and all(isinstance(v, int) and not isinstance(v, bool) for v in head):
            yield value
        else:
            for part in value:
                yield from reward_triples(part)
    elif isinstance(value, dict):
        for part in value.values():
            yield from reward_triples(part)


def server_reward_sources(config) -> list:
    """Every reward this server hands out from configs: shop goods, campaign building
    rewards, the starting bag. `config` maps a config name to its dict."""
    triples = []
    for row in config("shop").values():
        triples += list(reward_triples(row.get("shop_reward", [])))
    for row in config("map_title_detail").values():
        for key, value in row.items():
            if key.startswith("reward_"):
                triples += list(reward_triples(value))
    for row in config("role_detail").values():
        triples += [[ITEM, entry[0], entry[1]] for entry in row.get("item", [])
                    if isinstance(entry, list) and len(entry) >= 2]
    return triples


def reachable_cards(triples, items: dict, boxes: dict) -> set:
    """Hero ids the rewards can lead to, opening box items (is_use 1, box = use_effect[0])
    through any depth of boxes inside boxes."""
    todo, seen_items, seen_boxes, cards = list(triples), set(), set(), set()
    while todo:
        kind, ref = todo.pop()[:2]
        if kind == CARD:
            cards.add(ref)
        elif kind == ITEM and ref not in seen_items:
            seen_items.add(ref)
            detail = items.get(str(ref), {})
            if detail.get("is_use") == USE_BOX:
                box = str((detail.get("use_effect") or [0])[0])
                if box in boxes and box not in seen_boxes:
                    seen_boxes.add(box)
                    todo.extend(reward_triples(boxes[box]))
    return cards


def _guess_module(refs: list, keys: dict) -> str | None:
    votes = collections.Counter()
    for _, _, near in refs:
        for key in near:
            service, method = keys.get(key, ("", ""))
            if service == "api" and "." in method:
                votes[method.split(".", 1)[0]] += 1
    return votes.most_common(1)[0][0] if votes else None


def draft_module(name: str) -> dict:
    if name in OPEN_NOW:
        return {"phase": 0, "open": True}
    if name.startswith(OUT_PREFIXES) or name in OUT_MODULES:
        return {"phase": None, "open": False, "reason": OUT_REASON}
    for phase, names in PHASE_GUESS.items():
        if name in names:
            return {"phase": phase, "open": False,
                    "reason": f"{UNCLASSIFIED}: gợi ý giai đoạn {phase} theo lộ trình"}
    return {"phase": None, "open": False, "reason": UNCLASSIFIED}


def draft_view(refs: list, keys: dict, modules: dict) -> dict:
    guess = _guess_module(refs, keys)
    where = ", ".join(f"{f}:{n}" for f, n, _ in refs[:2]) or "không nơi nào gọi"
    if guess in modules:
        return {"module": guess, "reason": f"{UNCLASSIFIED}: đoán từ {where}"}
    return {"open": False, "reason": f"{UNCLASSIFIED}: không thấy API gần {where}"}


def draft() -> dict:
    keys = url_keys()
    modules, refs = api_modules(keys), view_refs()
    return {
        "card_id_max": LAST_HERO_ID,
        "city_order_max": None,
        "modules": {m: draft_module(m) for m in sorted(modules)},
        "quiet": {},
        "views": {str(v): draft_view(refs.get(v, []), keys, modules) for v in sorted(view_configs())},
    }


def _city_lines(card_max: int) -> list:
    items, boxes = load_config("item"), load_config("box")
    order = load_config("cityid_cityorderid")
    stories = {str(r.get("stage_id")): r for r in load_config("map_main_story").values()}
    by_city = collections.defaultdict(list)
    for building, row in load_config("map_title_detail").items():
        if building.isdigit():
            for key, value in row.items():
                if key.startswith("reward_"):
                    by_city[str(int(building) // 1000)] += list(reward_triples(value))
    lines = []
    for city, number in sorted(order.items(), key=lambda kv: int(kv[1])):
        cards = reachable_cards(by_city.get(city, []), items, boxes)
        top = max(cards) if cards else "-"
        flag = "  > 2018" if cards and max(cards) > card_max else ""
        level = stories.get(city, {}).get("open_level", "?")
        lines.append(f"city order {number:>4} id {city:>4} open_level {level:>4} max hero {top}{flag}")
    return lines


def report(scope_path=DEFAULT_PATH) -> list:
    from sahht_server.app import SESSION_HANDLERS
    keys = url_keys()
    modules, views, refs = api_modules(keys), view_configs(), view_refs()
    path = Path(scope_path)
    scope = (json.loads(path.read_text(encoding="utf-8")) if path.is_file()
             else {"card_id_max": LAST_HERO_ID, "modules": {}, "views": {}, "quiet": {}})
    handled = {m for s, m in SESSION_HANDLERS if s == "api"}
    lines = ["== modules (handled/total, quiet)"]
    for module in sorted(modules):
        entry = scope["modules"].get(module)
        state = "MISSING" if entry is None else f"phase={entry.get('phase')} open={entry.get('open')}"
        done = sum(1 for m in modules[module] if m in handled)
        quiet = sum(1 for m in modules[module] if m in scope["quiet"])
        lines.append(f"{module:28} {state:22} {done}/{len(modules[module])} handled, {quiet} quiet")
    lines.append("== views")
    for view in sorted(views):
        entry = scope["views"].get(str(view))
        where = ", ".join(f"{f}:{n}" for f, n, _ in refs.get(view, [])[:3]) or "không nơi nào gọi"
        state = "MISSING" if entry is None else json.dumps(
            {k: v for k, v in entry.items() if k != "reason"}, ensure_ascii=False)
        lines.append(f"view {view:>5} {state:30} {views[view]['name']} | {views[view]['story']} | {where}")
    lines.append("== level-gated buttons (button_open.config): check each on the emulator")
    for button, text in sorted(load_config("button_open").items(), key=lambda kv: int(kv[0])):
        lines.append(f"button {button:>4} {text}")
    lines.append("== campaign cities")
    lines += _city_lines(scope["card_id_max"])
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draft", action="store_true", help="print a draft scope file to stdout")
    args = ap.parse_args()
    if args.draft:
        json.dump(draft(), sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        print("\n".join(report()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Sinh bản nháp và kiểm nó nạp được**

Run:
```bash
cd server
python3 -m tools.audit_scope --draft > build/scope_draft.json
cp build/scope_draft.json data/scope_2018.json
python3 -c "from sahht_server.scope import Scope; s=Scope.load(); print(len(s.modules), len(s.views), len(s.closed_views()))"
```
Expected: ba số, khoảng `140 154 <n>`; không có `ScopeError`.

- [ ] **Step 5: Chạy test, chỉ còn test "chưa review" thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`
Expected: chỉ `test_nothing_is_left_unreviewed` FAIL, liệt kê các khóa còn `CHUA_PHAN_LOAI`.

- [ ] **Step 6: Phân loại từng module còn `CHUA_PHAN_LOAI`**

Với mỗi module có `CHUA_PHAN_LOAI` trong `data/scope_2018.json`:
1. Lấy các khóa URL của nó: `grep -n '"/api/?method=<module>\.' ../decompiled/lua/game_url_config.lua`.
2. Tìm màn hình dùng các khóa đó: `grep -rln '<khóa>' ../decompiled/lua/game_ui ../decompiled/lua/game_pop`.
3. Đọc chú thích của khóa URL và tên màn để biết đó là tính năng gì.
4. Quyết định theo quy tắc của spec mục 1: liên server, sự kiện nạp/quay thưởng, hoặc chỉ phục vụ nội dung sau 2018 thì `"phase": null`; tính năng cốt lõi thì gán giai đoạn 1-6 theo bảng trong lộ trình.
5. Thay `"reason"` bằng mô tả tiếng Việt kèm bằng chứng, ví dụ `"Đấu trường: game_ui/game_arena.lua; lộ trình giai đoạn 6"`.

Không đổi `open` của module nào; chỉ các module trong `OPEN_NOW` được `open: true`.

- [ ] **Step 7: Phân loại từng view còn `CHUA_PHAN_LOAI`**

Chạy `python3 -m tools.audit_scope | grep '^view'` để thấy tên, story và nơi gọi; mở dòng Lua đó và xác định nút nó điều khiển.
- Nút mở một màn hình dùng API: `{"module": "<module>", "reason": "<nút gì>, <file:dòng>"}`.
- Nút không gắn API nào: `{"open": true|false, "reason": "<nút gì>, <file:dòng>"}`; chỉ để `true` khi nút đó hoạt động được mà không cần API nào ngoài các module đang mở.
- View không nơi nào gọi: `{"open": false, "reason": "không nơi nào trong Lua gọi view này"}`.

- [ ] **Step 8: Quyết định `city_order_max`**

Run: `cd server && python3 -m tools.audit_scope | grep '^city'`
Nếu không dòng nào có `> 2018`, giữ `"city_order_max": null`.
Nếu có, đặt `city_order_max` bằng thứ tự ngay trước thành phố đầu tiên có `> 2018`, và nêu lý do trong báo cáo ở Step 10.

- [ ] **Step 9: Chạy test để thấy nó qua**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`
Expected: `Ran 20 tests ... OK`.

- [ ] **Step 10: CỔNG REVIEW: dừng lại cho người dùng duyệt bảng phạm vi**

Gửi người dùng:
- Số module theo từng giai đoạn, và danh sách module `phase: null` kèm lý do.
- Các view sẽ bị đóng (`python3 -c "from sahht_server.scope import Scope; print(Scope.load().closed_views())"`) kèm tên trong `inreview.config`.
- Quyết định `city_order_max`.
Không làm Task 4 trở đi cho tới khi người dùng đồng ý; sửa bảng theo góp ý rồi chạy lại Step 9.

- [ ] **Step 11: Commit**

```bash
git add server/tools/audit_scope.py server/data/scope_2018.json server/tests/test_scope.py
git commit -m "feat: 2018 scope table and the audit tool that checks it"
```

---

### Task 4: Nạp scope vào server, chính sách điều phối, và cổng `inreview`

**Files:**
- Modify: `server/sahht_server/handlers.py` (import; `Services` dòng 64-70; `user_main_page` dòng 291-301)
- Modify: `server/sahht_server/app.py` (import, hằng số, `RequestLog.write`, `_route`, `_dispatch`, hàm mới `_resolve`/`_closed`, `build_server`, `main`)
- Modify: `server/tests/test_flow.py` (`ServerCase.setUp`; thay `test_unknown_api_method_gets_empty_success_and_is_logged`; thêm test)

**Interfaces:**
- Consumes: `scope.Scope`, `scope.DEFAULT_PATH` (Task 2); `data/scope_2018.json` (Task 3).
- Produces:
  - `Services.scope: Scope` (trường mới, đứng cuối).
  - `build_server(host, port, db_path, config_dir, version_map_path, request_log, scope_path=None)`; `None` nghĩa là `scope.DEFAULT_PATH`.
  - `ServerCase.scope_path(self) -> Path | None` (test ghi đè để nạp scope riêng; `self.tmp` đã tồn tại khi nó được gọi).
  - Log JSONL: mỗi dòng có `service`, `method`, `params`, thêm `"quiet": true` hoặc `"closed": true` khi đúng trường hợp; không còn trường `stub`.
  - Phản hồi đóng: `{"status": "error_not_open", "msg": "Tính năng chưa mở.", "data": {}, "user_status": {...}}`.

- [ ] **Step 1: Viết test thất bại**

Trong `server/tests/test_flow.py`, thay `ServerCase.setUp` (giữ nguyên `tearDown` và các helper khác):

```python
class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tmp.name) / "config"
        self.config_dir.mkdir()
        for name, content in FIXTURE_CONFIGS.items():
            (self.config_dir / f"{name}.config").write_text(json.dumps(content))
        self.log_path = Path(self.tmp.name) / "requests.jsonl"
        self.server = build_server(
            host="127.0.0.1",
            port=0,
            db_path=":memory:",
            config_dir=self.config_dir,
            version_map_path=ROOT / "data" / "game_config_version.json",
            request_log=self.log_path,
            scope_path=self.scope_path(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def scope_path(self):
        """The scope file the server loads (None: data/scope_2018.json). self.tmp exists here."""
        return None
```

Trong `GameApiTests`, thay toàn bộ `test_unknown_api_method_gets_empty_success_and_is_logged` bằng:

```python
    def log_lines(self, method):
        return [l for l in map(json.loads, self.log_path.read_text().splitlines())
                if l.get("method") == method]

    def test_unimplemented_api_method_is_closed_with_a_popup_and_logged(self):
        _, body = self.api("arena.battle", self.rans, self.uid, foo="1")
        self.assertEqual(body["status"], "error_not_open")
        self.assertEqual(body["msg"], "Tính năng chưa mở.")
        self.assertIn("user_status", body)
        [line] = self.log_lines("arena.battle")
        self.assertTrue(line["closed"])
        self.assertNotIn("stub", line)
        self.assertEqual(line["params"]["foo"], "1")

    def test_client_analytics_are_answered_quietly(self):
        _, body = self.get(f"{BASE}/dataosha/", method="rank", rans=self.rans, user_token=self.uid)
        self.assertEqual((body["status"], body["data"]), (0, {}))
        [line] = self.log_lines("rank")
        self.assertTrue(line["quiet"])

    def test_implemented_method_is_logged_without_flags(self):
        self.api("cards.open", self.rans, self.uid)
        [line] = self.log_lines("cards.open")
        self.assertNotIn("quiet", line)
        self.assertNotIn("closed", line)

    def test_main_page_hides_every_closed_view(self):
        _, body = self.api("user.main_page", self.rans, self.uid)
        closed = body["data"]["inreview"]
        self.assertEqual(closed, self.server.services.scope.closed_views())
        self.assertEqual(closed, sorted(closed))
        self.assertTrue(all(isinstance(v, int) for v in closed))
```

Thêm class mới ở cuối `server/tests/test_flow.py` (trước `if __name__` nếu có):

```python
class QuietMethodTests(ServerCase):
    """A background call listed in the scope's `quiet` gets its recorded empty body."""

    def scope_path(self):
        from sahht_server.scope import DEFAULT_PATH
        raw = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        raw["quiet"]["arena.poll_test"] = {"body": {"list": []}, "evidence": "test"}
        path = Path(self.tmp.name) / "scope.json"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return path

    def test_quiet_method_gets_its_body(self):
        data = self.register()
        _, body = self.api("arena.poll_test", data["rand_str"], data["uid"])
        self.assertEqual((body["status"], body["data"]), (0, {"list": []}))
        lines = [json.loads(l) for l in self.log_path.read_text().splitlines()]
        [line] = [l for l in lines if l["method"] == "arena.poll_test"]
        self.assertTrue(line["quiet"])
```

- [ ] **Step 2: Chạy test để thấy nó thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_flow.py'`
Expected: `TypeError: build_server() got an unexpected keyword argument 'scope_path'`.

- [ ] **Step 3: Thêm `scope` vào `Services` và `inreview` vào `user.main_page`**

Trong `server/sahht_server/handlers.py`, thêm cạnh các import nội bộ (`from .player import ...`, `from .store import ...`):

```python
from .scope import Scope
```

Đổi `Services` thành:

```python
@dataclass(frozen=True)
class Services:
    store: Store
    config_dir: Path
    version_map: dict
    all_config_version: str
    configs: ConfigCache
    scope: Scope
```

Trong `user_main_page`, thêm vào dict của `ok(...)`, ngay sau dòng `"config_refresh": 0,`:

```python
        # Every view id the client must hide. game_data.updateInreviewByJsonData resets
        # its list on each reply, so the whole list goes every time.
        "inreview": svc.scope.closed_views(),
```

- [ ] **Step 4: Chính sách điều phối và log trong `app.py`**

Trong `server/sahht_server/app.py`:

Thêm import (cạnh `from .store import Store`):

```python
from . import scope as scope_module
from .scope import Scope
```

Thêm hằng số dưới `SESSION_SERVICES`:

```python
QUIET_SERVICES = {"dataosha"}   # the client's own analytics: answered, never shown
CLOSED_MSG = "Tính năng chưa mở."
```

Thay `RequestLog.write`:

```python
    def write(self, service, method, params, flag=None):
        """`flag` is "quiet" or "closed" for methods with no handler: the work still to do."""
        if self._path is None:
            return
        safe = {k: "<redacted>" if k in REDACTED_PARAMS else v for k, v in params.items()}
        record = {"service": service, "method": method, "params": safe}
        if flag:
            record[flag] = True
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
```

Trong `_route`, đổi ba dòng cuối thành:

```python
        body, flag = self._dispatch(req, svc)
        self.server.request_log.write(service, method, params, flag)
        return 200, body
```

Thay toàn bộ `_dispatch` bằng:

```python
    def _dispatch(self, req, svc):
        """(body, log flag): the flag is None, "quiet" or "closed"."""
        if req.service == "config":
            if req.method == "all_config":
                return handlers.all_config(req, svc), None
            return _refused(req.method), None
        if req.service == "login" and req.method in handlers.LOGIN_HANDLERS:
            return handlers.LOGIN_HANDLERS[req.method](req, svc), None

        handler = SESSION_HANDLERS.get((req.service, req.method))
        if handler is None and req.service not in SESSION_SERVICES:
            return _refused(req.method), None  # e.g. an unimplemented login method

        player = self._session_player(req, svc)
        if player is None:
            return handlers.need_login(), None
        flag, handler = _resolve(req, svc.scope, handler)
        # One transaction per request: concurrent requests of a player cannot interleave
        # their checks and writes, a crash leaves nothing half done, and a refusal
        # (an error status) never keeps a partial change.
        try:
            with svc.store.transaction():
                body = handler(req, svc, player)
                if body.get("status") != 0:
                    raise handlers.Refused.of(body)
                body["user_status"] = user_status(svc, player["uid"])
        except handlers.Refused as refused:
            body = refused.body
            body["user_status"] = user_status(svc, player["uid"])
        return body, flag
```

Thêm ngay trên `def _refused(method):`:

```python
def _resolve(req, scope: Scope, handler):
    """(log flag, handler) for a session request. Without a handler, a background call
    recorded in the scope gets its verified empty body, the client's analytics an empty
    success, and anything else a popup: an empty success would let the screen run on
    and fail on missing fields."""
    if handler is not None:
        return None, handler
    body = scope.quiet_body(req.method) if req.service == "api" else None
    if body is not None or req.service in QUIET_SERVICES:
        return "quiet", lambda *_: handlers.ok(body or {})
    return "closed", _closed


def _closed(*_):
    return handlers.fail("error_not_open", CLOSED_MSG)
```

Thay `build_server`:

```python
def build_server(host, port, db_path, config_dir, version_map_path, request_log, scope_path=None):
    version_map = json.loads(Path(version_map_path).read_text(encoding="utf-8"))
    scope = Scope.load(scope_path or scope_module.DEFAULT_PATH)   # a bad file stops the start
    server = ThreadingHTTPServer((host, port), GameHandler)
    server.daemon_threads = True
    server.services = Services(
        store=Store(str(db_path)),
        config_dir=Path(config_dir),
        version_map=version_map,
        all_config_version=handlers.version_map_etag(version_map),
        configs=ConfigCache(config_dir),
        scope=scope,
    )
    server.request_log = RequestLog(request_log)
    return server
```

Trong `main`, thêm đối số sau `--request-log`:

```python
    ap.add_argument("--scope", default=str(root / "data" / "scope_2018.json"))
```

và truyền nó:

```python
    server = build_server(args.host, args.port, args.db, args.config_dir,
                          args.version_map, args.request_log, args.scope)
```

- [ ] **Step 5: Chạy test để thấy nó qua**

Run: `cd server && python3 -I -m unittest discover -s tests -t .`
Expected: `OK`, không test nào lỗi.

- [ ] **Step 6: Kiểm server khởi động với bảng thật**

Run:
```bash
cd server
kill $(ss -ltnpH 'sport = :8080' | grep -oP 'pid=\K[0-9]+') 2>/dev/null
(python3 -m sahht_server.app --port 8080 > build/server.log 2>&1 &)
curl -s --retry 5 --retry-connrefused --retry-delay 1 'http://127.0.0.1:8080/pub_abroad_vr/api/?method=arena.index'
```
Expected: `{"status": "error_need_login", ...}` (chưa có phiên), không phải lỗi 500; `build/server.log` có `listening on`.

- [ ] **Step 7: Commit**

```bash
git add server/sahht_server/handlers.py server/sahht_server/app.py server/tests/test_flow.py
git commit -m "feat: close unimplemented methods with a popup and hide closed views"
```

---

### Task 5: Chặn nội dung sau 2018

**Files:**
- Modify: `server/sahht_server/rewards.py` (import; đầu hàm `grant`)
- Modify: `server/sahht_server/gacha.py` (bỏ import `LAST_HERO_ID`; `_hero_entries`)
- Modify: `server/sahht_server/campaign.py` (`_cities_in_order`)
- Modify: `server/tests/test_scope.py` (thêm `RewardReachTests`), `server/tests/test_gameplay.py` (`HeroTests`), `server/tests/test_campaign.py` (`WorldMapTests`)

**Interfaces:**
- Consumes: `Services.scope` (Task 4); `audit_scope.load_config`, `server_reward_sources`, `reachable_cards` (Task 3).
- Produces: `grant` ném `Refused` với `body["status"] == "error_scope"` khi loot có tướng ngoài phạm vi; `campaign._cities_in_order(svc)` bỏ thành phố ngoài `city_order_max`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `server/tests/test_scope.py`, ngay trước `if __name__ == "__main__":`:

```python
class RewardReachTests(unittest.TestCase):
    """No reward the server hands out can lead to a hero past the cut, through any boxes."""

    def test_no_reward_source_reaches_a_hero_after_2018(self):
        config = audit_scope.load_config
        cards = audit_scope.reachable_cards(audit_scope.server_reward_sources(config),
                                            config("item"), config("box"))
        scope = Scope.load(DEFAULT_PATH)
        self.assertTrue(cards, "the walk found no heroes at all: the config paths are wrong")
        self.assertEqual(sorted(c for c in cards if not scope.card_in_scope(c)), [])

    def test_the_walk_follows_boxes_inside_boxes(self):
        items = {"1": {"is_use": 1, "use_effect": [10]}, "2": {"is_use": 1, "use_effect": [20]}}
        boxes = {"10": [{"num": 1, "reward": [[6, 2, 1, 5]]}],
                 "20": [{"num": 1, "reward": [[5, 38800, 1, 5]]}]}
        self.assertEqual(audit_scope.reachable_cards([[6, 1, 1]], items, boxes), {38800})
```

Trong `server/tests/test_gameplay.py`, thêm import đầu file:

```python
from sahht_server.handlers import Refused
from sahht_server.rewards import Loot, grant
```

và thêm vào class `HeroTests`:

```python
    def test_a_hero_after_2018_is_never_granted(self):
        svc = self.server.services
        with self.assertRaises(Refused) as caught:
            with svc.store.transaction():
                grant(svc, self.uid, Loot(cards=[100, 38800]), 0)
        self.assertEqual(caught.exception.body["status"], "error_scope")
        self.assertEqual(len(svc.store.cards_for_player(self.uid)), 3)
```

Trong `server/tests/test_campaign.py`, thêm import đầu file:

```python
import dataclasses

from sahht_server import campaign
```

và thêm vào class `WorldMapTests`:

```python
    def test_cities_past_the_scope_are_left_out(self):
        svc = self.server.services
        narrow = dataclasses.replace(svc, scope=dataclasses.replace(svc.scope, city_order_max=0))
        self.assertEqual(campaign._cities_in_order(svc), ["100"])
        self.assertEqual(campaign._cities_in_order(narrow), [])
```

- [ ] **Step 2: Chạy test để thấy nó thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t .`
Expected: `test_a_hero_after_2018_is_never_granted` FAIL (không có `Refused`) và `test_cities_past_the_scope_are_left_out` FAIL (`['100'] != []`); `RewardReachTests` qua (dữ liệu đã sạch; test giữ nó sạch về sau).

- [ ] **Step 3: Cài đặt**

Trong `server/sahht_server/rewards.py`, thêm `import sys` vào đầu file, rồi đổi phần đầu của `grant` (giữ nguyên mọi dòng từ `with store.transaction():` trở đi):

```python
def grant(svc, uid: str, loot: Loot, now: int) -> Granted:
    """Apply the loot inside one transaction and describe it for the client."""
    late = [c for c in loot.cards if not svc.scope.card_in_scope(c)]
    if late:
        # A data bug, never a player action: no config reward should lead past the cut.
        print(f"refused out-of-scope heroes {late} for player {uid}", file=sys.stderr)
        raise Refused("error_scope", "Phần thưởng không hợp lệ.")
    store = svc.store
```

Trong `server/sahht_server/gacha.py`, xóa dòng `from .skills import LAST_HERO_ID` và đổi `_hero_entries`:

```python
def _hero_entries(svc: Services, pool: dict, key: str) -> list:
    characters = svc.configs.get("character_detail")
    return [(e[0], e[-1]) for e in pool.get(key, [])
            if isinstance(e, list) and len(e) >= 3 and str(e[0]) in characters
            and svc.scope.card_in_scope(e[0]) and e[-1] > 0]
```

Trong `server/sahht_server/campaign.py`, đổi `_cities_in_order`:

```python
def _cities_in_order(svc: Services) -> list:
    order = svc.configs.get("cityid_cityorderid")
    known = _city_buildings(svc)
    return [city for city, number in sorted(order.items(), key=lambda kv: int(kv[1]))
            if city in known and svc.scope.city_order_in_scope(number)]
```

- [ ] **Step 4: Chạy test để thấy nó qua**

Run: `cd server && python3 -I -m unittest discover -s tests -t .`
Expected: `OK`, không test nào lỗi.

- [ ] **Step 5: Commit**

```bash
git add server/sahht_server/rewards.py server/sahht_server/gacha.py server/sahht_server/campaign.py server/tests/test_scope.py server/tests/test_gameplay.py server/tests/test_campaign.py
git commit -m "feat: keep heroes and cities past 2018 out of every reward"
```

---

### Task 6: Nạp giả

**Files:**
- Modify: `server/sahht_server/player.py` (`CURRENCIES`; `_FIXED_STATUS`; `user_status`)
- Create: `server/sahht_server/payment.py`
- Modify: `server/sahht_server/app.py` (import và `SESSION_HANDLERS`)
- Modify: `server/tests/test_flow.py` (`FIXTURE_CONFIGS` thêm `charge`, `vip`)
- Create: `server/tests/test_payment.py`

**Interfaces:**
- Consumes: `Store.payment_exists`, `record_payment`, `payment_counts` (Task 1); `handlers.ok`, `fail`, `is_int`.
- Produces:
  - `player.FREE_TICKETS = 9999`
  - `player.vip_level(configs, vip_exp: int) -> int`
  - `user_status` có `ticket` (luôn `FREE_TICKETS`), `vip_exp` (từ ví), `vip` (tính từ `vip_exp`).
  - `payment.parse_order(cp_order_id: str) -> tuple[str, str] | None` ((uid, khóa gói))
  - `payment.HANDLERS` gồm `("api", "payment.use_ticket")` và `("api", "shop.vip_buy_step")`.

- [ ] **Step 1: Thêm config giả lập và viết test thất bại**

Trong `server/tests/test_flow.py`, thêm vào `FIXTURE_CONFIGS` (trước dấu `}` đóng dict):

```python
    # Recharge packs: 3 a plain coin bag, 4 doubles the first time, 5 can be bought once,
    # 1 is a monthly card (open_gift), 22 is hidden (is_show 0).
    "charge": {
        "1": {"name": "Thẻ tháng", "coin": 0, "gift_coin": 0, "is_double": 0, "buy_times": 2,
              "vip_exp": 500, "is_show": 1, "open_gift": 2, "price": 50000},
        "3": {"name": "Túi Xu 220", "coin": 220, "gift_coin": 0, "is_double": 0, "buy_times": 0,
              "vip_exp": 220, "is_show": 1, "open_gift": 0, "price": 20000},
        "4": {"name": "Túi Xu đôi", "coin": 550, "gift_coin": 50, "is_double": 1, "buy_times": 0,
              "vip_exp": 550, "is_show": 1, "open_gift": 0, "price": 50000},
        "5": {"name": "Một lần", "coin": 10, "gift_coin": 0, "is_double": 0, "buy_times": 1,
              "vip_exp": 10, "is_show": 1, "open_gift": 0, "price": 10000},
        "22": {"name": "Ẩn", "coin": 999, "gift_coin": 0, "is_double": 0, "buy_times": 0,
               "vip_exp": 0, "is_show": 0, "open_gift": 0, "price": 20000},
    },
    # need_exp of row L is the total vip_exp needed to reach L + 1.
    "vip": {"0": {"need_exp": 200}, "1": {"need_exp": 1200}, "2": {"need_exp": 3200}},
```

Tạo `server/tests/test_payment.py`:

```python
"""Free recharge with gold tickets: payment.use_ticket and shop.vip_buy_step."""

import time
import unittest

from sahht_server.payment import parse_order
from sahht_server.player import FREE_TICKETS, vip_level
from tests.test_gameplay import PlayerCase


class ParseOrderTests(unittest.TestCase):
    def test_order_id_is_uid_server_pack_then_anything(self):
        self.assertEqual(parse_order("10001_1_3_1700000000_0_42"), ("10001", "3"))
        self.assertEqual(parse_order("10001_1_3_1700000000_ch_with_parts_42"), ("10001", "3"))

    def test_malformed_order_ids_are_rejected(self):
        for bad in ("", "10001_1_3", "abc_1_3_1_0_1", "10001_1_x_1_0_1", "10001__3_1_0_1"):
            self.assertIsNone(parse_order(bad), bad)


class VipLevelTests(unittest.TestCase):
    def test_level_counts_thresholds_reached_and_stops_at_the_top_row(self):
        class Configs:
            @staticmethod
            def get(name):
                return {"0": {"need_exp": 200}, "1": {"need_exp": 1200}, "2": {"need_exp": 3200}}
        self.assertEqual([vip_level(Configs, e) for e in (0, 199, 200, 1199, 1200, 10 ** 9)],
                         [0, 0, 1, 1, 2, 2])


class RechargeTests(PlayerCase):
    def order(self, pack, n=0):
        return f"{self.uid}_1_{pack}_{int(time.time())}_0_{n}"

    def buy(self, pack, n=0):
        return self.call("payment.use_ticket", cpOrderId=self.order(pack, n))

    def test_tickets_are_free_and_never_run_out(self):
        status = self.call("user.main_page")["user_status"]
        self.assertEqual(status["ticket"], FREE_TICKETS)
        self.buy("3")
        self.assertEqual(self.call("user.main_page")["user_status"]["ticket"], FREE_TICKETS)

    def test_a_coin_bag_gives_coin_and_vip_exp(self):
        body = self.buy("3")
        self.assertEqual(body["status"], 0, body)
        status = body["user_status"]
        self.assertEqual((status["coin"], status["vip_exp"], status["vip"]), (1000 + 220, 220, 1))

    def test_first_purchase_of_a_double_pack_doubles_its_coin(self):
        self.assertEqual(self.buy("4", 1)["user_status"]["coin"], 1000 + 550 + 50 + 550)
        self.assertEqual(self.buy("4", 2)["user_status"]["coin"], 1000 + 1150 + 600)

    def test_a_resent_order_is_paid_once(self):
        order = self.order("3")
        self.call("payment.use_ticket", cpOrderId=order)
        body = self.call("payment.use_ticket", cpOrderId=order)
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], 1000 + 220)

    def test_buy_times_caps_a_pack(self):
        self.assertEqual(self.buy("5", 1)["status"], 0)
        body = self.buy("5", 2)
        self.assertEqual(body["status"], "error_buy_times")
        self.assertEqual(body["user_status"]["coin"], 1000 + 10)

    def test_packs_with_their_own_rewards_are_not_open_yet(self):
        for pack in ("1", "22"):
            body = self.buy(pack)
            self.assertEqual((body["status"], body["msg"]), ("error_not_open", "Gói này chưa mở."))
            self.assertEqual(body["user_status"]["coin"], 1000)

    def test_bad_orders_are_refused(self):
        for order in ("junk", "99999_1_3_1_0_1", f"{self.uid}_1_77_1_0_1"):
            body = self.call("payment.use_ticket", cpOrderId=order)
            self.assertEqual(body["status"], "error_param", order)
        self.assertEqual(self.call("user.main_page")["user_status"]["coin"], 1000)

    def test_vip_buy_step_lists_packs_already_bought(self):
        self.assertEqual(self.call("shop.vip_buy_step")["data"],
                         {"step": [], "double_pay": [], "month_award": 0, "week_award": 0})
        self.buy("4", 1)
        self.buy("3", 2)
        self.buy("3", 3)
        self.assertEqual(self.call("shop.vip_buy_step")["data"]["double_pay"], [3, 4])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Chạy test để thấy nó thất bại**

Run: `cd server && python3 -I -m unittest discover -s tests -t . -p 'test_payment.py'`
Expected: `ModuleNotFoundError: No module named 'sahht_server.payment'`.

- [ ] **Step 3: `user_status` với vé miễn phí và cấp VIP**

Trong `server/sahht_server/player.py`:

Xóa `"ticket", ` khỏi tuple `CURRENCIES`; vé không còn đến từ ví.

Thay `_FIXED_STATUS` bằng khối sau:

```python
_FIXED_STATUS = {
    "association_id": 0, "cur_title": 0,
    "card_max": 200, "equip_max": 100, "role": 1,
}
# Gold tickets ("Vé vàng") are how the client pays for recharge packs
# (native_helper.buyProduct). Recharge is free on this server, so the balance is fixed
# and never spent. The largest pack costs 300 tickets.
FREE_TICKETS = 9999


def vip_level(configs, vip_exp: int) -> int:
    """vip.config row L's need_exp is the total vip_exp that reaches L + 1. Capped at the
    top row: ui_vip reads the current level's row with no nil guard."""
    rows = configs.get("vip")
    if not rows:
        return 0
    reached = sum(1 for row in rows.values() if row.get("need_exp", float("inf")) <= vip_exp)
    return min(reached, max(int(key) for key in rows))
```

Trong `user_status`, thêm ba khóa ngay sau dòng `**svc.store.state(uid, now),  # action_point, ...`:

```python
        "ticket": FREE_TICKETS,
        "vip_exp": wallet.get("vip_exp", 0),
        "vip": vip_level(svc.configs, wallet.get("vip_exp", 0)),
```

- [ ] **Step 4: Module `payment.py`**

Tạo `server/sahht_server/payment.py`:

```python
"""Free recharge: payment.use_ticket and the VIP screen's shop.vip_buy_step.

The Vietnamese client has no payment gateway. ui_vip builds an order id
`<uid>_<server>_<pack>_<time>_<channel>`, native_helper.buyProduct appends `_<random>`
and sends it as cpOrderId once the player confirms paying in gold tickets. Tickets are
free here (player.FREE_TICKETS), so a purchase only grants the pack.
"""

import time

from .handlers import Request, Services, fail, is_int, ok

ORDER_FIELDS = 4   # uid, server, pack, then the rest (time, channel, random)


def parse_order(cp_order_id: str):
    """(uid, charge.config key), or None for a malformed order id."""
    parts = cp_order_id.split("_", ORDER_FIELDS - 1)
    if len(parts) != ORDER_FIELDS:
        return None
    uid, server, pack, rest = parts
    if not (uid.isascii() and uid.isdigit() and server and is_int(pack) and rest):
        return None
    return uid, pack


def use_ticket(req: Request, svc: Services, player: dict):
    order_id = req.params.get("cpOrderId", "")
    parsed = parse_order(order_id)
    if parsed is None or parsed[0] != player["uid"]:
        return fail("error_param", "Mã đơn nạp không hợp lệ.")
    pack_id = parsed[1]
    pack = svc.configs.get("charge").get(pack_id)
    if pack is None:
        return fail("error_param", "Gói nạp không tồn tại.")
    if pack.get("open_gift") or pack.get("is_show") != 1:
        # Monthly and weekly cards, growth plans and voucher packs carry rewards of
        # their own that no system grants yet (roadmap phase 1).
        return fail("error_not_open", "Gói này chưa mở.")
    uid = player["uid"]
    with svc.store.transaction():
        if svc.store.payment_exists(order_id):
            return ok()   # the client resent an order that was already paid
        bought = svc.store.payment_counts(uid).get(pack_id, 0)
        if pack.get("buy_times", 0) and bought >= pack["buy_times"]:
            return fail("error_buy_times", "Gói này đã mua đủ số lần.")
        coin = pack.get("coin", 0) + pack.get("gift_coin", 0)
        if pack.get("is_double") == 1 and bought == 0:
            coin += pack.get("coin", 0)   # "Nạp tiền lần đầu tặng <coin> Xu"
        svc.store.record_payment(uid, order_id, pack_id, int(time.time()))
        svc.store.change_wallet(uid, {"coin": coin, "vip_exp": pack.get("vip_exp", 0)})
    return ok()


def vip_buy_step(req: Request, svc: Services, player: dict):
    """ui_vip counts `step` (VIP gift packs bought: none until the VIP shop exists) and
    walks `double_pay` with #, comparing to numeric pack ids."""
    bought = svc.store.payment_counts(player["uid"])
    return ok({"step": [], "double_pay": sorted(int(p) for p in bought),
               "month_award": 0, "week_award": 0})


HANDLERS = {
    ("api", "payment.use_ticket"): use_ticket,
    ("api", "shop.vip_buy_step"): vip_buy_step,
}
```

Trong `server/sahht_server/app.py`, đổi import và `SESSION_HANDLERS`:

```python
from . import campaign, cards, gacha, handlers, payment, shop
```

```python
SESSION_HANDLERS = {**handlers.SESSION_HANDLERS, **campaign.HANDLERS, **cards.HANDLERS,
                    **gacha.HANDLERS, **shop.HANDLERS, **payment.HANDLERS}
```

- [ ] **Step 5: Chạy test để thấy nó qua**

Run: `cd server && python3 -I -m unittest discover -s tests -t .`
Expected: `OK`, không test nào lỗi; `test_every_module_with_a_handler_is_open` vẫn qua vì `payment` và `shop` đang mở trong bảng phạm vi.

- [ ] **Step 6: Commit**

```bash
git add server/sahht_server/player.py server/sahht_server/payment.py server/sahht_server/app.py server/tests/test_flow.py server/tests/test_payment.py
git commit -m "feat: free recharge with gold tickets and VIP levels"
```

---

### Task 7: E2E trên emulator, danh sách `quiet`, và tài liệu

**Files:**
- Modify: `server/data/scope_2018.json` (mục `quiet`, và view nếu E2E thấy nút cần đóng)
- Modify: `server/README.md`, `CLAUDE.md`
- Ảnh chụp: `server/build/phase0-*.png` (gitignored)

**Interfaces:**
- Consumes: mọi thứ ở Task 1-6.
- Produces: bằng chứng E2E; bảng phạm vi có `quiet` đầy đủ; tài liệu cập nhật.

- [ ] **Step 1: Khởi động lại server và kiểm emulator**

Run:
```bash
cd server
kill $(ss -ltnpH 'sport = :8080' | grep -oP 'pid=\K[0-9]+') 2>/dev/null
: > data/requests.jsonl
(python3 -m sahht_server.app --port 8080 > build/server.log 2>&1 &)
curl -s --retry 5 --retry-connrefused --retry-delay 1 -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8080/pub_abroad_vr/api/?method=x'
adb devices
```
Expected: `200`; `adb devices` có một dòng `emulator-5554	device`.
Nếu không có emulator, khởi động `~/Android/Sdk/emulator/emulator -avd sahht -no-audio -no-snapshot-save -gpu swiftshader_indirect` trong nền rồi `adb wait-for-device`.

- [ ] **Step 2: Tài khoản mới và tutorial đội 1 (không hồi quy)**

Run: `adb shell pm clear vn.sahht.sl && adb logcat -c && adb shell monkey -p vn.sahht.sl -c android.intent.category.LAUNCHER 1`
Đăng ký một tài khoản mới, đặt tên, đi hết tutorial đội 1 như trước (CLAUDE.md, mục "Emulator workflow"); khi về màn chính, chụp `adb exec-out screencap -p > build/phase0-main.png` và xem ảnh.
Expected: tutorial chạy hết như trước; `adb logcat -d | grep -E 'LUA ERROR|failed:|attempt to'` rỗng.

- [ ] **Step 3: Đọc log tìm API ngầm**

Run: `python3 -I -c "import json; [print(l['service'], l['method'], 'closed' if l.get('closed') else 'quiet') for l in map(json.loads, open('data/requests.jsonl')) if l.get('closed') or l.get('quiet')]"`
Với mỗi method `closed` mà người chơi không chủ động bấm:
1. Tìm nơi client gọi nó (`grep -rn '<khóa URL>' ../decompiled/lua`) và đọc callback để biết trường nào được đọc không có nil guard.
2. Thêm vào `quiet` của `data/scope_2018.json`: `"<method>": {"body": {<thân rỗng tối thiểu có đủ các trường đó>}, "evidence": "<file>:<dòng>"}`.
3. Chạy `python3 -I -m unittest discover -s tests -t . -p 'test_scope.py'`, khởi động lại server như Step 1 (không xóa log lần này), rồi về lại màn chính.
Expected: không còn dòng `closed` nào mà người chơi không chủ động bấm.

- [ ] **Step 4: Duyệt từng nút đang hiện trên màn chính**

Lần lượt chạm từng nút đang hiện; sau mỗi lần chạm, chụp `build/phase0-<tên nút>.png`, xem ảnh và logcat.
Expected cho mỗi nút: hoặc màn hình mở và chạy đúng, hoặc hiện popup "Tính năng chưa mở."; không lỗi Lua; không có chữ vỡ hay phần tử lệch.
Nếu một nút mở ra lỗi: tìm view ID của nó (`python3 -m tools.audit_scope | grep '^view'`) và đóng view đó trong bảng, hoặc thêm `quiet` nếu đó là API ngầm; khởi động lại server và kiểm lại nút đó.
Nếu thấy giao diện lỗi không do server, ghi lại để báo người dùng.

- [ ] **Step 5: Nút mở theo cấp ở cấp 10**

Đưa người chơi lên cấp 10 (thay `<tài khoản>` bằng tài khoản vừa tạo):
```bash
python3 -c "
import time
from sahht_server.store import Store
s = Store('data/sahht.db')
p = s.player_for_account('<tài khoản>')
s.set_level(p['uid'], 10, 0, int(time.time()))
print(p['uid'])"
```
Thoát game rồi vào lại để màn chính tải cấp mới; chạm nút bang hội (hoặc một nút mở theo cấp khác chưa làm, xem danh sách `button` của `python3 -m tools.audit_scope`) và chụp `build/phase0-guild.png`.
Expected: popup "Tính năng chưa mở."; logcat sạch.

- [ ] **Step 6: Nạp giả**

Mở màn VIP, chụp `build/phase0-vip.png`.
Expected: hiện `9999` Vé vàng và VIP như trong `user_status`.
Mua "Túi Xu 1100" và xác nhận.
Expected: xu tăng đúng 1100; `vip_exp` tăng 1100; nếu trước đó `vip_exp` là 0 thì thành VIP 1 (1100 ≥ 200 và < 1200 theo `vip.config`); thanh VIP hiện đúng tiến độ tới mốc 1200.
Chạm "Thẻ tháng" và xác nhận.
Expected: popup "Gói này chưa mở.".
Chụp `build/phase0-vip-after.png`; logcat sạch.

- [ ] **Step 7: Kiểm cuối**

Run:
```bash
adb logcat -d | grep -E 'LUA ERROR|failed:|attempt to'
python3 -I -c "import json; print([l['method'] for l in map(json.loads, open('data/requests.jsonl')) if l.get('closed')])"
python3 -I -m unittest discover -s tests -t .
```
Expected: logcat rỗng; danh sách `closed` chỉ gồm các nút đã cố ý chạm ở Step 4-5 (và gói "Thẻ tháng" không nằm trong đó, vì nó là `payment.use_ticket` có handler); toàn bộ test OK.

- [ ] **Step 8: Cập nhật tài liệu**

Trong `server/README.md`:
- Bảng "What works": thêm dòng `| Feature gate | user.main_page inreview, every method without a handler | data/scope_2018.json: closed views are hidden; methods without a handler answer error_not_open (a popup), except background calls listed as quiet, which get a verified empty body |` và dòng `| Recharge | payment.use_ticket, shop.vip_buy_step | free: gold tickets fixed at 9999; coin bags grant coin and VIP exp; packs with their own rewards answer "Gói này chưa mở." |`.
- Xóa dòng cuối cũ của bảng (`Everything else under /api/, /pay/, /dataosha/ ... answers status: 0 with empty data, and is logged`).
- Trong "Protocol notes", thay câu về `"stub": true` bằng: `Every request is logged; "closed": true marks a method the client called that has no handler yet, "quiet": true one answered with a recorded empty body.`
- Trong "Not done", đổi câu về stub thành: các tính năng ngoài Giai đoạn 0 đóng bằng popup, xem lộ trình.

Trong `CLAUDE.md`:
- "Server architecture": thay câu `Unknown /api/, /pay/, /dataosha/ methods get status 0 ...` bằng chính sách handler / quiet / closed; thêm `scope.py`, `payment.py`, `tools/audit_scope.py`, `data/scope_2018.json`, và migration (`MIGRATIONS`, `PRAGMA user_version`; không sửa migration đã áp dụng, chỉ thêm mới).
- "Hard-won shape rules": thêm `user.main_page` `inreview` (cả danh sách mỗi lần, client xóa danh sách cũ khi nhận); `active_switch` không bao giờ được client đọc; `error_not_open` + `msg` hiện popup và không gọi callback; luồng Vé vàng (`cpOrderId = <uid>_<server>_<pack>_<time>_<channel>_<random>`); `double_pay` là mảng số.
- "Commands": cập nhật số test và thêm `python3 -m tools.audit_scope` (`--draft`).
- "Status and next steps": Giai đoạn 0 xong; bước tiếp theo là Giai đoạn 1 theo `docs/superpowers/specs/2026-11-23-roadmap-2018.md`.
Mỗi câu một dòng; không dùng gạch dài.

- [ ] **Step 9: Commit**

```bash
git add server/data/scope_2018.json server/README.md CLAUDE.md
git commit -m "docs: phase 0 scope gate and free recharge, verified on the emulator"
```
