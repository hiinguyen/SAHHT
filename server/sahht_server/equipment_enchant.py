"""Equipment enchanting (equip.enchant, equip.save_init_enchant, equip.remove_enchant,
equip.auto_enchant; view 131).

Each attempt costs `enchant.config[quality].piece` units of `enchant` (Mảnh Ma Quang).
Weapons and accessories (`equip.config.sort` 1-2) get one attack element key
(`fire`/`water`/`wind`/`earth`); armor and boots (sort 3-4) get two defence keys
(`*_dfs`). The count matters: the screen reads the max cap from `atk_max` when the piece
has one key and from `def_max` when it has two.

The first enchant rolls the keys and values into `extra.enchant_pending` and returns them
as `data.enchant_attrs`; saving copies them into `is_enchant`/`atts`, cancelling drops
them. Every later enchant adds a uniform `1..atk_rate/def_rate` to each key, capped at
`atk_max`/`def_max`. Removing the enchant clears the state and refunds the pieces spent on
the piece (`extra._enchant_spent`); the client shows it as `data.enchant`.

Elemental stats are stored and shown but the battle engine has no elemental attributes
yet, so they do not reach combat power.
"""

import math
import random

from . import equipment
from .handlers import Refused, Request, Services, fail, ok
from .rewards import client_cache

ATTACK_KEYS = ("fire", "water", "wind", "earth")
DEFENCE_KEYS = ("fire_dfs", "water_dfs", "wind_dfs", "earth_dfs")
ATTACK_SORTS = (1, 2)
DEFENCE_SORTS = (3, 4)
CURRENCY = "enchant"
PER_VALUE = 60   # the per-attempt gain the quick-enchant prompt estimates with


def _config(svc: Services, row: dict) -> dict:
    return svc.configs.get("equip").get(str(row["c_id"]), {})


def _piece_cost(svc: Services, cfg: dict) -> int:
    row = svc.configs.get("enchant").get(str(cfg.get("quality", 0)))
    return row.get("piece", 0) if isinstance(row, dict) else 0


def _keys(cfg: dict) -> tuple[str, ...]:
    sort = cfg.get("sort", 0)
    if sort in ATTACK_SORTS:
        return (random.choice(ATTACK_KEYS),)
    if sort in DEFENCE_SORTS:
        return tuple(random.sample(DEFENCE_KEYS, 2))
    return ()


def _max_value(svc: Services, cfg: dict, count: int) -> int:
    row = svc.configs.get("enchant").get(str(cfg.get("quality", 0))) or {}
    return row.get("def_max" if count > 1 else "atk_max", 0)


def _rate(svc: Services, cfg: dict) -> int:
    row = svc.configs.get("enchant").get(str(cfg.get("quality", 0))) or {}
    span = row.get("def_rate" if cfg.get("sort") in DEFENCE_SORTS else "atk_rate") or [1, 1]
    return max(1, int(span[-1]))


def _gain(svc: Services, cfg: dict) -> int:
    return random.randrange(1, _rate(svc, cfg) + 1)


def _fields(row: dict) -> dict:
    return equipment.extra(row)


def _spend(svc: Services, uid: str, cost: int) -> None:
    if cost and not svc.store.change_wallet(uid, {CURRENCY: -cost}):
        raise Refused("error_not_enough", "Mảnh Ma Quang không đủ.")


def _save(svc: Services, uid: str, equip_id: str, fields: dict) -> None:
    svc.store.set_equipment_extra(uid, equip_id, fields)


def equip_enchant(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None:
        return fail("error_param", "Trang bị không hợp lệ.")
    cfg = _config(svc, row)
    cost = _piece_cost(svc, cfg)
    fields = _fields(row)
    atts = fields.get("atts") or {}
    with svc.store.transaction():
        _spend(svc, uid, cost)
        spent = int(fields.get("_enchant_spent", 0)) + cost
        if atts:
            cap = _max_value(svc, cfg, len(atts))
            change = {key: min(cap, atts[key] + _gain(svc, cfg)) - atts[key] for key in atts}
            total = {key: atts[key] + change[key] for key in atts}
            _save(svc, uid, equip_id, fields | {"atts": total, "_enchant_spent": spent})
            return ok({"cur_atts": total, "enchant_attrs": change,
                       "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})
        keys = _keys(cfg)
        if not keys:
            raise Refused("error_param", "Trang bị này không thể phù phép.")
        rolled = {key: _gain(svc, cfg) for key in keys}
        _save(svc, uid, equip_id, fields | {"enchant_pending": rolled,
                                            "_enchant_spent": spent})
    return ok({"enchant_attrs": rolled})


def save_init_enchant(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None:
        return fail("error_param", "Trang bị không hợp lệ.")
    fields = _fields(row)
    pending = fields.get("enchant_pending") or {}
    if not pending:
        return fail("error_param", "Không có kết quả phù phép nào đang chờ.")
    fields = {k: v for k, v in fields.items() if k != "enchant_pending"}
    if req.params.get("is_save") == "1":
        fields = fields | {"is_enchant": True, "atts": pending}
        atts = pending
    else:
        atts = fields.get("atts") or {}
    _save(svc, uid, equip_id, fields)
    return ok({"cur_atts": atts, "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


def remove_enchant(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None:
        return fail("error_param", "Trang bị không hợp lệ.")
    fields = _fields(row)
    if not fields.get("is_enchant"):
        return fail("error_param", "Trang bị chưa được phù phép.")
    refund = int(fields.get("_enchant_spent", 0))
    fields = {k: v for k, v in fields.items()
              if k not in ("is_enchant", "atts", "enchant_pending", "_enchant_spent")}
    with svc.store.transaction():
        _save(svc, uid, equip_id, fields)
        if refund:
            svc.store.change_wallet(uid, {CURRENCY: refund})
    return ok({"enchant": refund, "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


def _need_times(svc: Services, cfg: dict, atts: dict) -> int:
    cap = _max_value(svc, cfg, len(atts))
    return max((math.ceil(max(0, cap - value) / PER_VALUE) for value in atts.values()),
               default=0)


def _auto_roll(svc: Services, cfg: dict, atts: dict) -> dict:
    cap = _max_value(svc, cfg, len(atts))
    return {key: min(cap, value + _gain(svc, cfg)) for key, value in atts.items()}


def auto_enchant(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    sort = req.params.get("sort", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None or not _fields(row).get("is_enchant"):
        return fail("error_param", "Trang bị chưa được phù phép.")
    cfg = _config(svc, row)
    fields = _fields(row)
    atts = fields.get("atts") or {}
    cost = _piece_cost(svc, cfg)
    need = _need_times(svc, cfg, atts)
    balance = svc.store.wallet(uid).get(CURRENCY, 0)
    can = cost and min(need, balance // cost) or 0
    if sort == "-1":
        return ok({"need_times": need, "can_times": can, "enchant_cost": cost,
                   "need_enchant": cost, "cur_atts": atts})
    if sort not in ("0", "1", "2"):
        return fail("error_param", "Tham số không hợp lệ.")
    times = need if sort in ("0", "2") else can
    with svc.store.transaction():
        done = 0
        for _ in range(times):
            if cost and not svc.store.change_wallet(uid, {CURRENCY: -cost}):
                break
            atts = _auto_roll(svc, cfg, atts)
            done += 1
        if done:
            fields = fields | {"atts": atts,
                               "_enchant_spent": int(fields.get("_enchant_spent", 0)) + cost * done}
            _save(svc, uid, equip_id, fields)
    return ok({"cur_atts": atts, "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


HANDLERS = {
    ("api", "equip.enchant"): equip_enchant,
    ("api", "equip.save_init_enchant"): save_init_enchant,
    ("api", "equip.remove_enchant"): remove_enchant,
    ("api", "equip.auto_enchant"): auto_enchant,
}
