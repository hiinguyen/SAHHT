"""The diamond shop (shop.open, shop.buy) and the SHHHT VIP shop.

shop.config: `need_value` is the coin price indexed by how many were bought already
(the last entry repeats), `sell_max` caps purchases per `sell_sort` period (1 daily,
2 weekly; sell_sort 0 has no cap). A daily or weekly entry with sell_max 0 is shown sold
out by the client (game_buy_item_scene), so it cannot be bought. `show_level` and `sell_time` limit who
sees an entry and when. The client filters none of this, so the server does. Entries
whose rewards include a kind with no system yet are not offered.
"""

import time
from datetime import datetime, timedelta, timezone

from .handlers import TIMEZONE, Request, Services, fail, is_int, ok
from .player import vip_level
from .rewards import (CARD, CURRENCY_BY_TYPE, ITEM, PLAYER_EXP, Loot, grant, pay)

SUPPORTED = set(CURRENCY_BY_TYPE) | {CARD, ITEM, PLAYER_EXP}
DAILY, WEEKLY = 1, 2
MAX_COUNT = 999
LOCAL = timezone(timedelta(hours=TIMEZONE))


def period(sort: int, now: int) -> str:
    day = datetime.fromtimestamp(now, LOCAL).date()
    if sort == DAILY:
        return day.isoformat()
    if sort == WEEKLY:
        year, week, _ = day.isocalendar()
        return f"{year}-W{week}"
    return ""


def _on_sale(entry: dict, level: int, now: int) -> bool:
    low, high = (entry.get("show_level") or [1, 10**6])[:2]
    if not low <= level <= high:
        return False
    if not all(r[0] in SUPPORTED for r in entry.get("shop_reward", [])):
        return False
    window = entry.get("sell_time", "")
    if not window:
        return True
    try:
        start, end = (datetime.strptime(" ".join(part.split()), "%Y/%m/%d %H:%M:%S")
                      .replace(tzinfo=LOCAL).timestamp() for part in window.split("-"))
    except ValueError:
        return False
    return start <= now <= end


def _bought(svc: Services, uid: str, shop_id: str, entry: dict, now: int) -> int:
    return svc.store.counter(uid, f"shop:{shop_id}", period(entry.get("sell_sort", 0), now))


def shop_open(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    items = {}
    for shop_id, entry in svc.configs.get("shop").items():
        if isinstance(entry, dict) and _on_sale(entry, player["level"], now):
            items[shop_id] = {"bought": _bought(svc, uid, shop_id, entry, now),
                              "shop_reward": entry.get("shop_reward", []),
                              "im_use": entry.get("im_use", 0)}
    return ok({"items": items})


def shop_buy(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    shop_id, count = req.params.get("shop_id", ""), req.params.get("count", "1")
    entry = svc.configs.get("shop").get(shop_id)
    if (entry is None or not is_int(count) or not 1 <= int(count) <= MAX_COUNT
            or not _on_sale(entry, player["level"], now)):
        return fail("error_param", "Vật phẩm không bán.")
    count, prices = int(count), entry.get("need_value") or [0]
    bought = _bought(svc, uid, shop_id, entry, now)
    capped = entry.get("sell_sort", 0) in (DAILY, WEEKLY)
    if capped and bought + count > entry.get("sell_max", 0):
        return fail("error_sell_max", "Đã hết lượt mua.")
    price = sum(prices[min(bought + i, len(prices) - 1)] for i in range(count))
    loot = Loot.of([[kind, ref, n * count] for kind, ref, n in entry.get("shop_reward", [])])
    with svc.store.transaction():
        pay(svc, uid, {"coin": price})
        svc.store.set_counter(uid, f"shop:{shop_id}", bought + count,
                              period(entry.get("sell_sort", 0), now))
        granted = grant(svc, uid, loot, now)
    return ok({"bought": bought + count, "goods": granted.reward,
               "_client_cache_update": granted.cache})


def _vip_bought(svc: Services, uid: str) -> dict:
    """shop id -> bought count, the map game_vip_shop keeps in `m_shop_data`."""
    return {str(shop_id): bought for shop_id in svc.configs.get("vip_store")
            if (bought := svc.store.counter(uid, f"vip_shop:{shop_id}"))}


def vip_store_index(req: Request, svc: Services, player: dict):
    return ok({"date": _vip_bought(svc, player["uid"])})


def vip_store_buy(req: Request, svc: Services, player: dict):
    """The SHHHT VIP shop (ui_vip btnTag 301): vip_store.config stock bought with coin."""
    uid, now = player["uid"], int(time.time())
    shop_id, count = req.params.get("shop_id", ""), req.params.get("count", "1")
    entry = svc.configs.get("vip_store").get(shop_id)
    if entry is None or not is_int(count) or not 1 <= int(count) <= MAX_COUNT:
        return fail("error_param", "Vật phẩm không bán.")
    count = int(count)
    vip = vip_level(svc.configs, svc.store.wallet(uid).get("vip_exp", 0))
    if vip < entry.get("show_vip", 0):
        return fail("error_vip", "Chưa đạt cấp VIP.")
    bought = svc.store.counter(uid, f"vip_shop:{shop_id}")
    if bought + count > entry.get("sell_max", 0):
        return fail("error_sell_max", "Đã hết lượt mua.")
    price = (entry.get("need_value") or [[9, 0, 0]])[0][2] * count
    loot = Loot.of([[kind, ref, n * count] for kind, ref, n in entry.get("shop_item", [])])
    with svc.store.transaction():
        pay(svc, uid, {"coin": price})
        svc.store.set_counter(uid, f"vip_shop:{shop_id}", bought + count)
        granted = grant(svc, uid, loot, now)
    return ok({"goods": [], "reward": granted.reward, "date": _vip_bought(svc, uid),
               "_client_cache_update": granted.cache})


HANDLERS = {
    ("api", "shop.open"): shop_open,
    ("api", "shop.buy"): shop_buy,
    ("api", "shop.vip_store_index"): vip_store_index,
    ("api", "shop.vip_store_buy"): vip_store_buy,
}
