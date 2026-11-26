"""Request handlers for the game protocol.

Every handler takes (Request, Services) and returns a JSON-serialisable body.
Success is `status: 0`; failures use the string statuses the client switches on.
"""

import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from . import config_overrides, equipment, gems
from .player import ensure_starter, ensure_starter_equipment, guide_steps, seed_guides
from .progression import Rules
from .scope import Scope
from .store import ATTACK_SLOTS, Store

ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_]{6,20}$")
INT_RE = re.compile(r"[0-9]{1,9}")   # ASCII digits only: str.isdigit() also accepts "²"
PASSWD_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
CONFIG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Vietnam is UTC+7; the client reads this as an integer hour offset.
TIMEZONE = 7
SERVER_OPEN_TIME = 1700000000


@dataclass(frozen=True)
class Request:
    service: str
    method: str
    params: dict          # first value of each key
    base_url: str
    hostname: str
    lists: dict = field(default_factory=dict)   # every value of each key, in order


class ConfigCache:
    """Game configs (`<name>.config` JSON) loaded once, plus indexes derived from them."""

    def __init__(self, config_dir: Path):
        self._dir = Path(config_dir)
        self._cache: dict = {}
        # Re-entrant: building one derived index reads other configs through get().
        self._lock = threading.RLock()

    def get(self, name: str) -> dict:
        """A config as the server and the client use it: the APK's, with the server's edits."""
        return self.derived(("config", name),
                            lambda: config_overrides.apply(name, self.raw(name), self.get))

    def raw(self, name: str) -> dict:
        """A config exactly as the APK ships it."""
        return self.derived(("raw", name), lambda: self._load(name))

    def derived(self, key, build):
        with self._lock:
            if key not in self._cache:
                self._cache[key] = build()
            return self._cache[key]

    def _load(self, name: str) -> dict:
        path = self._dir / f"{name}.config"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


@dataclass(frozen=True)
class Services:
    store: Store
    config_dir: Path
    version_map: dict
    all_config_version: str
    configs: ConfigCache
    scope: Scope


def ok(data=None, **top):
    return {"status": 0, "msg": "", "data": {} if data is None else data, **top}


def fail(status, msg):
    return {"status": status, "msg": msg, "data": {}}


def is_int(value: str) -> bool:
    """A small non-negative integer from a request parameter."""
    return INT_RE.fullmatch(value) is not None


class Refused(Exception):
    """A check failed inside a store transaction: raising it rolls everything back,
    and the handler answers with `body`."""

    def __init__(self, status, msg):
        super().__init__(msg)
        self.body = fail(status, msg)

    @classmethod
    def of(cls, body: dict) -> "Refused":
        refused = cls(body["status"], body.get("msg", ""))
        refused.body = body
        return refused


def need_login():
    return fail("error_need_login", "Phiên đăng nhập đã hết hạn, xin đăng nhập lại.")


def version_map_etag(version_map: dict) -> str:
    canonical = json.dumps(version_map, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _credential(req: Request, key: str) -> str:
    # The client url-encodes these itself and the transport may encode again.
    return unquote(req.params.get(key, ""))


def server_list(req: Request, player: dict) -> list:
    return [{
        "server": player["server"],
        "server_name": "Máy chủ 1",
        "sort_id": 1,
        "uid": player["uid"],
        "level": player["level"],
        "flag": 0,
        "master_url": req.base_url,
        "domain": req.base_url,
        "lua_url": f"{req.base_url}/lua",
        "lua_ver_url": f"{req.base_url}/lua_ver",
        "dataosha_url": req.base_url,
        "chat_ip": req.hostname,
        "chat_port": "0",
        "open_time": SERVER_OPEN_TIME,
    }]


def _login_payload(req: Request, svc: Services, account: str, ticket: str) -> dict:
    player = svc.store.player_for_account(account)
    return {
        "rand_str": ticket,
        "ks": ticket,
        "server_list": server_list(req, player),
        "current_server": player["server"],
        "uid": player["uid"],
    }


def new_account(req: Request, svc: Services):
    account = f"fake_account_{secrets.token_hex(6)}"
    svc.store.create_account(account, None)
    ticket = svc.store.issue_ticket(account)
    data = _login_payload(req, svc, account, ticket)
    data["fake_account"] = account
    return ok(data)


def register(req: Request, svc: Services):
    account, passwd = _credential(req, "account"), _credential(req, "passwd")
    if not ACCOUNT_RE.match(account) or not PASSWD_RE.match(passwd):
        return fail("error_param", "Tên tài khoản hoặc mật khẩu không hợp lệ.")
    if not svc.store.create_account(account, passwd):
        return fail("error_account_exist", "Tài khoản đã tồn tại.")
    ticket = svc.store.issue_ticket(account)
    return ok(_login_payload(req, svc, account, ticket))


def login(req: Request, svc: Services):
    account, passwd = _credential(req, "account"), _credential(req, "passwd")
    if not svc.store.verify_password(account, passwd):
        return fail("error_account", "Sai tài khoản hoặc mật khẩu.")
    ticket = svc.store.issue_ticket(account)
    return ok(_login_payload(req, svc, account, ticket))


def get_user_server_list(req: Request, svc: Services):
    account = _credential(req, "account")
    ticket = req.params.get("rans", "")
    if not account or svc.store.account_for_ticket(ticket) != account:
        return need_login()
    return ok(_login_payload(req, svc, account, ticket))


def loading(req: Request, svc: Services):
    return ok(game_config_version=svc.version_map, all_config_version=svc.all_config_version)


def all_config(req: Request, svc: Services):
    name = req.params.get("config_name")
    if name is None:
        paths = sorted(svc.config_dir.glob("*.config"))
    elif CONFIG_NAME_RE.match(name) and (svc.config_dir / f"{name}.config").is_file():
        paths = [svc.config_dir / f"{name}.config"]
    else:
        return fail("error_param", "Tên cấu hình không hợp lệ.")
    return ok({p.stem: _served_config(svc, p) for p in paths})


def _served_config(svc: Services, path: Path) -> dict:
    """The config the client downloads: the server's edited copy when there is one.
    Unedited configs are read from disk each time, so the full dump stays out of the cache."""
    if path.stem in config_overrides.EDITS:
        return svc.configs.get(path.stem)
    return json.loads(path.read_text(encoding="utf-8"))


def lua_manifest(version: str):
    """Hot-update manifest: the APK already carries everything, so nothing differs."""
    return ok({"current_version": version, "different_files": []})


# ---- authenticated game API (service "api") -------------------------------

FORMATION_SLOTS = 10  # equip_pos keys "0".."9"; equipping indexes them unguarded
POSITION_NUM, ALTERNATE_NUM = 5, 3   # attack slots, bench slots the client shows
NAME_MAX = 16
EMPTY_POSITION = "-1"
FORMATION_COUNTER, DEFAULT_FORMATION = "formation", 1


def card_documents(svc: Services, uid: str) -> dict:
    """Every card of the player as the client reads it, keyed by card id."""
    rules = Rules.load(svc.configs)
    level = svc.store.player_for_uid(uid)["level"]
    docs = {c["id"]: rules.card_document(c, level) for c in svc.store.cards_for_player(uid)}
    return equipment.add_bound_equipment(svc.configs, svc.store.equipment_rows(uid), docs)


def alignment(cards: list) -> list:
    """[[attack ids by position], [bench ids by position]]; "-1" marks an empty position.
    The client reads both rows positionally (game_data.setTeamByJsonData)."""
    attack, bench = [EMPTY_POSITION] * ATTACK_SLOTS, [EMPTY_POSITION] * ALTERNATE_NUM
    for c in cards:
        slot = c["slot"]
        if slot is not None and slot < ATTACK_SLOTS:
            attack[slot] = c["id"]
        elif slot is not None and slot - ATTACK_SLOTS < ALTERNATE_NUM:
            bench[slot - ATTACK_SLOTS] = c["id"]
    return [attack, bench]


def owned_formations(svc: Services) -> list:
    """formation.config's layouts; each leaves a different cell empty and all are free."""
    return sorted(int(k) for k in svc.configs.get("formation") if k.isdigit()) or [1]


def current_formation(svc: Services, uid: str) -> int:
    return svc.store.counter(uid, FORMATION_COUNTER) or DEFAULT_FORMATION


def formation_document(svc: Services, uid: str) -> dict:
    return {"current": current_formation(svc, uid), "own": owned_formations(svc)}


def formation_cards(cards: list) -> list:
    """Cards in attack positions, in slot order."""
    return sorted((c for c in cards if c["slot"] is not None and c["slot"] < ATTACK_SLOTS),
                  key=lambda c: c["slot"])


def team_combat(svc: Services, uid: str) -> int:
    rules = Rules.load(svc.configs)
    cards = svc.store.cards_for_player(uid)
    level = svc.store.player_for_uid(uid)["level"]
    rows = svc.store.equipment_rows(uid)
    by_id = {e["id"]: e for e in rows}
    equipped = {}
    for position, _, equip_id in svc.store.equipment_positions(uid):
        equipped.setdefault(position, []).append(equip_id)
    jewels = gems.keys_by_position(svc.store.gem_positions(uid))
    bound = equipment.bound_by_card(svc.configs, rows)
    docs, fates = {}, {}
    for card in cards:
        if card["slot"] is None:
            continue
        doc = rules.card_document(card, level)
        stats = gems.add_stats(
            equipment.bonus(svc.configs, equipped.get(card["slot"], []), by_id),
            gems.bonus(svc.configs, jewels.get(card["slot"], [])))
        docs[card["slot"]] = equipment.with_bonus(doc, stats)
        fates[card["slot"]] = equipment.fate_percent(
            svc.configs, list(bound.get(card["id"], {}).values()), by_id)
    return rules.team_combat(docs, fates)


def item_stacks(svc: Services, uid: str) -> dict:
    """The bag as the client stores it: item id -> list of stack counts."""
    details = svc.configs.get("item")
    bag = {}
    for item_id, count in svc.store.items(uid).items():
        stack = details.get(str(item_id), {}).get("stack") or count
        bag[str(item_id)] = [min(stack, count - i) for i in range(0, count, stack)]
    return bag


def mark_user_login(req: Request, svc: Services, player: dict):
    ensure_starter(svc, player)
    ensure_starter_equipment(svc, player)
    seed_guides(svc, player["uid"])   # accounts that cleared stages before a guide rule existed
    return ok({"mk": secrets.token_hex(8)})


def cards_open(req: Request, svc: Services, player: dict):
    # Every other cards.open setter returns early on a missing key, so keys are
    # only sent once their exact shape is known; a wrong shape is a Lua error.
    ensure_starter(svc, player)
    ensure_starter_equipment(svc, player)
    uid = player["uid"]
    return ok({
        "cards": card_documents(svc, uid),
        "alignment": alignment(svc.store.cards_for_player(uid)),
        "equip_pos": equipment.grid(svc.store.equipment_positions(uid)),
        # Gem stacks (key -> count) and where they sit; gemInGemPos indexes every
        # position unguarded whenever a gem screen opens, so the grid is always complete.
        "gem": svc.store.gems(uid),
        "gem_pos": gems.grid(svc.store.gem_positions(uid)),
        # God-field gear grids (no system yet): drawing any equipment icon indexes them.
        **{f"equip_pos_{n}": equipment.grid(()) for n in (1, 2, 3)},
        # Cheer-formation gear (no system yet): equipInBonus reads keys "200".."209".
        "bonus_equip_pos": {str(i): [0] * equipment.SLOTS for i in range(200, 210)},
        "formation": formation_document(svc, uid),
        "items": item_stacks(svc, uid),
        "equip": equipment.documents(svc.store.equipment_rows(uid)),
        "battle_card_num": {"position_num": POSITION_NUM, "alternate_num": ALTERNATE_NUM},
        # The cheer-formation system does not exist yet, but every hero card drawn
        # outside the formation screen (gacha results, lists) iterates these with pairs().
        "formation_bonus": {}, "formation_bonus_addition": {},
        # God-field lineups (no system yet): game_data.godheroInTeamById iterates
        # lineups "1".."3" for every hero card drawn, and the client starts with none.
        "god_field_ids": {str(i): [EMPTY_POSITION] * ATTACK_SLOTS for i in (1, 2, 3)},
    })


# alert name -> (svc, uid, now) -> value. user.main_page replaces the client's whole `alerts`
# table, so every module that lights a dot registers here; values must be real booleans.
ALERT_PROVIDERS: dict = {}


def main_alerts(svc: Services, uid: str) -> dict:
    now = int(time.time())
    return {"is_double": False,
            **{name: provider(svc, uid, now) for name, provider in ALERT_PROVIDERS.items()}}


def user_main_page(req: Request, svc: Services, player: dict):
    return ok({
        "arena_rank": 1, "arena_point": 0, "buy_ap_times": 0,
        "combat": team_combat(svc, player["uid"]),  # getChangedCombat() does arithmetic on it
        "timezone": TIMEZONE, "alerts": main_alerts(svc, player["uid"]), "resource": {},
        "notices": [], "actives": {},
        # Without this, returning to the main scene compares a missing top-level
        # all_config_version with the stored one and forces a re-login (game_scene:777).
        # The configs are the APK's own and never change.
        "config_refresh": 0,
        # Every view id the client must hide. game_data.updateInreviewByJsonData resets
        # its list on each reply, so the whole list goes every time.
        "inreview": svc.scope.closed_views(),
    })


def user_guide(req: Request, svc: Services, player: dict):
    """Tutorial progress; the client reads it back from user_status.guide."""
    team, step = req.params.get("guide_team", ""), req.params.get("guide_id", "")
    steps = guide_steps(svc).get(team)
    if steps is None or not is_int(step):
        return fail("error_param", "Tham số không hợp lệ.")
    svc.store.advance_guide(player["uid"], team, min(int(step), steps[1]))
    seed_guides(svc, player["uid"])
    return ok()


def user_rename(req: Request, svc: Services, player: dict):
    name = unquote(req.params.get("show_name", "")).strip()
    if not name or len(name) > NAME_MAX or any(ch in name for ch in "<>&\"\\"):
        return fail("error_param", "Tên không hợp lệ.")
    svc.store.rename(player["uid"], name)
    return ok()


# Public login-service methods: (Request, Services) -> body.
LOGIN_HANDLERS = {
    "new_account": new_account,
    "register": register,
    "login": login,
    "get_user_server_list": get_user_server_list,
    "loading": loading,
}

# Session-guarded methods: (Request, Services, player) -> body.
SESSION_HANDLERS = {
    ("login", "mark_user_login"): mark_user_login,
    ("api", "cards.open"): cards_open,
    ("api", "user.main_page"): user_main_page,
    ("api", "user.guide"): user_guide,
    ("api", "user.rename"): user_rename,
}
