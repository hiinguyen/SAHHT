"""Using bag items (item.use), by the `is_use` code of item.config.

Served kinds: 1 chest (box `use_effect[0]`; a second `use_effect` entry is the key or chest
item that is spent with it), 2 stamina, 4 crystal pack, 7 / 8 hero and equipment bag
expansion, 15 optional exchange (spend `use_num`, pick rewards from a box), 19 exp ball.
Every other kind needs a system this server does not run and answers `error_item`.

An optional exchange (game_item_info_pop_ext) shows the first two non-empty groups of its
box as lists; the client sends the 1-based picks as repeated `type_list` (first group) and
`type_list_1` (second group), exactly the group's `num` of them.
"""

import random
import time

from .handlers import Refused, Request, Services, fail, is_int, ok
from .player import CARD_BAG, EQUIP_BAG, expand_bag
from .rewards import Loot, client_cache, grant, merge_cache, open_box
from .shop import MAX_COUNT

USE_BOX, USE_STAMINA, USE_CRYSTAL, USE_CARD_BAG, USE_EQUIP_BAG = 1, 2, 4, 7, 8
USE_PICK, USE_EXP_BALL = 15, 19
PICK_PARAMS = ("type_list", "type_list_1")


def _unserved() -> Refused:
    return Refused("error_item", "Vật phẩm này chưa dùng được.")


def _box(svc: Services, effect: list) -> list:
    box = svc.configs.get("box").get(str(effect[0]))
    if box is None:
        raise _unserved()
    return box


def _chest_loot(svc: Services, effect: list, count: int) -> Loot:
    rng, loot = random.Random(), Loot()
    for _ in range(count):
        for entry in open_box(_box(svc, effect), rng):
            loot.add(*entry)
    return loot


def _picked_loot(svc: Services, req: Request, effect: list, count: int) -> Loot:
    groups = [g for g in _box(svc, effect) if g.get("num")][:len(PICK_PARAMS)]
    if not groups:
        raise _unserved()
    loot = Loot()
    for group, param in zip(groups, PICK_PARAMS):
        picks = req.lists.get(param, [])
        valid = (all(is_int(p) for p in picks) and len(set(picks)) == len(picks) == group["num"]
                 and all(1 <= int(p) <= len(group["reward"]) for p in picks))
        if not valid:
            raise Refused("error_param", "Xin chọn chính xác số lượng phần thưởng!")
        for pick in picks:
            kind, ref, amount = group["reward"][int(pick) - 1][:3]
            loot.add(kind, ref, amount * count)
    return loot


def _apply(svc: Services, req: Request, uid: str, item_id: int, detail: dict, count: int):
    """(loot, {item id: count to spend}) for using `count` of the item."""
    kind, effect = detail.get("is_use"), detail.get("use_effect") or [0]
    costs, loot = {item_id: count}, Loot()
    if kind == USE_BOX:
        if len(effect) > 1:
            costs[effect[1]] = count
        loot = _chest_loot(svc, effect, count)
    elif kind == USE_STAMINA:
        loot.action_point = effect[0] * count
    elif kind == USE_CRYSTAL:
        loot.currencies["crystal"] = effect[0] * count
    elif kind == USE_EXP_BALL:
        loot.currencies["exp_ball"] = effect[0] * count
    elif kind in (USE_CARD_BAG, USE_EQUIP_BAG):
        bag = CARD_BAG if kind == USE_CARD_BAG else EQUIP_BAG
        expand_bag(svc.store, uid, bag, effect[0] * count)
    elif kind == USE_PICK:
        costs[item_id] = max(detail.get("use_num") or 1, 1) * count
        loot = _picked_loot(svc, req, effect, count)
    else:
        raise _unserved()
    return loot, costs


def item_use(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    item_id, num = req.params.get("item_id", ""), req.params.get("num", "1")
    detail = svc.configs.get("item").get(item_id)
    if detail is None or not is_int(num) or not 1 <= int(num) <= MAX_COUNT:
        return fail("error_param", "Vật phẩm không hợp lệ.")
    with svc.store.transaction():
        loot, costs = _apply(svc, req, uid, int(item_id), detail, int(num))
        if not svc.store.change_items(uid, {key: -amount for key, amount in costs.items()}):
            raise Refused("error_item", "Không đủ vật phẩm.")
        granted = grant(svc, uid, loot, now)
    used = client_cache(svc, uid, items=list(costs))
    return ok({"effect": granted.reward, "_client_cache_update": merge_cache(granted.cache, used)})


HANDLERS = {("api", "item.use"): item_use}
