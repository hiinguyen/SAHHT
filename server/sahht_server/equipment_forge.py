"""Equipment forging (equip.equip_forge_index/level/refresh; view 167).

A piece has `equip_forge_level = {lv, exp}` (top row of `equip_set_level`, 10) and
`equip_forge`, a map of `equip_set_random` row id to `{stat: value}`; `equip_forge_temp`
is a refresh waiting to be saved. The screen shows the stored values as they are, so the
server recomputes them whenever the forge level rises.

Forging stones are `small/middle/high_forge_stone` (10/100/500 experience each); raising
a level costs `equip_set_level[lv + 1].need` and the remainder carries into the next level.
A refresh costs the row of `equip_set_cost[sort + 1]` (10 stones of that grade plus metal)
and rolls three distinct properties whose `equip_sort` contains the piece's sort, weighted
by the row's `weight`. Values follow the client's `getNextProperty`:
`floor(ability + equip_set_level[lv].add<quality> * rate)` for sorts 1-5 and
`ability + add<quality> * rate` for sorts 6-10, with the rates of `equip_set_rate`.
"""

import math
import random

from . import equipment
from .handlers import Refused, Request, Services, fail, ok
from .rewards import CURRENCY_BY_TYPE, client_cache

STONES = ("small_forge_stone", "middle_forge_stone", "high_forge_stone")
STONE_EXP = (10, 100, 500)
MODULUS = (1, 0.9, 0.6, 0.9, 6)     # equip_set_rate rows 1-5
FLAT_SORTS = 5                      # sorts 1-5 use MODULUS; 6-10 use the quality rates
PROPERTIES = 3


def _config(svc: Services, row: dict) -> dict:
    return svc.configs.get("equip").get(str(row["c_id"]), {})


def _fields(row: dict) -> dict:
    return equipment.extra(row)


def _level_table(svc: Services) -> dict:
    return svc.configs.get("equip_set_level")


def _max_level(svc: Services) -> int:
    return max((int(key) for key in _level_table(svc) if key.isdigit()), default=0)


def _quality_rates(svc: Services) -> list:
    rows = svc.configs.get("equip_set_rate")
    return [rows[str(i)].get("rate_num", 0) for i in range(6, 10)]


def _value(svc: Services, property_row: dict, level: int) -> int | float:
    """The client's getNextProperty for the level the properties are shown at."""
    add = _level_table(svc).get(str(level), {}).get(f"add{property_row.get('quality', 1)}", 0)
    ability = property_row.get("ability", 0)
    sort = property_row.get("sort", 0)
    if 1 <= sort <= FLAT_SORTS:
        return math.floor(ability + add * MODULUS[sort - 1])
    rates = _quality_rates(svc)
    quality = property_row.get("quality", 1)
    rate = rates[quality - 1] if 0 < quality <= len(rates) else 0
    return round(ability + add * rate, 4)


def _candidates(svc: Services, cfg: dict) -> list:
    sort = cfg.get("sort", 0)
    rows = svc.configs.get("equip_set_random")
    return [(key, row) for key, row in rows.items()
            if isinstance(row, dict) and sort in (row.get("equip_sort") or [])
            and row.get("weight", 0) > 0]


def _pick(svc: Services, cfg: dict) -> list:
    """Three distinct property ids, drawn by weight."""
    pool = _candidates(svc, cfg)
    chosen = []
    while pool and len(chosen) < PROPERTIES:
        total = sum(row.get("weight", 0) for _, row in pool)
        pick = random.uniform(0, total)
        index = 0
        for position, (_, row) in enumerate(pool):
            pick -= row.get("weight", 0)
            if pick <= 0:
                index = position
                break
        chosen.append(pool.pop(index)[0])
    return chosen


def _roll(svc: Services, cfg: dict, level: int) -> dict:
    rows = svc.configs.get("equip_set_random")
    rolled = {}
    for property_id in _pick(svc, cfg):
        row = rows[property_id]
        stat = equipment.STAT_BY_ABILITY.get(row.get("sort", 0), "hp")
        rolled[property_id] = {stat: _value(svc, row, level)}
    return rolled


def _spend(svc: Services, uid: str, costs: dict) -> None:
    if costs and not svc.store.change_wallet(uid, {k: -v for k, v in costs.items()}):
        raise Refused("error_not_enough", "Không đủ đá rèn hoặc sắt.")


def _cost(svc: Services, sort: int) -> dict:
    row = svc.configs.get("equip_set_cost").get(str(sort + 1), {})
    costs = {}
    for entry in row.get("cost", []):
        key = CURRENCY_BY_TYPE.get(entry[0])
        if key:
            costs[key] = costs.get(key, 0) + int(entry[2])
    return costs


def equip_forge_index(req: Request, svc: Services, player: dict):
    row = svc.store.equipment_row(player["uid"], req.params.get("equip_id", ""))
    if row is None:
        return fail("error_param", "Trang bị không hợp lệ.")
    return ok(equipment.document(row))


def equip_forge_level(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    parts = req.params.get("forge_stone", "").split("_")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None or len(parts) != 3 or any(not part.isdigit() for part in parts):
        return fail("error_param", "Tham số không hợp lệ.")
    counts = [int(part) for part in parts]
    added = sum(count * experience for count, experience in zip(counts, STONE_EXP))
    if added <= 0:
        return fail("error_param", "Hãy thêm đá rèn.")
    fields = _fields(row)
    state = fields.get("equip_forge_level") or {"lv": 0, "exp": 0}
    level, exp = int(state.get("lv", 0)), int(state.get("exp", 0)) + added
    cap = _max_level(svc)
    if level >= cap:
        return fail("error_max_level", "Trang bị đã rèn đến cấp tối đa.")
    while level < cap:
        need = _level_table(svc).get(str(level + 1), {}).get("need", 0)
        if exp < need:
            break
        exp -= need
        level += 1
    if level >= cap:
        exp = 0
    with svc.store.transaction():
        _spend(svc, uid, {STONES[i]: count for i, count in enumerate(counts) if count})
        forge = fields.get("equip_forge") or {}
        if forge:
            rows = svc.configs.get("equip_set_random")
            forge = {key: {equipment.STAT_BY_ABILITY.get(rows[key].get("sort", 0), "hp"):
                           _value(svc, rows[key], level)}
                     for key in forge if key in rows}
        # The refresh popup reads `next(equip_forge)` with no nil check, so the map is
        # always sent once the piece has a forge level, even before the first refresh.
        fields = fields | {"equip_forge_level": {"lv": level, "exp": exp},
                           "equip_forge": forge}
        svc.store.set_equipment_extra(uid, equip_id, fields)
    return ok({"_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


def equip_forge_refresh(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    sort, is_save = req.params.get("sort", ""), req.params.get("is_save", "0")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None or not sort.isdigit() or int(sort) not in (0, 1, 2):
        return fail("error_param", "Tham số không hợp lệ.")
    fields = _fields(row)
    level = int((fields.get("equip_forge_level") or {}).get("lv", 0))
    if level <= 0:
        return fail("error_param", "Hãy rèn đến cấp 1 trước.")
    if is_save == "1":
        temp = fields.get("equip_forge_temp")
        if not isinstance(temp, dict) or not temp:
            return fail("error_param", "Không có thuộc tính nào đang chờ.")
        fields = {k: v for k, v in fields.items() if k != "equip_forge_temp"}
        fields["equip_forge"] = temp
        svc.store.set_equipment_extra(uid, equip_id, fields)
        return ok({"_client_cache_update": client_cache(svc, uid, equips=[equip_id])})
    cfg = _config(svc, row)
    with svc.store.transaction():
        _spend(svc, uid, _cost(svc, int(sort)))
        fields = fields | {"equip_forge_temp": _roll(svc, cfg, level)}
        svc.store.set_equipment_extra(uid, equip_id, fields)
    return ok({"_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


HANDLERS = {
    ("api", "equip.equip_forge_index"): equip_forge_index,
    ("api", "equip.equip_forge_level"): equip_forge_level,
    ("api", "equip.equip_forge_refresh"): equip_forge_refresh,
}
