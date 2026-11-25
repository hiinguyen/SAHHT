"""Equipment actions: enhancing (factory.equip_levelup, the one-key enhance), evolving
(equip.evolution), refining (equip.st_levelup) and selling.

Enhancing follows the client's own cost loop (equipment_strengthen.lua): for every level
from the current one to the target, `equip_strongthen.config[level].metal` is multiplied
by `quality<quality>` percent. The level is capped by both the table (251 rows) and the
player level.
"""

import random
import time

from . import equipment
from .handlers import Refused, Request, Services, fail, ok
from .rewards import client_cache, pay

METAL = "metal"
METALCORE = "metalcore"
MAX_REFINE_LEVEL = 10
MATERIAL_ITEM, MATERIAL_EQUIP = 6, 7   # the first number of an equip_material entry
MATERIAL_SLOTS = 3


def _equip_config(svc: Services, row: dict) -> dict:
    return svc.configs.get("equip").get(str(row["c_id"]), {})


def _level_cap(svc: Services, player: dict) -> int:
    return min(len(svc.configs.get("equip_strongthen")), player["level"])


def _level_cost(svc: Services, row: dict, from_level: int, levels: int) -> int:
    """The metal the client's strength screen would charge for these levels."""
    table = svc.configs.get("equip_strongthen")
    quality = _equip_config(svc, row).get("quality", 0)
    cost = 0
    for level in range(from_level, from_level + levels):
        step = table.get(str(level), {})
        coefficient = step.get(f"quality{quality}", 100) / 100
        cost += int(step.get("metal", 0) * coefficient)
    return cost


def factory_equip_levelup(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("magor", "")
    levels = req.params.get("lvs", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None or not levels.isdigit() or int(levels) <= 0:
        return fail("error_param", "Trang bị không hợp lệ.")
    levels = int(levels)
    cap = _level_cap(svc, player)
    target = min(row["lv"] + levels, cap)
    if target <= row["lv"]:
        return fail("error_max_level", "Trang bị đã đạt cấp tối đa.")
    cost = _level_cost(svc, row, row["lv"], target - row["lv"])
    with svc.store.transaction():
        pay(svc, uid, {METAL: cost})
        svc.store.set_equipment_level(uid, equip_id, target)
    return ok({"reward": {}, "_client_cache_update": client_cache(
        svc, uid, equips=[equip_id])})


def all_equip_levelup_auto(req: Request, svc: Services, player: dict):
    """Raise every piece as far as the current metal allows, cheapest first."""
    uid, now = player["uid"], int(time.time())
    rows = sorted(svc.store.equipment_rows(uid), key=lambda row: int(row["id"]))
    cap = _level_cap(svc, player)
    metal = svc.store.wallet(uid).get(METAL, 0)
    targets, spent = {}, 0
    for row in rows:
        level = row["lv"]
        while level < cap:
            cost = _level_cost(svc, row, level, 1)
            if spent + cost > metal:
                break
            spent += cost
            level += 1
        if level > row["lv"]:
            targets[row["id"]] = level
    if not targets:
        return ok({"reward": {}, "_client_cache_update": {
            "equip": {"_equip": {"update": {}, "remove": []}}}})
    with svc.store.transaction():
        pay(svc, uid, {METAL: spent})
        for equip_id, level in targets.items():
            svc.store.set_equipment_level(uid, equip_id, level)
    return ok({"reward": {}, "_client_cache_update": client_cache(
        svc, uid, equips=list(targets))})


def _evolution_recipe(svc: Services, row: dict):
    """(next c_id, equip_evolution row) for an evolvable piece, else None."""
    cfg = _equip_config(svc, row)
    recipe = svc.configs.get("equip_evolution").get(str(cfg.get("evolution_id")))
    next_c_id = cfg.get("evolution")
    if not next_c_id or not isinstance(recipe, dict):
        return None
    return next_c_id, recipe


def _spend_materials(svc: Services, uid: str, selected: dict, recipe: dict):
    """Consume the recipe's items and spare copies; returns the removed equipment ids.

    A spare copy is a piece of the wanted config that is not the evolving one and not
    worn, the same count the client's own `getEquipCountByCid` shows. The lowest level
    goes first so the best pieces stay.
    """
    worn = {equip_id for _, _, equip_id in svc.store.equipment_positions(uid)}
    spares = sorted((e for e in svc.store.equipment_rows(uid)
                     if e["id"] != selected["id"] and e["id"] not in worn),
                    key=lambda e: (e["lv"], int(e["id"])))
    items, removed = {}, []
    for slot in range(1, MATERIAL_SLOTS + 1):
        for kind, material_id, count in recipe.get(f"equip_material_{slot}", []):
            if kind == MATERIAL_ITEM:
                items[material_id] = items.get(material_id, 0) + count
                continue
            taken = [e["id"] for e in spares
                     if e["c_id"] == material_id and e["id"] not in removed][:count]
            if kind != MATERIAL_EQUIP or len(taken) < count:
                raise Refused("error_not_enough", "Nguyên liệu tiêu hao không đủ!")
            removed.extend(taken)
    if items and not svc.store.change_items(uid, {i: -n for i, n in items.items()}):
        raise Refused("error_not_enough", "Nguyên liệu tiêu hao không đủ!")
    if removed:
        svc.store.remove_equipment(uid, removed)
    return items, removed


def equip_evolution(req: Request, svc: Services, player: dict):
    """Evolve a piece in place: same id and level, the next quality's config."""
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    if req.params.get("is_buy"):
        return fail("error_not_open", "Tính năng chưa mở.")   # view 170, paid with gold
    row = svc.store.equipment_row(uid, equip_id)
    found = _evolution_recipe(svc, row) if row else None
    if found is None:
        return fail("error_param", "Trang bị này không thể tiến hóa!")
    next_c_id, recipe = found
    with svc.store.transaction():
        pay(svc, uid, {METAL: recipe.get("metal", 0)})
        items, removed = _spend_materials(svc, uid, row, recipe)
        svc.store.set_equipment_config(uid, equip_id, next_c_id)
    return ok({"_client_cache_update": client_cache(
        svc, uid, equips=[equip_id], removed_equips=removed, items=items)})


def equip_st_levelup(req: Request, svc: Services, player: dict):
    """Refine a piece one level. Cost and odds come from the next level's row of
    `equip_st`; a failure still costs and drops the piece to the current row's `false_back`.
    The two fixed fields the client reads are `data.success` and the cache update."""
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None:
        return fail("error_param", "Trang bị không hợp lệ.")
    level = row.get("st_lv", 0)
    if level >= MAX_REFINE_LEVEL:
        return fail("error_max_level", "Trang bị tinh luyện đã đạt cấp tối đa!")
    table = svc.configs.get("equip_st")
    step = table.get(str(level + 1), {})
    fall_back = table.get(str(level), {}).get("false_back", 0) if level else 0
    with svc.store.transaction():
        pay(svc, uid, {METAL: step.get("metal", 0), METALCORE: step.get("metalcore", 0)})
        success = random.randrange(100) < step.get("rate", 0)
        svc.store.set_equipment_st_level(uid, equip_id, level + 1 if success else fall_back)
    return ok({"success": "true" if success else "false",
               "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


def equip_sell(req: Request, svc: Services, player: dict):
    """Sell bag equipment for the config's sell_metal; equipped pieces are refused."""
    uid = player["uid"]
    ids = [v for v in req.lists.get("equip", []) if v]
    if not ids or len(set(ids)) != len(ids):
        return fail("error_param", "Trang bị không hợp lệ.")
    rows = {e["id"]: e for e in svc.store.equipment_rows(uid)}
    if any(equip_id not in rows for equip_id in ids):
        return fail("error_param", "Trang bị không hợp lệ.")
    equipped = {equip_id for _, _, equip_id in svc.store.equipment_positions(uid)}
    if any(equip_id in equipped for equip_id in ids):
        return fail("error_param", "Trang bị đang sử dụng.")
    sell_metal = sum(_equip_config(svc, rows[equip_id]).get("sell_metal", 0)
                     for equip_id in ids)
    with svc.store.transaction():
        if not svc.store.remove_equipment(uid, ids):
            return fail("error_param", "Trang bị không hợp lệ.")
        svc.store.change_wallet(uid, {METAL: sell_metal})
    return ok({"sell_metal": sell_metal, "_client_cache_update": client_cache(
        svc, uid, removed_equips=ids)})


HANDLERS = {
    ("api", "factory.equip_levelup"): factory_equip_levelup,
    ("api", "equip.all_equip_levelup_auto"): all_equip_levelup_auto,
    ("api", "equip.evolution"): equip_evolution,
    ("api", "equip.st_levelup"): equip_st_levelup,
    ("api", "equip.sell"): equip_sell,
}
