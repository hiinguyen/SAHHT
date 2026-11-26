"""Growth plan ("Kế hoạch trưởng thành", welfare tab, charge pack 12).

The player buys the plan once (the free recharge path, `payment.use_ticket` for pack 12);
afterwards each level row of grow_gift.config pays its reward once when the player reaches
that level. `status` is 0 before the purchase and 1 after; `info` lists the claimed levels.
"""

import time

from .handlers import ALERT_PROVIDERS, Request, Services, fail, ok
from .rewards import Loot, grant

PACK_ID = "12"
BOUGHT = "grow:bought"


def _claimed_name(level) -> str:
    return f"grow:claimed:{level}"


def _levels(svc: Services) -> list:
    return sorted(int(key) for key in svc.configs.get("grow_gift"))


def _state(svc: Services, uid: str) -> dict:
    claimed = [lv for lv in _levels(svc) if svc.store.counter(uid, _claimed_name(lv))]
    return {"status": int(bool(svc.store.counter(uid, BOUGHT))), "info": claimed}


def refuse_purchase(svc: Services, uid: str):
    """An error body when the plan was already bought, else None."""
    if svc.store.counter(uid, BOUGHT):
        return fail("error_buy_times", "Bạn đã mua Kế hoạch Trưởng Thành rồi.")
    return None


def activate(svc: Services, uid: str) -> None:
    svc.store.set_counter(uid, BOUGHT, 1)


def grow_gift_index(req: Request, svc: Services, player: dict):
    return ok(_state(svc, player["uid"]))


def grow_gift_receive(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    text = req.params.get("lv", "")
    row = svc.configs.get("grow_gift").get(text)
    state = _state(svc, uid)
    if row is None or not state["status"] or int(text) in state["info"]:
        return fail("error_param", "Chưa thể nhận phần thưởng này.")
    if svc.store.player_for_uid(uid)["level"] < int(text):
        return fail("error_level", "Chưa đủ cấp.")
    svc.store.set_counter(uid, _claimed_name(text), 1)
    granted = grant(svc, uid, Loot.of(row["reward"]), now)
    return ok({"reward": granted.reward, **_state(svc, uid),
               "_client_cache_update": granted.cache})


def _has_claimable(svc: Services, uid: str, now: int) -> bool:
    state = _state(svc, uid)
    level = svc.store.player_for_uid(uid)["level"]
    return bool(state["status"]) and any(
        lv <= level and lv not in state["info"] for lv in _levels(svc))


ALERT_PROVIDERS["grow_gift"] = _has_claimable

HANDLERS = {
    ("api", "active.grow_gift_index"): grow_gift_index,
    ("api", "active.grow_gift_receive"): grow_gift_receive,
}
