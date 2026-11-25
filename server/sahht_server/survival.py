"""Survival test ("Thử thách sinh tồn", hall row 80): a ladder of single fights.

The player climbs one level per win. Every loss spends one of three revivals; the ladder
and the revivals reset at 09:00 and 21:00 (`WINDOW_HOURS`). The best level ever reached is
permanent and sets how far the rush button clears without fights: up to ten levels below it.
The APK ships 200 levels but fights for only the first 150, so `config_overrides` trims the
table to what has fights.
"""

import random
import time

from . import campaign
from .battle import WIN
from .handlers import TIMEZONE, Request, Services, fail, is_int, ok
from .player import vip_level
from .rewards import Loot, client_cache, grant, merge_cache

WINDOW_HOURS = 12
FIRST_WINDOW_HOUR = 9     # windows start at 09:00 and 21:00 local time
REVIVALS = 3
RUSH_MIN_LEVEL = 30       # the client's own check: player level 30, or any VIP
RUSH_BEHIND = 10          # rush stops this many levels below the best level


def _window(now: int) -> tuple:
    """(window id, seconds left in it)."""
    length = WINDOW_HOURS * 3600
    local = now + TIMEZONE * 3600 - FIRST_WINDOW_HOUR * 3600
    return local // length, length - local % length


def _state(svc: Services, uid: str, now: int) -> dict:
    window = str(_window(now)[0])
    return {"done": svc.store.counter(uid, "live:done", window),
            "fails": svc.store.counter(uid, "live:fails", window),
            "best": svc.store.counter(uid, "live:best")}


def _save(svc: Services, uid: str, now: int, done: int, fails: int, best: int) -> None:
    window = str(_window(now)[0])
    svc.store.set_counter(uid, "live:done", done, window)
    svc.store.set_counter(uid, "live:fails", fails, window)
    svc.store.set_counter(uid, "live:best", best)


def _fight_documents(svc: Services) -> dict:
    """map_fight rows and enemy rows of every level: the screen reads any level's enemies
    unguarded, so the whole ladder goes out with each reply."""
    def build():
        levels = svc.configs.get("active_fight_forever")
        fights = {str(row["fight"]): svc.configs.get("map_fight")[str(row["fight"])]
                  for row in levels.values()}
        enemies = {str(e): campaign._enemy(svc, "active", e)
                   for row in fights.values() for _, e in campaign._enemy_ids(row)}
        return {"map_fight": fights, "enemy_detail": enemies}
    return svc.configs.derived("survival_documents", build)


def snapshot(svc: Services, uid: str, now: int) -> dict:
    state = _state(svc, uid, now)
    return {"done": list(range(1, state["done"] + 1)), "expire": _window(now)[1],
            "forever_fails": state["fails"], "forever_max_step": state["best"],
            **_fight_documents(svc)}


def _level_loot(svc: Services, level: int) -> Loot:
    return Loot.of(svc.configs.get("active_fight_forever")[str(level)]["reward"])


def forever_fight(req: Request, svc: Services, player: dict):
    now, uid = int(time.time()), player["uid"]
    levels = svc.configs.get("active_fight_forever")
    state = _state(svc, uid, now)
    level = req.params.get("level", "")
    if not is_int(level) or int(level) != state["done"] + 1 or level not in levels:
        return fail("error_param", "Cấp độ không hợp lệ.")
    if state["fails"] >= REVIVALS:
        return fail("error_times", "Hết lượt hồi sinh.")
    level = int(level)
    fight_row = svc.configs.get("map_fight")[str(levels[str(level)]["fight"])]
    attackers = campaign._attackers(svc, uid, player["level"])
    defenders = campaign._defenders(svc, "active", fight_row, random.Random())
    data = campaign.run_battle(svc, uid, player, attackers, defenders, fight_row)
    if data["battle"]["winer"] != WIN:
        _save(svc, uid, now, state["done"], state["fails"] + 1, state["best"])
        return ok({**data, "reward": {}, "active_forever": snapshot(svc, uid, now)})
    rewards, cards = campaign.battle_exp(svc, uid, fight_row, attackers, now)
    granted = grant(svc, uid, _level_loot(svc, level), now)
    _save(svc, uid, now, level, state["fails"], max(state["best"], level))
    rewards["reward_character"] = [{"c_id": str(c["c_id"])}
                                   for c in campaign._new_cards(svc, uid, granted)]
    return ok({**data, "battle_rewards": rewards, "reward": granted.reward,
               "active_forever": snapshot(svc, uid, now),
               "_client_cache_update": merge_cache(client_cache(svc, uid, cards=cards),
                                                   granted.cache)})


def auto_forever_fight(req: Request, svc: Services, player: dict):
    """Rush: clear the levels up to `best - 10` without fighting, paying all their rewards."""
    now, uid = int(time.time()), player["uid"]
    vip = vip_level(svc.configs, svc.store.wallet(uid).get("vip_exp", 0))
    if player["level"] < RUSH_MIN_LEVEL and vip <= 0:
        return fail("error_level", "Chưa đủ cấp.")
    state = _state(svc, uid, now)
    target = min(max(state["best"] - RUSH_BEHIND, 1), len(svc.configs.get("active_fight_forever")))
    loot = Loot()
    for level in range(state["done"] + 1, target + 1):
        loot.merge(_level_loot(svc, level))
    granted = grant(svc, uid, loot, now)
    if target > state["done"]:
        _save(svc, uid, now, target, state["fails"], state["best"])
    return ok({"reward": granted.reward, "active_forever": snapshot(svc, uid, now),
               "_client_cache_update": granted.cache})


HANDLERS = {
    ("api", "active.forever_fight"): forever_fight,
    ("api", "active.auto_forever_fight"): auto_forever_fight,
}
