"""SQLite persistence: accounts, tickets, and everything a player owns.

The store holds data, not game rules: costs, level curves and rewards are decided by
the callers, which pass the numbers in. A multi-step change (pay, then grant) runs
inside `transaction()`, so it either happens completely or not at all.
"""

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager

UID_RE = re.compile(r"[0-9]{1,18}")   # ASCII only: str.isdigit() also accepts "²"
UID_OFFSET = 10000
DEFAULT_SERVER = "1"
ATTACK_SLOTS = 5          # cards.slot 0-4: attack positions
BENCH_SLOTS = 5           # cards.slot 5-9: bench positions 0-4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account  TEXT PRIMARY KEY,
    salt     BLOB,
    pw_hash  BLOB,
    ticket   TEXT
);
CREATE TABLE IF NOT EXISTS players (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT UNIQUE NOT NULL REFERENCES accounts(account),
    server  TEXT NOT NULL,
    name    TEXT NOT NULL,
    level   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS cards (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    c_id      INTEGER NOT NULL,
    lv        INTEGER NOT NULL DEFAULT 1,
    exp       INTEGER NOT NULL DEFAULT 0,   -- progress inside the current level
    step      INTEGER NOT NULL DEFAULT 0,   -- evolution step (the client's evo)
    slot      INTEGER                       -- 0-4 attack, 5-9 bench, NULL elsewhere
);
CREATE INDEX IF NOT EXISTS cards_by_player ON cards(player_id);
CREATE TABLE IF NOT EXISTS card_skills (
    card_id INTEGER NOT NULL REFERENCES cards(id),
    slot    INTEGER NOT NULL,               -- 1-based skill slot
    lv      INTEGER NOT NULL DEFAULT 1,
    exp     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (card_id, slot)
);
CREATE TABLE IF NOT EXISTS player_state (
    player_id    INTEGER PRIMARY KEY REFERENCES players(id),
    action_point INTEGER NOT NULL,
    ap_time      INTEGER NOT NULL,   -- epoch seconds the stored action_point was valid at
    exp          INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wallet (
    player_id INTEGER NOT NULL REFERENCES players(id),
    currency  TEXT NOT NULL,
    amount    INTEGER NOT NULL,
    PRIMARY KEY (player_id, currency)
);
CREATE TABLE IF NOT EXISTS items (
    player_id INTEGER NOT NULL REFERENCES players(id),
    item_id   INTEGER NOT NULL,
    count     INTEGER NOT NULL,
    PRIMARY KEY (player_id, item_id)
);
CREATE TABLE IF NOT EXISTS guide (
    player_id INTEGER NOT NULL REFERENCES players(id),
    team      TEXT NOT NULL,
    step      INTEGER NOT NULL,
    PRIMARY KEY (player_id, team)
);
CREATE TABLE IF NOT EXISTS cleared_buildings (
    player_id   INTEGER NOT NULL REFERENCES players(id),
    building_id INTEGER NOT NULL,
    PRIMARY KEY (player_id, building_id)
);
CREATE TABLE IF NOT EXISTS building_steps (
    player_id   INTEGER NOT NULL REFERENCES players(id),
    building_id INTEGER NOT NULL,
    steps_won   INTEGER NOT NULL,    -- fights of a multi-step building already won
    PRIMARY KEY (player_id, building_id)
);
CREATE TABLE IF NOT EXISTS counters (
    player_id INTEGER NOT NULL REFERENCES players(id),
    name      TEXT NOT NULL,         -- e.g. "gacha:101", "shop:1001"
    period    TEXT NOT NULL,         -- "" for lifetime counters, a date for daily ones
    value     INTEGER NOT NULL,
    PRIMARY KEY (player_id, name)
);
"""

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


def _hash_password(passwd: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passwd.encode(), salt=salt, n=2**14, r=8, p=1)


def _pid(uid: str) -> int:
    return int(uid) - UID_OFFSET


class Store:
    def __init__(self, db_path: str, ap_max: int = 120, ap_interval: int = 300):
        self.ap_max = ap_max
        self.ap_interval = ap_interval   # seconds per regenerated action point
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0
        try:
            self._migrate()
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

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

    @contextmanager
    def transaction(self):
        """All store calls inside commit together, or roll back together on an exception.
        Nested blocks join the outer one (no savepoints): an exception must reach the
        outermost block, which is the only one that commits or rolls back."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._db.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    self._db.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                try:
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise

    def _all(self, sql, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    # ---- accounts ----------------------------------------------------------

    def create_account(self, account: str, passwd: str | None) -> bool:
        """Create an account and its player. A None password makes a guest that cannot log in by password."""
        salt = secrets.token_bytes(16) if passwd is not None else None
        pw_hash = _hash_password(passwd, salt) if passwd is not None else None
        try:
            with self.transaction():
                self._db.execute("INSERT INTO accounts(account, salt, pw_hash) VALUES (?, ?, ?)",
                                 (account, salt, pw_hash))
                self._db.execute("INSERT INTO players(account, server, name) VALUES (?, ?, ?)",
                                 (account, DEFAULT_SERVER, account))
        except sqlite3.IntegrityError:
            return False
        return True

    def verify_password(self, account: str, passwd: str) -> bool:
        row = self._one("SELECT salt, pw_hash FROM accounts WHERE account = ?", (account,))
        if row is None or row["pw_hash"] is None:
            return False
        return hmac.compare_digest(_hash_password(passwd, row["salt"]), row["pw_hash"])

    def issue_ticket(self, account: str) -> str:
        """Replace the account's ticket; any earlier ticket stops working."""
        ticket = secrets.token_hex(16)
        with self.transaction():
            self._db.execute("UPDATE accounts SET ticket = ? WHERE account = ?", (ticket, account))
        return ticket

    def account_for_ticket(self, ticket: str) -> str | None:
        if not ticket:
            return None
        row = self._one("SELECT account FROM accounts WHERE ticket = ?", (ticket,))
        return row["account"] if row else None

    def player_for_account(self, account: str) -> dict | None:
        return _player(self._one(
            "SELECT id, account, server, name, level FROM players WHERE account = ?", (account,)))

    def player_for_uid(self, uid: str) -> dict | None:
        if not UID_RE.fullmatch(uid):
            return None
        return _player(self._one(
            "SELECT id, account, server, name, level FROM players WHERE id = ?", (_pid(uid),)))

    def rename(self, uid: str, name: str) -> None:
        with self.transaction():
            self._db.execute("UPDATE players SET name = ? WHERE id = ?", (name, _pid(uid)))

    # ---- cards ---------------------------------------------------------------

    def cards_for_player(self, uid: str) -> list[dict]:
        """Every card of the player with its skill progress: skills = {slot: (lv, exp)}."""
        rows = self._all("SELECT id, c_id, lv, exp, step, slot FROM cards "
                         "WHERE player_id = ? ORDER BY id", (_pid(uid),))
        skills = {}
        for s in self._all("SELECT s.card_id, s.slot, s.lv, s.exp FROM card_skills s "
                           "JOIN cards c ON c.id = s.card_id WHERE c.player_id = ?", (_pid(uid),)):
            skills.setdefault(s["card_id"], {})[s["slot"]] = (s["lv"], s["exp"])
        return [dict(row) | {"id": str(row["id"]), "skills": skills.get(row["id"], {})}
                for row in rows]

    def card(self, uid: str, card_id: str) -> dict | None:
        """One card the player owns, or None (also for ids of other players)."""
        return next((c for c in self.cards_for_player(uid) if c["id"] == str(card_id)), None)

    def add_cards(self, uid: str, c_ids) -> list[str]:
        """New level-1 cards outside the formation; returns their ids in order."""
        ids = []
        with self.transaction():
            for c_id in c_ids:
                cur = self._db.execute("INSERT INTO cards(player_id, c_id) VALUES (?, ?)",
                                       (_pid(uid), int(c_id)))
                ids.append(str(cur.lastrowid))
        return ids

    def grant_starter_cards(self, uid: str, c_ids) -> bool:
        """Give a player with no cards the starter heroes in formation order; True if granted."""
        with self.transaction():
            if self._one("SELECT 1 FROM cards WHERE player_id = ? LIMIT 1", (_pid(uid),)):
                return False
            self._db.executemany("INSERT INTO cards(player_id, c_id, slot) VALUES (?, ?, ?)",
                                 [(_pid(uid), c_id, slot) for slot, c_id in enumerate(c_ids)])
        return True

    def update_card(self, uid: str, card_id: str, *, lv: int, exp: int, step: int) -> None:
        with self.transaction():
            self._db.execute("UPDATE cards SET lv = ?, exp = ?, step = ? "
                             "WHERE id = ? AND player_id = ?", (lv, exp, step, int(card_id), _pid(uid)))

    def set_card_skill(self, card_id: str, slot: int, lv: int, exp: int) -> None:
        with self.transaction():
            self._db.execute("INSERT INTO card_skills(card_id, slot, lv, exp) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT(card_id, slot) DO UPDATE SET lv = excluded.lv, exp = excluded.exp",
                             (int(card_id), slot, lv, exp))

    def remove_cards(self, uid: str, card_ids) -> bool:
        """Delete cards the player owns; refuses (False) if any id is not theirs."""
        ids = [int(i) for i in card_ids]
        with self.transaction():
            owned = self._all(f"SELECT id FROM cards WHERE player_id = ? AND id IN "
                              f"({','.join('?' * len(ids))})", (_pid(uid), *ids)) if ids else []
            if len(owned) != len(set(ids)):
                return False
            for card_id in ids:
                self._db.execute("DELETE FROM card_skills WHERE card_id = ?", (card_id,))
                self._db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        return True

    def set_alignment(self, uid: str, attack: list, bench: list) -> bool:
        """Place cards by position (None = empty). Refuses ids the player does not own or repeats."""
        placed = [int(c) for c in attack + bench if c is not None]
        if len(placed) != len(set(placed)) or len(attack) > ATTACK_SLOTS or len(bench) > BENCH_SLOTS:
            return False
        with self.transaction():
            owned = {r["id"] for r in self._all("SELECT id FROM cards WHERE player_id = ?", (_pid(uid),))}
            if not set(placed) <= owned:
                return False
            self._db.execute("UPDATE cards SET slot = NULL WHERE player_id = ?", (_pid(uid),))
            for offset, row in ((0, attack), (ATTACK_SLOTS, bench)):
                for pos, card_id in enumerate(row):
                    if card_id is not None:
                        self._db.execute("UPDATE cards SET slot = ? WHERE id = ?",
                                         (offset + pos, int(card_id)))
        return True

    # ---- wallet and items ------------------------------------------------------

    def wallet(self, uid: str) -> dict:
        return {r["currency"]: r["amount"] for r in
                self._all("SELECT currency, amount FROM wallet WHERE player_id = ?", (_pid(uid),))}

    def change_wallet(self, uid: str, deltas: dict) -> bool:
        """Add (or, with negatives, spend) currencies; refuses if any balance would go negative."""
        with self.transaction():
            current = self.wallet(uid)
            if any(current.get(k, 0) + v < 0 for k, v in deltas.items()):
                return False
            for currency, delta in deltas.items():
                self._db.execute(
                    "INSERT INTO wallet(player_id, currency, amount) VALUES (?, ?, ?) "
                    "ON CONFLICT(player_id, currency) DO UPDATE SET amount = amount + excluded.amount",
                    (_pid(uid), currency, delta))
        return True

    def items(self, uid: str) -> dict:
        return {r["item_id"]: r["count"] for r in
                self._all("SELECT item_id, count FROM items WHERE player_id = ? AND count > 0",
                          (_pid(uid),))}

    def change_items(self, uid: str, deltas: dict) -> bool:
        """Add or consume items by id; refuses if any count would go negative."""
        with self.transaction():
            current = self.items(uid)
            if any(current.get(int(k), 0) + v < 0 for k, v in deltas.items()):
                return False
            for item_id, delta in deltas.items():
                self._db.execute(
                    "INSERT INTO items(player_id, item_id, count) VALUES (?, ?, ?) "
                    "ON CONFLICT(player_id, item_id) DO UPDATE SET count = count + excluded.count",
                    (_pid(uid), int(item_id), delta))
        return True

    # ---- counters (gacha draws, shop purchases, free-draw times) ---------------

    def counter(self, uid: str, name: str, period: str = "") -> int:
        """A counter's value; a counter stored for another period reads as 0."""
        row = self._one("SELECT period, value FROM counters WHERE player_id = ? AND name = ?",
                        (_pid(uid), name))
        return row["value"] if row and row["period"] == period else 0

    def set_counter(self, uid: str, name: str, value: int, period: str = "") -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO counters(player_id, name, period, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(player_id, name) DO UPDATE SET period = excluded.period, value = excluded.value",
                (_pid(uid), name, period, value))

    # ---- tutorial --------------------------------------------------------------

    def guide(self, uid: str) -> dict:
        return {r["team"]: r["step"] for r in
                self._all("SELECT team, step FROM guide WHERE player_id = ?", (_pid(uid),))}

    def advance_guide(self, uid: str, team: str, step: int) -> None:
        """Tutorial progress only moves forward."""
        with self.transaction():
            self._db.execute(
                "INSERT INTO guide(player_id, team, step) VALUES (?, ?, ?) "
                "ON CONFLICT(player_id, team) DO UPDATE SET step = MAX(step, excluded.step)",
                (_pid(uid), team, step))

    # ---- stamina, experience, level -----------------------------------------------

    def _state_row(self, player_id: int, now: int):
        row = self._db.execute(
            "SELECT action_point, ap_time, exp FROM player_state WHERE player_id = ?",
            (player_id,)).fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO player_state(player_id, action_point, ap_time) VALUES (?, ?, ?)",
                (player_id, self.ap_max, now))
            return self.ap_max, now, 0
        return row["action_point"], row["ap_time"], row["exp"]

    def _regenerate(self, action_point: int, ap_time: int, now: int):
        """Current points and the time they are valid at, keeping partial progress."""
        if action_point >= self.ap_max:
            return action_point, now
        gained = max(0, now - ap_time) // self.ap_interval
        if action_point + gained >= self.ap_max:
            return self.ap_max, now
        return action_point + gained, ap_time + gained * self.ap_interval

    def state(self, uid: str, now: int) -> dict:
        with self.transaction():
            ap, ap_time, exp = self._state_row(_pid(uid), now)
        ap, ap_time = self._regenerate(ap, ap_time, now)
        left = 0 if ap >= self.ap_max else self.ap_interval - (now - ap_time)
        return {"action_point": ap, "action_point_update_left": left, "exp": exp}

    def change_action_point(self, uid: str, delta: int, now: int) -> bool:
        """Spend (negative) or add stamina; refuses a spend larger than what is left.
        Added points may go above the maximum; regeneration then waits until it drops below."""
        player_id = _pid(uid)
        with self.transaction():
            ap, ap_time = self._regenerate(*self._state_row(player_id, now)[:2], now)
            if ap + delta < 0:
                return False
            if ap >= self.ap_max:
                ap_time = now  # regeneration starts from the moment it drops below max
            self._db.execute("UPDATE player_state SET action_point = ?, ap_time = ? WHERE player_id = ?",
                             (ap + delta, ap_time, player_id))
        return True

    def spend_action_point(self, uid: str, cost: int, now: int) -> bool:
        return self.change_action_point(uid, -cost, now)

    def set_level(self, uid: str, level: int, exp: int, now: int) -> None:
        """Store the player's level and the experience inside it."""
        player_id = _pid(uid)
        with self.transaction():
            self._state_row(player_id, now)
            self._db.execute("UPDATE player_state SET exp = ? WHERE player_id = ?", (exp, player_id))
            self._db.execute("UPDATE players SET level = ? WHERE id = ?", (level, player_id))

    # ---- campaign progress ----------------------------------------------------------

    def cleared_buildings(self, uid: str) -> set[int]:
        return {r["building_id"] for r in self._all(
            "SELECT building_id FROM cleared_buildings WHERE player_id = ?", (_pid(uid),))}

    def mark_cleared(self, uid: str, building_id: int) -> bool:
        """Record a cleared building; True only the first time (first-clear rewards)."""
        with self.transaction():
            cur = self._db.execute(
                "INSERT OR IGNORE INTO cleared_buildings(player_id, building_id) VALUES (?, ?)",
                (_pid(uid), building_id))
            self._db.execute("DELETE FROM building_steps WHERE player_id = ? AND building_id = ?",
                             (_pid(uid), building_id))
        return cur.rowcount == 1

    def building_steps(self, uid: str) -> dict:
        """building id -> fights already won of a building that is not finished yet."""
        return {r["building_id"]: r["steps_won"] for r in self._all(
            "SELECT building_id, steps_won FROM building_steps WHERE player_id = ?", (_pid(uid),))}

    def set_building_steps(self, uid: str, building_id: int, steps_won: int) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO building_steps(player_id, building_id, steps_won) VALUES (?, ?, ?) "
                "ON CONFLICT(player_id, building_id) DO UPDATE SET steps_won = excluded.steps_won",
                (_pid(uid), building_id, steps_won))

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


def _player(row) -> dict | None:
    if row is None:
        return None
    return {
        "uid": str(row["id"] + UID_OFFSET),
        "account": row["account"],
        "server": row["server"],
        "name": row["name"],
        "level": row["level"],
    }
