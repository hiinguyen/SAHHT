"""Hero and equipment exchange ("Đổi đồng đội" / "Đổi trang bị"): item.view, item.exchange.

The client's exchange scene (`game_ui/game_exchange_scene.lua`) builds its own catalog from
`exchange.config` and only asks the server which items the player owns and how many times
each row was already exchanged. A row costs `need_num` of `need_item` plus food (hero rows,
`change_sort` 1) or metal (equipment rows, sort 2); sorts 3-5 belong to systems this server
does not run and answer "Tính năng chưa mở.".

Both replies carry the full `items` / `exchange_log` shape: the scene calls `backData()`
again on the exchange reply, and `exchange_log[key]` is indexed without a nil guard.
"""

import time

from .handlers import (Refused, Request, Services, fail, is_int, item_stacks, ok)
from .rewards import Loot, client_cache, grant, merge_cache, pay

EXCHANGE_PREFIX = "exchange:"
SERVED_SORTS = (1, 2)       # 1 hero, 2 equipment; 3 talisman, 4 pet, 5 type-49 are closed


def _exchange_log(svc: Services, uid: str) -> dict:
    """Row key -> lifetime exchanges, the only state the scene reads back."""
    return {name[len(EXCHANGE_PREFIX):]: value
            for name, value in svc.store.counters_with_prefix(uid, EXCHANGE_PREFIX).items()}


def _view(svc: Services, uid: str) -> dict:
    return {"items": item_stacks(svc, uid), "exchange_log": _exchange_log(svc, uid)}


def item_view(req: Request, svc: Services, player: dict):
    """Everything the exchange scene needs to draw the rows the player can afford."""
    return ok(_view(svc, player["uid"]))


def item_exchange(req: Request, svc: Services, player: dict):
    uid, change_id = player["uid"], req.params.get("change_id", "")
    row = svc.configs.get("exchange").get(change_id) if is_int(change_id) else None
    if row is None:
        return fail("error_param", "Vật phẩm đổi không hợp lệ.")
    sort = row.get("change_sort")
    if sort not in SERVED_SORTS:
        raise Refused("error_not_open", "Tính năng chưa mở.")

    times = _exchange_log(svc, uid).get(change_id, 0)
    limit = row.get("change_time") or 0
    if limit and times >= limit:
        raise Refused("error_limit", "Đã đạt giới hạn đổi.")

    need_num = row.get("need_num") or []
    if not need_num:
        return fail("error_param", "Vật phẩm đổi không hợp lệ.")
    need_item = int(row.get("need_item") or 0)
    need_count = int(need_num[min(times, len(need_num) - 1)])
    costs = {"food": int(row.get("need_food") or 0)} if sort == 1 \
        else {"metal": int(row.get("need_metal") or 0)}

    with svc.store.transaction():
        if need_count and not svc.store.change_items(uid, {need_item: -need_count}):
            raise Refused("error_item", "Không đủ mảnh.")
        pay(svc, uid, costs)
        granted = grant(svc, uid, Loot.of(row.get("change_id") or []), int(time.time()))
        svc.store.set_counter(uid, f"{EXCHANGE_PREFIX}{change_id}", times + 1)
        # The reply is a new item.view plus the toast and the bag/card changes; the scene
        # redraws from `items` and `exchange_log` immediately.
        data = _view(svc, uid)
        data["reward"] = granted.reward
        data["_client_cache_update"] = merge_cache(
            granted.cache, client_cache(svc, uid, items=[need_item]))
    return ok(data)


HANDLERS = {
    ("api", "item.view"): item_view,
    ("api", "item.exchange"): item_exchange,
}
