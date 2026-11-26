"""Welfare tabs of the main scene: free sign-in, recharge sign-in and the VIP reward track.

Free sign-in (daily_award.config): the first visit of each calendar day opens the next day
of the cycle (`signin:score`, capped at the config's length); days stay claimable until
claimed (`signin:claimed` bitmask), so missed days are not lost. The recharge sign-in
(month_award_coin.config) needs `pay` coins recharged today to claim that day's cell.
VIP rewards (new_vip_reward.config): each VIP level up to the player's own has a 7-day track
(one day per calendar day, `vip_sign:<level>`), and the own level has a daily bonus.
Daily state uses the shop's daily period; everything else is a lifetime counter.
"""

import time

from .handlers import ALERT_PROVIDERS, Refused, Request, Services, fail, is_int, ok
from .player import vip_level
from .rewards import Loot, grant
from .shop import DAILY, period

TRACK_DAYS = 7


def _day(now: int) -> str:
    return period(DAILY, now)


# ---- free sign-in --------------------------------------------------------------------

def _cycle_length(svc: Services) -> int:
    return len(svc.configs.get("daily_award"))


def _sync_sign_in(svc: Services, uid: str, now: int) -> int:
    """Open today's day once; returns the days reached so far."""
    store, day = svc.store, _day(now)
    with store.transaction():
        score = store.counter(uid, "signin:score")
        if not store.counter(uid, "signin:today", day):
            store.set_counter(uid, "signin:today", 1, day)
            score = min(score + 1, _cycle_length(svc))
            store.set_counter(uid, "signin:score", score)
    return score


def _unclaimed_days(svc: Services, uid: str, score: int) -> list:
    claimed = svc.store.counter(uid, "signin:claimed")
    return [d for d in range(1, score + 1) if not claimed >> d & 1]


def _coin_sign_state(svc: Services, uid: str, now: int) -> dict:
    store, day = svc.store, _day(now)
    rows, claimed = svc.configs.get("month_award_coin"), store.counter(uid, "coin_sign:claimed")
    paid = store.counter(uid, "recharge_coin", day)
    if store.counter(uid, "coin_sign:today", day):
        days, status = claimed - 1, 2
    else:
        row = rows.get(str(claimed + 1))
        days, status = claimed, int(row is not None and paid >= row["pay"])
    return {"coin_days": days, "coin_status": status, "coin_pay_rmb": paid}


def record_recharge(svc: Services, uid: str, coins: int, now: int) -> None:
    """Coins recharged today, which unlock the recharge sign-in cell."""
    day = _day(now)
    svc.store.set_counter(uid, "recharge_coin", svc.store.counter(uid, "recharge_coin", day)
                          + coins, day)


def _sign_in_data(svc: Services, uid: str, now: int) -> dict:
    score = _sync_sign_in(svc, uid, now)
    return {"score": score, "reward": _unclaimed_days(svc, uid, score),
            **_coin_sign_state(svc, uid, now)}


def daily_award_all_reward(req: Request, svc: Services, player: dict):
    return ok(_sign_in_data(svc, player["uid"], int(time.time())))


def daily_award_get_reward(req: Request, svc: Services, player: dict):
    uid, now, key = player["uid"], int(time.time()), req.params.get("reward", "")
    score = _sync_sign_in(svc, uid, now)
    if not is_int(key) or int(key) not in _unclaimed_days(svc, uid, score):
        return fail("error_param", "Chưa thể nhận phần thưởng này.")
    day = int(key)
    with svc.store.transaction():
        svc.store.set_counter(uid, "signin:claimed",
                              svc.store.counter(uid, "signin:claimed") | 1 << day)
        loot = Loot.of(svc.configs.get("daily_award")[str(day)]["award"])
        granted = grant(svc, uid, loot, now)
    return ok({"reward": granted.reward, "_client_cache_update": granted.cache})


def daily_award_coin_award(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    with svc.store.transaction():
        if _coin_sign_state(svc, uid, now)["coin_status"] != 1:
            return fail("error_param", "Chưa đủ điều kiện nhận.")
        claimed = svc.store.counter(uid, "coin_sign:claimed")
        row = svc.configs.get("month_award_coin")[str(claimed + 1)]
        svc.store.set_counter(uid, "coin_sign:claimed", claimed + 1)
        svc.store.set_counter(uid, "coin_sign:today", 1, _day(now))
        granted = grant(svc, uid, Loot.of(row["award"]), now)
    state = _coin_sign_state(svc, uid, now)
    return ok({"coin_days": state["coin_days"], "coin_status": state["coin_status"],
               "reward": granted.reward, "_client_cache_update": granted.cache})


def _has_unclaimed_sign_in(svc: Services, uid: str, now: int) -> bool:
    return bool(_unclaimed_days(svc, uid, _sync_sign_in(svc, uid, now)))


# ---- VIP rewards ----------------------------------------------------------------------

def _vip(svc: Services, uid: str) -> int:
    return vip_level(svc.configs, svc.store.wallet(uid).get("vip_exp", 0))


def _vip_rows(svc: Services) -> dict:
    return svc.configs.get("new_vip_reward")


def _sign_record(svc: Services, uid: str, now: int) -> dict:
    day, rows = _day(now), _vip_rows(svc)
    record = {}
    for level in range(1, _vip(svc, uid) + 1):
        if str(level) not in rows:
            continue
        done = svc.store.counter(uid, f"vip_sign:{level}")
        today = svc.store.counter(uid, f"vip_sign_today:{level}", day)
        record[str(level)] = {"day": done, "flag": done < TRACK_DAYS and not today}
    return record


def _every_day_open(svc: Services, uid: str, now: int) -> bool:
    level = _vip(svc, uid)
    return (level >= 1 and str(level) in _vip_rows(svc)
            and not svc.store.counter(uid, "vip_everyday", _day(now)))


def _vip_state(svc: Services, uid: str, now: int) -> dict:
    return {"sign_record": _sign_record(svc, uid, now),
            "is_every_day": _every_day_open(svc, uid, now)}


def vip_reward_sign_index(req: Request, svc: Services, player: dict):
    return ok(_vip_state(svc, player["uid"], int(time.time())))


def vip_reward_vip_sign(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    own, asked = _vip(svc, uid), req.params.get("vip")
    level = own if asked is None else int(asked) if is_int(asked) else 0
    if not 1 <= level <= own or str(level) not in _vip_rows(svc):
        return fail("error_param", "Chưa đạt cấp VIP.")
    with svc.store.transaction():
        entry = _sign_record(svc, uid, now).get(str(level))
        if entry is None or not entry["flag"]:
            raise Refused("error_param", "Hôm nay đã nhận hoặc đã nhận đủ.")
        svc.store.set_counter(uid, f"vip_sign:{level}", entry["day"] + 1)
        svc.store.set_counter(uid, f"vip_sign_today:{level}", 1, _day(now))
        reward = _vip_rows(svc)[str(level)][f"day{entry['day'] + 1}"]
        granted = grant(svc, uid, Loot.of(reward), now)
    return ok({"reward": granted.reward, **_vip_state(svc, uid, now),
               "_client_cache_update": granted.cache})


def vip_reward_every_day(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    with svc.store.transaction():
        if not _every_day_open(svc, uid, now):
            raise Refused("error_param", "Hôm nay đã nhận hoặc chưa đạt VIP.")
        svc.store.set_counter(uid, "vip_everyday", 1, _day(now))
        reward = _vip_rows(svc)[str(_vip(svc, uid))]["everyday"]
        granted = grant(svc, uid, Loot.of(reward), now)
    return ok({"reward": granted.reward, **_vip_state(svc, uid, now),
               "_client_cache_update": granted.cache})


ALERT_PROVIDERS["daily"] = _has_unclaimed_sign_in

HANDLERS = {
    ("api", "daily_award.all_reward"): daily_award_all_reward,
    ("api", "daily_award.get_reward"): daily_award_get_reward,
    ("api", "daily_award.coin_award"): daily_award_coin_award,
    ("api", "vip_reward.sign_index"): vip_reward_sign_index,
    ("api", "vip_reward.vip_sign"): vip_reward_vip_sign,
    ("api", "vip_reward.every_day"): vip_reward_every_day,
}
