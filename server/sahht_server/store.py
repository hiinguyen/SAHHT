"""SQLite persistence: accounts, tickets, and everything a player owns.

The store holds data, not game rules: costs, level curves and rewards are decided by
the callers, which pass the numbers in. A multi-step change (pay, then grant) runs
inside `transaction()`, so it either happens completely or not at all.
"""

import hashlib
import hmac
import json
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

_CARD_LOCK = """
ALTER TABLE cards ADD COLUMN locked INTEGER NOT NULL DEFAULT 0;
"""

_EQUIPMENT = """
CREATE TABLE IF NOT EXISTS equipment (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    c_id      INTEGER NOT NULL,           -- equip.config key
    lv        INTEGER NOT NULL DEFAULT 1,
    st_lv     INTEGER NOT NULL DEFAULT 0  -- refine level
);
CREATE INDEX IF NOT EXISTS equipment_by_player ON equipment(player_id);
CREATE TABLE IF NOT EXISTS equipment_positions (
    player_id    INTEGER NOT NULL REFERENCES players(id),
    position     INTEGER NOT NULL,         -- team position 0-9
    slot         INTEGER NOT NULL,         -- equipment sort - 1: 0-3
    equipment_id INTEGER NOT NULL UNIQUE REFERENCES equipment(id),
    PRIMARY KEY (player_id, position, slot)
);
"""

# Every feature that adds fields to an equipment document (refine, enchant, forge,
# fate, and their pending rolls) keeps them together in one JSON column: they are always
# read and written as a set, never queried by key, so a new feature needs no migration.
_EQUIPMENT_EXTRA = """
ALTER TABLE equipment ADD COLUMN extra TEXT NOT NULL DEFAULT '{}';
"""

# The three skill slots a 5-skill hero brings to a battle ("1_2_3"), as a fixed
# three-of-five choice; `cards.set_battle_skill` rewrites it.
_BATTLE_SKILLS = """
CREATE TABLE IF NOT EXISTS battle_skill_slots (
    card_id INTEGER PRIMARY KEY REFERENCES cards(id),
    slots   TEXT NOT NULL
);
"""

# Leader skills: the learned level of each (skill id -> level, JSON) and the three
# equipped slots (`[id, id, id]`, 0 for empty).
_LEADER_SKILLS = """
CREATE TABLE IF NOT EXISTS leader_skills (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    levels    TEXT NOT NULL DEFAULT '{}',
    slots     TEXT NOT NULL DEFAULT '[0, 0, 0]'
);
"""

# Gems are fungible stacks keyed by the client's gem key: "<gem.config id>" for a plain
# gem, "<evolution level>-<gem.config id>" for an evolved one. `gem_positions` is the
# per-position grid of keys (slot 0 attack gem, slots 1-3 defence gems).
_GEMS = """
CREATE TABLE IF NOT EXISTS gems (
    player_id INTEGER NOT NULL REFERENCES players(id),
    gem_key   TEXT NOT NULL,
    count     INTEGER NOT NULL CHECK (count > 0),
    PRIMARY KEY (player_id, gem_key)
);
CREATE TABLE IF NOT EXISTS gem_positions (
    player_id INTEGER NOT NULL REFERENCES players(id),
    position  INTEGER NOT NULL,
    slot      INTEGER NOT NULL,
    gem_key   TEXT NOT NULL,
    PRIMARY KEY (player_id, position, slot)
);
"""

# The unfinished run of an activity chapter (resource war, daily/extreme challenge, exp
# stage): which stage and the 0-based steps already won, as a JSON list.
_ACTIVE_RUNS = """
CREATE TABLE IF NOT EXISTS active_runs (
    player_id INTEGER NOT NULL REFERENCES players(id),
    chapter   INTEGER NOT NULL,
    active_id INTEGER NOT NULL,
    steps     TEXT NOT NULL,
    PRIMARY KEY (player_id, chapter)
);
"""

# Elite stages: one attempt at a time. `elite_attempt` is the city and chapter being fought,
# `elite_cleared` its buildings won so far (wiped when a new attempt starts), `elite_done` the
# cities ever completed (they pay the repeat reward and show as recovered).
_ELITE = """
CREATE TABLE IF NOT EXISTS elite_attempt (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    city      TEXT NOT NULL,
    chapter   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS elite_cleared (
    player_id   INTEGER NOT NULL REFERENCES players(id),
    building_id INTEGER NOT NULL,
    PRIMARY KEY (player_id, building_id)
);
CREATE TABLE IF NOT EXISTS elite_done (
    player_id INTEGER NOT NULL REFERENCES players(id),
    city      TEXT NOT NULL,
    PRIMARY KEY (player_id, city)
);
"""

_CARD_BREAK = """
ALTER TABLE cards ADD COLUMN bre INTEGER NOT NULL DEFAULT 0;
"""

_MAIL = """
CREATE TABLE IF NOT EXISTS mail (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    mail_key   TEXT,
    sender     TEXT NOT NULL DEFAULT 'sys',
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL,
    gift       TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    claimed_at INTEGER
);
CREATE INDEX IF NOT EXISTS mail_by_player ON mail(player_id, claimed_at);
CREATE UNIQUE INDEX IF NOT EXISTS mail_once ON mail(player_id, mail_key) WHERE mail_key IS NOT NULL
"""

# Arena: one ladder row per player (rank and when periodic points were last paid), the
# battle log both sides read, and the replayed battle documents the log points at.
_ARENA = """
CREATE TABLE IF NOT EXISTS arena (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    rank      INTEGER NOT NULL,
    award_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS arena_by_rank ON arena(rank);
CREATE TABLE IF NOT EXISTS arena_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    attacker   TEXT NOT NULL,
    defender   TEXT NOT NULL,
    a_combat   INTEGER NOT NULL,
    d_combat   INTEGER NOT NULL,
    tp         TEXT NOT NULL,
    is_win     INTEGER NOT NULL,
    battle_log TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS arena_log_by_player ON arena_log(player_id, id);
CREATE TABLE IF NOT EXISTS arena_replays (
    key        TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""

# Applied in order; PRAGMA user_version is how many are applied. Migration 1 is the
# original schema (IF NOT EXISTS), so a database from before migrations is upgraded in
# place. Never edit an applied migration: append a new one.
MIGRATIONS = (_SCHEMA, _PAYMENTS, _CARD_LOCK, _EQUIPMENT, _EQUIPMENT_EXTRA, _BATTLE_SKILLS,
              _LEADER_SKILLS, _GEMS, _ACTIVE_RUNS, _ELITE, _CARD_BREAK, _MAIL, _ARENA)


def _statements(script: str) -> list[str]:
    """executescript() commits on its own, so migrations run statement by statement."""
    return [s.strip() for s in script.split(";") if s.strip()]


def _hash_password(passwd: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passwd.encode(), salt=salt, n=2**14, r=8, p=1)


def _pid(uid: str) -> int:
    return int(uid) - UID_OFFSET


def _decode_extra(raw) -> dict:
    """The JSON column as a dict; an unreadable value must not break the whole roster."""
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


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

    def players_overview(self) -> list[dict]:
        """`{account, uid, name, level}` of every player, oldest first."""
        return [{"account": r["account"], "uid": _player(r)["uid"], "name": r["name"],
                 "level": r["level"]}
                for r in self._all("SELECT id, account, server, name, level FROM players "
                                   "ORDER BY id")]

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
        """Every card of the player with its skill progress: skills = {slot: (lv, exp)}.
        `battle_slots` is the three skill slots the card brings to a battle."""
        rows = self._all("SELECT id, c_id, lv, exp, step, bre, slot, locked FROM cards "
                         "WHERE player_id = ? ORDER BY id", (_pid(uid),))
        skills = {}
        for s in self._all("SELECT s.card_id, s.slot, s.lv, s.exp FROM card_skills s "
                           "JOIN cards c ON c.id = s.card_id WHERE c.player_id = ?", (_pid(uid),)):
            skills.setdefault(s["card_id"], {})[s["slot"]] = (s["lv"], s["exp"])
        battle = {b["card_id"]: [int(p) for p in b["slots"].split("_") if p]
                  for b in self._all("SELECT b.card_id, b.slots FROM battle_skill_slots b "
                                     "JOIN cards c ON c.id = b.card_id WHERE c.player_id = ?",
                                     (_pid(uid),))}
        return [dict(row) | {"id": str(row["id"]), "skills": skills.get(row["id"], {}),
                             "battle_slots": battle.get(row["id"])}
                for row in rows]

    # ---- leader skills -------------------------------------------------------

    def leader_skills(self, uid: str) -> tuple:
        """(learned {skill id: level}, equipped [id, id, id])."""
        row = self._one("SELECT levels, slots FROM leader_skills WHERE player_id = ?",
                        (_pid(uid),))
        if row is None:
            return {}, [0, 0, 0]
        try:
            levels = {int(k): int(v) for k, v in json.loads(row["levels"]).items()}
            slots = [int(s) for s in json.loads(row["slots"])]
        except (ValueError, TypeError, AttributeError):
            return {}, [0, 0, 0]
        return levels, (slots if len(slots) == 3 else [0, 0, 0])

    def set_leader_skill_level(self, uid: str, skill_id: int, level: int) -> None:
        levels, slots = self.leader_skills(uid)
        levels[int(skill_id)] = int(level)
        self._write_leader_skills(uid, levels, slots)

    def set_leader_skill_slots(self, uid: str, slots: list) -> None:
        levels, _ = self.leader_skills(uid)
        self._write_leader_skills(uid, levels, [int(s) for s in slots])

    def _write_leader_skills(self, uid: str, levels: dict, slots: list) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO leader_skills(player_id, levels, slots) VALUES (?, ?, ?) "
                "ON CONFLICT(player_id) DO UPDATE SET levels = excluded.levels, "
                "slots = excluded.slots",
                (_pid(uid), json.dumps({str(k): v for k, v in levels.items()}),
                 json.dumps(list(slots))))

    def set_battle_skill_slots(self, card_id: str, slots: list) -> None:
        with self.transaction():
            self._db.execute("INSERT INTO battle_skill_slots(card_id, slots) VALUES (?, ?) "
                             "ON CONFLICT(card_id) DO UPDATE SET slots = excluded.slots",
                             (int(card_id), "_".join(str(s) for s in slots)))

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

    def set_card_break(self, uid: str, card_id: str, bre: int) -> None:
        with self.transaction():
            self._db.execute("UPDATE cards SET bre = ? WHERE id = ? AND player_id = ?",
                             (bre, int(card_id), _pid(uid)))

    def reset_card(self, uid: str, card_id: str) -> None:
        """Back to a fresh card: level 1, no exp, no evolution, skills at their first tier.
        The break level stays."""
        with self.transaction():
            self._db.execute("UPDATE cards SET lv = 1, exp = 0, step = 0 "
                             "WHERE id = ? AND player_id = ?", (int(card_id), _pid(uid)))
            self._db.execute("DELETE FROM card_skills WHERE card_id = ?", (int(card_id),))
            self._db.execute("DELETE FROM battle_skill_slots WHERE card_id = ?", (int(card_id),))

    def set_card_locked(self, uid: str, card_id: str, locked: bool) -> bool:
        """Lock or unlock a card the player owns; False when it is not theirs."""
        with self.transaction():
            cur = self._db.execute("UPDATE cards SET locked = ? WHERE id = ? AND player_id = ?",
                                   (1 if locked else 0, int(card_id), _pid(uid)))
            return cur.rowcount == 1

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
                self._db.execute("DELETE FROM battle_skill_slots WHERE card_id = ?", (card_id,))
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

    # ---- equipment -------------------------------------------------------------

    def equipment_rows(self, uid: str) -> list[dict]:
        """Every equipment instance of the player, with its string id and decoded `extra`."""
        return [dict(row) | {"id": str(row["id"]), "extra": _decode_extra(row["extra"])}
                for row in self._all(
                    "SELECT id, c_id, lv, st_lv, extra FROM equipment "
                    "WHERE player_id = ? ORDER BY id", (_pid(uid),))]

    def equipment_row(self, uid: str, equip_id: str) -> dict | None:
        return next((e for e in self.equipment_rows(uid) if e["id"] == str(equip_id)), None)

    def equipment_count(self, uid: str) -> int:
        return self._one("SELECT COUNT(*) FROM equipment WHERE player_id = ?",
                         (_pid(uid),))[0]

    def equipment_extra(self, uid: str, equip_id: str) -> dict | None:
        """The feature fields of one piece, or None when it is not the player's."""
        row = self._one("SELECT extra FROM equipment WHERE id = ? AND player_id = ?",
                        (int(equip_id), _pid(uid)))
        return None if row is None else _decode_extra(row["extra"])

    def set_equipment_extra(self, uid: str, equip_id: str, extra: dict) -> bool:
        with self.transaction():
            cur = self._db.execute(
                "UPDATE equipment SET extra = ? WHERE id = ? AND player_id = ?",
                (json.dumps(extra, ensure_ascii=False, sort_keys=True), int(equip_id), _pid(uid)))
            return cur.rowcount == 1

    def add_equipment(self, uid: str, c_ids) -> list[str]:
        """New level-1 equipment instances; returns their ids in order."""
        ids = []
        with self.transaction():
            for c_id in c_ids:
                cur = self._db.execute(
                    "INSERT INTO equipment(player_id, c_id) VALUES (?, ?)",
                    (_pid(uid), int(c_id)))
                ids.append(str(cur.lastrowid))
        return ids

    def set_equipment_level(self, uid: str, equip_id: str, lv: int) -> bool:
        with self.transaction():
            cur = self._db.execute(
                "UPDATE equipment SET lv = ? WHERE id = ? AND player_id = ?",
                (lv, int(equip_id), _pid(uid)))
            return cur.rowcount == 1

    def set_equipment_st_level(self, uid: str, equip_id: str, st_lv: int) -> bool:
        with self.transaction():
            cur = self._db.execute(
                "UPDATE equipment SET st_lv = ? WHERE id = ? AND player_id = ?",
                (st_lv, int(equip_id), _pid(uid)))
            return cur.rowcount == 1

    def set_equipment_config(self, uid: str, equip_id: str, c_id: int) -> bool:
        """Turn an instance into another equip config, keeping its id, level and place."""
        with self.transaction():
            cur = self._db.execute(
                "UPDATE equipment SET c_id = ? WHERE id = ? AND player_id = ?",
                (int(c_id), int(equip_id), _pid(uid)))
            return cur.rowcount == 1

    def equipment_positions(self, uid: str) -> list[tuple]:
        """(position, slot, equipment id) for every equipped piece."""
        return [(r["position"], r["slot"], str(r["equipment_id"])) for r in self._all(
            "SELECT position, slot, equipment_id FROM equipment_positions "
            "WHERE player_id = ?", (_pid(uid),))]

    def set_equipment_positions(self, uid: str, placements) -> None:
        """Replace the whole grid; `placements` is (position, slot, equipment id)."""
        with self.transaction():
            self._db.execute("DELETE FROM equipment_positions WHERE player_id = ?", (_pid(uid),))
            self._db.executemany(
                "INSERT INTO equipment_positions(player_id, position, slot, equipment_id) "
                "VALUES (?, ?, ?, ?)",
                [(_pid(uid), position, slot, int(equip_id))
                 for position, slot, equip_id in placements])

    def remove_equipment(self, uid: str, equip_ids) -> bool:
        """Delete equipment the player owns; False if any id is not theirs."""
        ids = [int(i) for i in equip_ids]
        with self.transaction():
            owned = self._all(
                f"SELECT id FROM equipment WHERE player_id = ? AND id IN "
                f"({','.join('?' * len(ids))})", (_pid(uid), *ids)) if ids else []
            if len(owned) != len(set(ids)):
                return False
            for equip_id in ids:
                self._db.execute("DELETE FROM equipment_positions WHERE equipment_id = ?",
                                 (equip_id,))
                self._db.execute("DELETE FROM equipment WHERE id = ?", (equip_id,))
        return True

    # ---- gems ------------------------------------------------------------------

    def gems(self, uid: str) -> dict:
        """gem key -> count, for every stack the player holds."""
        return {r["gem_key"]: r["count"] for r in self._all(
            "SELECT gem_key, count FROM gems WHERE player_id = ?", (_pid(uid),))}

    def change_gems(self, uid: str, deltas: dict) -> bool:
        """Add or consume gems by key; refuses (changing nothing) if a stack would go
        negative. A stack that reaches zero is deleted."""
        with self.transaction():
            current = self.gems(uid)
            if any(current.get(key, 0) + delta < 0 for key, delta in deltas.items()):
                return False
            for key, delta in deltas.items():
                total = current.get(key, 0) + delta
                if total:
                    self._db.execute(
                        "INSERT INTO gems(player_id, gem_key, count) VALUES (?, ?, ?) "
                        "ON CONFLICT(player_id, gem_key) DO UPDATE SET count = excluded.count",
                        (_pid(uid), str(key), total))
                else:
                    self._db.execute("DELETE FROM gems WHERE player_id = ? AND gem_key = ?",
                                     (_pid(uid), str(key)))
        return True

    def gem_positions(self, uid: str) -> list[tuple]:
        """(position, slot, gem key) for every placed gem."""
        return [(r["position"], r["slot"], r["gem_key"]) for r in self._all(
            "SELECT position, slot, gem_key FROM gem_positions WHERE player_id = ?",
            (_pid(uid),))]

    def set_gem_positions(self, uid: str, placements) -> None:
        """Replace the whole grid; `placements` is (position, slot, gem key)."""
        with self.transaction():
            self._db.execute("DELETE FROM gem_positions WHERE player_id = ?", (_pid(uid),))
            self._db.executemany(
                "INSERT INTO gem_positions(player_id, position, slot, gem_key) "
                "VALUES (?, ?, ?, ?)",
                [(_pid(uid), position, slot, str(key)) for position, slot, key in placements])

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

    # ---- mail ------------------------------------------------------------------

    def add_mail(self, uid: str, *, key, sender, title, content, gift, now, ttl) -> int | None:
        """A new inbox row, or None when a mail with the same key was already sent."""
        with self.transaction():
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO mail(player_id, mail_key, sender, title, content, gift,"
                " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_pid(uid), key, sender, title, content, json.dumps(gift), now, now + ttl))
            return cursor.lastrowid if cursor.rowcount else None

    def mail_inbox(self, uid: str, now: int, limit: int = 100) -> list[dict]:
        """Unclaimed, unexpired mail, newest first."""
        rows = self._all(
            "SELECT * FROM mail WHERE player_id = ? AND claimed_at IS NULL AND expires_at > ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?", (_pid(uid), now, limit))
        return [{**dict(row), "gift": json.loads(row["gift"])} for row in rows]

    def mail_row(self, uid: str, mail_id: int, now: int) -> dict | None:
        """One claimable mail of the player, or None."""
        row = self._one("SELECT * FROM mail WHERE id = ? AND player_id = ? AND claimed_at IS NULL"
                        " AND expires_at > ?", (mail_id, _pid(uid), now))
        return None if row is None else {**dict(row), "gift": json.loads(row["gift"])}

    def claim_mail(self, uid: str, mail_id: int, now: int) -> bool:
        with self.transaction():
            return self._db.execute(
                "UPDATE mail SET claimed_at = ? WHERE id = ? AND player_id = ? "
                "AND claimed_at IS NULL", (now, mail_id, _pid(uid))).rowcount == 1

    def purge_mail(self, uid: str, before: int) -> None:
        """Forget claimed mail older than `before` (keyed tombstones included)."""
        with self.transaction():
            self._db.execute("DELETE FROM mail WHERE player_id = ? AND claimed_at < ?",
                             (_pid(uid), before))

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

    # ---- elite attempts --------------------------------------------------------

    def elite_attempt(self, uid: str):
        """(city, chapter) of the attempt in progress, or None."""
        row = self._one("SELECT city, chapter FROM elite_attempt WHERE player_id = ?", (_pid(uid),))
        return (row["city"], row["chapter"]) if row else None

    def start_elite_attempt(self, uid: str, city: str, chapter: int) -> None:
        """Begin an attempt with nothing cleared, replacing any in progress."""
        with self.transaction():
            self._db.execute("DELETE FROM elite_cleared WHERE player_id = ?", (_pid(uid),))
            self._db.execute(
                "INSERT INTO elite_attempt(player_id, city, chapter) VALUES (?, ?, ?) "
                "ON CONFLICT(player_id) DO UPDATE SET city = excluded.city, chapter = excluded.chapter",
                (_pid(uid), city, chapter))

    def end_elite_attempt(self, uid: str, completed_city: str = "") -> None:
        """Drop the attempt; a completed one is remembered in `elite_done`."""
        with self.transaction():
            self._db.execute("DELETE FROM elite_attempt WHERE player_id = ?", (_pid(uid),))
            self._db.execute("DELETE FROM elite_cleared WHERE player_id = ?", (_pid(uid),))
            if completed_city:
                self._db.execute("INSERT OR IGNORE INTO elite_done(player_id, city) VALUES (?, ?)",
                                 (_pid(uid), completed_city))

    def elite_cleared(self, uid: str) -> set[int]:
        return {r["building_id"] for r in self._all(
            "SELECT building_id FROM elite_cleared WHERE player_id = ?", (_pid(uid),))}

    def mark_elite_cleared(self, uid: str, building_id: int) -> None:
        with self.transaction():
            self._db.execute("INSERT OR IGNORE INTO elite_cleared(player_id, building_id) "
                             "VALUES (?, ?)", (_pid(uid), building_id))

    def elite_done(self, uid: str) -> set[str]:
        return {r["city"] for r in self._all(
            "SELECT city FROM elite_done WHERE player_id = ?", (_pid(uid),))}

    # ---- activity runs ---------------------------------------------------------

    def active_run(self, uid: str, chapter: int):
        """(stage id, steps won) of the chapter's unfinished run, or None."""
        row = self._one("SELECT active_id, steps FROM active_runs "
                        "WHERE player_id = ? AND chapter = ?", (_pid(uid), chapter))
        return (row["active_id"], json.loads(row["steps"])) if row else None

    def set_active_run(self, uid: str, chapter: int, active_id: int, steps: list) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO active_runs(player_id, chapter, active_id, steps) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(player_id, chapter) DO UPDATE SET "
                "active_id = excluded.active_id, steps = excluded.steps",
                (_pid(uid), chapter, active_id, json.dumps(steps)))

    def clear_active_run(self, uid: str, chapter: int) -> None:
        with self.transaction():
            self._db.execute("DELETE FROM active_runs WHERE player_id = ? AND chapter = ?",
                             (_pid(uid), chapter))

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

    # ---- arena -------------------------------------------------------------------

    def arena_row(self, uid: str):
        """The player's (rank, award_at), or None until they first open the arena."""
        row = self._one("SELECT rank, award_at FROM arena WHERE player_id = ?", (_pid(uid),))
        return (row["rank"], row["award_at"]) if row else None

    def create_arena_row(self, uid: str, rank: int, award_at: int) -> None:
        with self.transaction():
            self._db.execute("INSERT INTO arena(player_id, rank, award_at) VALUES (?, ?, ?)",
                             (_pid(uid), rank, award_at))

    def set_arena_rank(self, uid: str, rank: int) -> None:
        with self.transaction():
            self._db.execute("UPDATE arena SET rank = ? WHERE player_id = ?",
                             (rank, _pid(uid)))

    def set_arena_award_at(self, uid: str, award_at: int) -> None:
        with self.transaction():
            self._db.execute("UPDATE arena SET award_at = ? WHERE player_id = ?",
                             (award_at, _pid(uid)))

    def arena_max_rank(self) -> int:
        row = self._one("SELECT MAX(rank) AS rank FROM arena")
        return row["rank"] or 0

    def arena_rows(self) -> list[dict]:
        """Every ranked player with the name and level the client shows."""
        return [dict(r) | {"uid": str(r["id"] + UID_OFFSET)} for r in self._all(
            "SELECT p.id, p.name, p.level, a.rank FROM arena a "
            "JOIN players p ON p.id = a.player_id ORDER BY a.rank")]

    def arena_row_at(self, rank: int):
        """The ranked player at `rank`, or None (the rank belongs to a bot)."""
        row = self._one("SELECT p.id, p.name, p.level, a.rank FROM arena a "
                        "JOIN players p ON p.id = a.player_id WHERE a.rank = ?", (rank,))
        return dict(row) | {"uid": str(row["id"] + UID_OFFSET)} if row else None

    def add_arena_log(self, uid: str, *, attacker: str, defender: str, a_combat: int,
                      d_combat: int, tp: str, is_win: bool, battle_log: str, now: int) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO arena_log(player_id, attacker, defender, a_combat, d_combat, "
                "tp, is_win, battle_log, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_pid(uid), attacker, defender, a_combat, d_combat, tp, int(is_win),
                 battle_log, now))

    def arena_log(self, uid: str, limit: int = 20) -> list[dict]:
        return [dict(r) | {"is_win": bool(r["is_win"])} for r in self._all(
            "SELECT attacker, defender, a_combat, d_combat, tp, is_win, battle_log "
            "FROM arena_log WHERE player_id = ? ORDER BY id DESC LIMIT ?", (_pid(uid), limit))]

    def add_arena_replay(self, key: str, data: dict, now: int) -> None:
        with self.transaction():
            self._db.execute("INSERT INTO arena_replays(key, data, created_at) VALUES (?, ?, ?)",
                             (key, json.dumps(data), now))

    def arena_replay(self, key: str):
        row = self._one("SELECT data FROM arena_replays WHERE key = ?", (key,))
        return json.loads(row["data"]) if row else None

    def purge_arena_replays(self, before: int) -> None:
        with self.transaction():
            self._db.execute("DELETE FROM arena_replays WHERE created_at < ?", (before,))

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
