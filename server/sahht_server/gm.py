"""Game-master operations: find ids, create an account, give anything to any account.

One implementation behind two front ends: the command line (`tools/admin.py`) and the
token-protected `admin` HTTP service (`gm_api.py`) the phone app uses. Everything works on a
`handlers.Services`.
"""

import dataclasses
import time

from . import player as player_module
from .handlers import Refused
from .rewards import CURRENCY_BY_TYPE, Loot, grant

GM_LEVEL = 120
GM_WALLET = {"coin": 10**9, "food": 10**9, "metal": 10**9, "silver": 10**9, "star": 10**6,
             "energy": 10**6, "crystal": 10**6, "adv_crystal": 10**6}
# config, name field, kind used by the apps, label shown to the person
SEARCHES = (("character_detail", "name", "card", "Thẻ tướng"),
            ("item", "name", "item", "Vật phẩm"),
            ("equip", "name", "equip", "Trang bị"),
            ("gem", "name", "gem", "Đá quý"))
LATE_CARD_MAX = 10**9


class GmError(Exception):
    """A request the tool cannot carry out; the message is meant for the person."""


def search(configs, text: str, limit: int = 30) -> list:
    """Groups `{kind, label, more, rows: [{id, name}]}` of every config row whose name holds `text`."""
    needle = text.strip().lower()
    if not needle:
        return []
    groups = []
    for config, field, kind, label in SEARCHES:
        rows = [(key, str(row.get(field, ""))) for key, row in configs.get(config).items()
                if isinstance(row, dict) and needle in str(row.get(field, "")).lower()]
        if rows:
            groups.append({"kind": kind, "label": label, "more": max(0, len(rows) - limit),
                           "rows": [{"id": key, "name": name} for key, name in rows[:limit]]})
    return groups


def _entries(texts, sep=":") -> list:
    """`["6500", "7900:3"]` -> [("6500", 1), ("7900", 3)]."""
    pairs = []
    for text in texts:
        ref, _, count = str(text).strip().partition(sep)
        if not ref:
            continue
        if count and not count.isdigit():
            raise GmError(f"số lượng không hợp lệ: '{text}'")
        pairs.append((ref, int(count) if count else 1))
    return pairs


def _known(configs, config: str, ref: str, label: str) -> None:
    if ref not in configs.get(config):
        raise GmError(f"không có {label} {ref}")


def parse_loot(configs, *, cards=(), items=(), equips=(), gems=(), currencies=()) -> Loot:
    """A `Loot` from `ID[:count]` lists (currencies are `name=amount`)."""
    loot = Loot()
    for ref, count in _entries(cards):
        _known(configs, "character_detail", ref, "tướng")
        loot.cards.extend([int(ref)] * count)
    for ref, count in _entries(items):
        _known(configs, "item", ref, "vật phẩm")
        loot.items[int(ref)] = loot.items.get(int(ref), 0) + count
    for ref, count in _entries(equips):
        _known(configs, "equip", ref, "trang bị")
        loot.equips.extend([int(ref)] * count)
    for ref, count in _entries(gems):
        loot.gems[ref] = loot.gems.get(ref, 0) + count
    names = set(CURRENCY_BY_TYPE.values())
    for name, amount in _entries(currencies, "="):
        if name not in names:
            raise GmError(f"tiền tệ '{name}' không có; dùng: {', '.join(sorted(names))}")
        loot.currencies[name] = loot.currencies.get(name, 0) + amount
    return loot


def summary(loot: Loot) -> str:
    parts = [f"{name} +{count}" for name, count in loot.currencies.items()]
    parts += [f"vật phẩm {item} x{count}" for item, count in loot.items.items()]
    parts += [f"thẻ tướng {c_id}" for c_id in loot.cards] + [f"trang bị {e}" for e in loot.equips]
    parts += [f"đá {key} x{count}" for key, count in loot.gems.items()]
    return ", ".join(parts) or "không có gì"


def find_player(svc, account: str) -> dict:
    player = svc.store.player_for_account(account)
    if player is None:
        raise GmError(f"không có tài khoản '{account}'")
    return player


def ensure_account(svc, account: str, password: str, level: int = GM_LEVEL) -> dict:
    """Create the account if missing, give it the starter kit, a full wallet and `level`."""
    created = svc.store.player_for_account(account) is None
    if created and not svc.store.create_account(account, password):
        raise GmError("không tạo được tài khoản (tên hoặc mật khẩu không hợp lệ)")
    player = find_player(svc, account)
    player_module.ensure_starter(svc, player)
    svc.store.set_level(player["uid"], level, 0, int(time.time()))
    svc.store.change_wallet(player["uid"], GM_WALLET)
    return {"uid": player["uid"], "created": created, "level": level}


def give(svc, account: str, loot: Loot, level: int = 0, allow_late: bool = False) -> str:
    """Grant the loot (and set the level when given). Heroes after the 2018 cut need
    `allow_late`, as everywhere else in the server."""
    player = find_player(svc, account)
    now = int(time.time())
    scope = dataclasses.replace(svc.scope, card_id_max=LATE_CARD_MAX) if allow_late else svc.scope
    try:
        with svc.store.transaction():
            if level:
                svc.store.set_level(player["uid"], level, 0, now)
            grant(dataclasses.replace(svc, scope=scope), player["uid"], loot, now)
    except Refused as refused:
        raise GmError(f"bị từ chối: {refused.body['msg']} (tướng sau 2018 cần cho phép tướng muộn)")
    return summary(loot)


def overview(svc, account: str) -> dict:
    player = find_player(svc, account)
    uid = player["uid"]
    return {"account": account, "uid": uid, "level": player["level"],
            "cards": len(svc.store.cards_for_player(uid)), "items": len(svc.store.items(uid)),
            "wallet": {k: v for k, v in sorted(svc.store.wallet(uid).items()) if v}}


def accounts(svc) -> list:
    return svc.store.players_overview()
