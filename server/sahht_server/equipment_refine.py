"""Equipment tempering (equip.equip_refine, equip.auto_refine; view 148).

The screen lists only pieces whose `equip.config.refine_id` is over 0. A roll moves both
of the piece's own attributes (`ability1`/`ability2`). Each attribute picks one of the
row's three bands `refine_{min|mid|max}_{1|2}` by weight, then a uniform integer inside
it, and the running total is clamped to that attribute's `refine_control_1/2` range.
`extra.equip_refine` holds the totals keyed by stat name, always with `hp`: the client's
shared equip renderer reads `equip_refine.hp` without a nil check.

Costs come from `refine_{min|mid|max}_cost` (`type` 1-3) per roll, so `sort` rolls cost
`sort` times as much. `is_save=0` rolls for the preview and keeps nothing; `is_save=1`
rolls again and stores, exactly the two calls the screen makes (its save button re-rolls).
The response always carries the change of this call for the two attributes.

`equip.auto_refine` estimates how many rolls reach both caps (assuming the best band) and
how many the player can pay for, then either rolls towards the cap (handle_sort 1) or
exactly the affordable number (handle_sort 2). Charging happens per roll; a roll the
player cannot pay for ends the batch.
"""

import math
import random

from . import equipment
from .handlers import Refused, Request, Services, fail, ok
from .rewards import CURRENCY_BY_TYPE, client_cache

TYPES = {1: "min", 2: "mid", 3: "max"}
SORTS = (1, 5, 10)
ATTRS = (1, 2)
REFINE_KEYS = ("hp", "patk", "matk", "def", "speed")


def _config(svc: Services, row: dict) -> dict:
    return svc.configs.get("equip").get(str(row["c_id"]), {})


def _refine_row(svc: Services, row: dict) -> dict | None:
    refine_id = _config(svc, row).get("refine_id", 0)
    found = svc.configs.get("equip_refine").get(str(refine_id)) if refine_id else None
    return found if isinstance(found, dict) else None


def _attrs(svc: Services, row: dict) -> tuple[str, str]:
    cfg = _config(svc, row)
    return (equipment.STAT_BY_ABILITY[cfg["ability1"]],
            equipment.STAT_BY_ABILITY[cfg["ability2"]])


def _roll(bands) -> int:
    """One weighted band `[low, high, weight]`, then a uniform integer inside it."""
    choices = [band for band in bands if len(band) >= 3 and band[2] > 0]
    total = sum(band[2] for band in choices)
    if not choices or total <= 0:
        return 0
    pick = random.uniform(0, total)
    for band in choices:
        pick -= band[2]
        if pick <= 0:
            return random.randrange(int(band[0]), int(band[1]) + 1)
    band = choices[-1]
    return random.randrange(int(band[0]), int(band[1]) + 1)


def _control(refine_row: dict, attr: int) -> tuple[int, int]:
    span = refine_row.get(f"refine_control_{attr}") or [0, 0]
    return int(span[0]), int(span[1])


def _max_gain(refine_row: dict, mode: str, attr: int) -> int:
    bands = refine_row.get(f"refine_{mode}_{attr}") or []
    return max((int(band[1]) for band in bands), default=0)


def _roll_once(refine_row: dict, mode: str, totals: dict, stats: tuple[str, str]) -> dict:
    """Roll both attributes once onto `totals`; returns the change of this roll."""
    change = {}
    for attr in ATTRS:
        stat = stats[attr - 1]
        delta = _roll(refine_row.get(f"refine_{mode}_{attr}") or [])
        low, high = _control(refine_row, attr)
        before = totals.get(stat, 0)
        totals[stat] = max(low, min(high, before + delta))
        change[stat] = change.get(stat, 0) + totals[stat] - before
    return change


def _costs(svc: Services, refine_row: dict, mode: str) -> dict:
    costs = {}
    for entry in refine_row.get(f"refine_{mode}_cost") or []:
        key = CURRENCY_BY_TYPE.get(entry[0])
        if key:
            costs[key] = costs.get(key, 0) + int(entry[2])
    return costs


def _multiply(costs: dict, times: int) -> dict:
    return {key: value * times for key, value in costs.items()}


def _totals(row: dict, stats: tuple[str, str]) -> dict:
    stored = equipment.extra(row).get("equip_refine") or {}
    return {key: int(stored.get(key, 0)) for key in REFINE_KEYS} | {
        stat: int(stored.get(stat, 0)) for stat in stats}


def _capped(refine_row: dict, totals: dict, stats: tuple[str, str]) -> bool:
    return all(totals.get(stats[attr - 1], 0) >= _control(refine_row, attr)[1]
               for attr in ATTRS)


def _batch(svc: Services, uid: str, refine_row: dict, mode: str, times: int,
           totals: dict, stats: tuple[str, str]) -> dict | None:
    """Pay and roll `times` times inside the caller's transaction, or refuse."""
    cost = _multiply(_costs(svc, refine_row, mode), times)
    if cost and not svc.store.change_wallet(uid, {k: -v for k, v in cost.items()}):
        raise Refused("error_not_enough", "Không đủ tài nguyên.")
    change = {}
    for _ in range(times):
        rolled = _roll_once(refine_row, mode, totals, stats)
        for stat, value in rolled.items():
            change[stat] = change.get(stat, 0) + value
    return change


def equip_refine(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    sort, mode, is_save = req.params.get("sort", ""), req.params.get("type", ""), \
        req.params.get("is_save", "0")
    row = svc.store.equipment_row(uid, equip_id)
    refine_row = _refine_row(svc, row) if row else None
    if refine_row is None:
        return fail("error_param", "Trang bị này không thể tẩy luyện.")
    if not sort.isdigit() or int(sort) not in SORTS or not mode.isdigit() or int(mode) not in TYPES:
        return fail("error_param", "Tham số không hợp lệ.")
    times, mode_name = int(sort), TYPES[int(mode)]
    stats = _attrs(svc, row)
    with svc.store.transaction():
        totals = _totals(row, stats)
        change = _batch(svc, uid, refine_row, mode_name, times, totals, stats)
        if is_save == "1":
            fields = equipment.extra(row) | {"equip_refine": totals}
            svc.store.set_equipment_extra(uid, equip_id, fields)
    data = {"equip_refine": {stat: change.get(stat, 0) for stat in stats}}
    if is_save == "1":
        data["_client_cache_update"] = client_cache(svc, uid, equips=[equip_id])
    return ok(data)


def _affordable(wallet: dict, costs: dict) -> int:
    limits = [wallet.get(key, 0) // value for key, value in costs.items() if value > 0]
    return min(limits) if limits else 10**9


def _need_times(refine_row: dict, mode: str, totals: dict, stats: tuple[str, str]) -> int:
    """Rolls to reach both caps assuming the best band, a deterministic estimate."""
    need = 0
    for attr in ATTRS:
        gain = _max_gain(refine_row, mode, attr)
        left = max(0, _control(refine_row, attr)[1] - totals.get(stats[attr - 1], 0))
        if gain > 0:
            need = max(need, math.ceil(left / gain))
    return need


def _auto_info(svc: Services, uid: str, row: dict, refine_row: dict, mode: str) -> dict:
    """(can_refine_info, max_refine_info) for the quick-temper prompt."""
    stats = _attrs(svc, row)
    totals = _totals(row, stats)
    per_roll = _costs(svc, refine_row, mode)
    need = _need_times(refine_row, mode, totals, stats)
    can = max(0, min(need, _affordable(svc.store.wallet(uid), per_roll)))
    missing = max(0, need - can)
    whole = _multiply(per_roll, can)
    extra = _multiply(per_roll, missing)
    can_info = {"need_times": can, "refine_stone_need": whole.get("refine_stone", 0),
                "metal_need": whole.get("metal", 0), "coin_need": whole.get("coin", 0)}
    max_info = {"need_times": need, "refine_stone_need": whole.get("refine_stone", 0),
                "metal_need": whole.get("metal", 0), "coin_need": whole.get("coin", 0),
                "metal_cost": extra.get("metal", 0),
                "refine_stone_cost": extra.get("refine_stone", 0)}
    return {"can_refine_info": can_info, "max_refine_info": max_info}


def auto_refine(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    mode, handle = req.params.get("type", ""), req.params.get("handle_sort", "")
    row = svc.store.equipment_row(uid, equip_id)
    refine_row = _refine_row(svc, row) if row else None
    if refine_row is None:
        return fail("error_param", "Trang bị này không thể tẩy luyện.")
    if not mode.isdigit() or int(mode) not in TYPES or handle not in ("1", "2"):
        return fail("error_param", "Tham số không hợp lệ.")
    info = _auto_info(svc, uid, row, refine_row, TYPES[int(mode)])
    if req.params.get("is_buy") != "1":
        return ok(info)
    stats = _attrs(svc, row)
    with svc.store.transaction():
        totals = _totals(row, stats)
        per_roll = _costs(svc, refine_row, TYPES[int(mode)])
        limit = info["can_refine_info" if handle == "2" else "max_refine_info"]["need_times"]
        change = {}
        for _ in range(limit):
            if _capped(refine_row, totals, stats):
                break
            if per_roll and not svc.store.change_wallet(
                    uid, {k: -v for k, v in per_roll.items()}):
                break
            rolled = _roll_once(refine_row, TYPES[int(mode)], totals, stats)
            for stat, value in rolled.items():
                change[stat] = change.get(stat, 0) + value
        svc.store.set_equipment_extra(uid, equip_id,
                                      equipment.extra(row) | {"equip_refine": totals})
    return ok({"equip_refine": {stat: change.get(stat, 0) for stat in stats},
               "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


HANDLERS = {
    ("api", "equip.equip_refine"): equip_refine,
    ("api", "equip.auto_refine"): auto_refine,
}
