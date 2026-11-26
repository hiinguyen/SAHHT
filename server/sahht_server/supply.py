"""Survival supplies ("Sinh tồn vật tư", welfare tab and hall row 10).

The config text says it all: supplies are handed out 12:00-14:00 and 19:00-21:00 local time,
once per window per day, and restore 50 stamina; a missed window cannot be claimed later.
`active.index` offers the open, unclaimed window as `gift_reward {<window id>: seconds left}`
and `reward.gift_award` claims it. The main scene's dot compares `alerts.active` with the
integer 1, so that alert is 1 or 0, never a boolean.
"""

import time

from .handlers import ALERT_PROVIDERS, TIMEZONE, Request, Services, fail, ok
from .rewards import Loot, grant
from .shop import DAILY, period

WINDOWS = {"1": (12, 14), "2": (19, 21)}   # window id -> (first hour, hour it closes)
SUPPLY_STAMINA = 50
HOUR = 3600


def _open_window(now: int):
    """(window id, seconds left) of the window open now, or None."""
    local = (now + TIMEZONE * HOUR) % (24 * HOUR)
    for window, (start, end) in WINDOWS.items():
        if start * HOUR <= local < end * HOUR:
            return window, end * HOUR - local
    return None


def _claimed(svc: Services, uid: str, window: str, now: int) -> bool:
    return bool(svc.store.counter(uid, f"supply:{window}", period(DAILY, now)))


def gift_reward(svc: Services, uid: str, now: int) -> dict:
    """`active.index`'s gift_reward: the claimable window with its seconds left, else {}."""
    current = _open_window(now)
    if current is None or _claimed(svc, uid, current[0], now):
        return {}
    return {current[0]: current[1]}


def reward_gift_award(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    window = req.params.get("award_id", "")
    if gift_reward(svc, uid, now).get(window) is None:
        return fail("error_param", "Chưa đến giờ phát vật tư hoặc bạn đã nhận rồi.")
    svc.store.set_counter(uid, f"supply:{window}", 1, period(DAILY, now))
    granted = grant(svc, uid, Loot(action_point=SUPPLY_STAMINA), now)
    return ok({"reward": granted.reward, "_client_cache_update": granted.cache})


ALERT_PROVIDERS["active"] = lambda svc, uid, now: int(bool(gift_reward(svc, uid, now)))

HANDLERS = {("api", "reward.gift_award"): reward_gift_award}
