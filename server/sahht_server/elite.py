"""Elite stages ("Ải Tinh Anh"): the normal cities again, harder, once per attempt.

An elite chapter (201..220, cities 301..320; the 4xx family of chapters 101..120 is served
too) is fought as one attempt: every building starts uncleared, falls one at a time in
unlock order, and the attempt ends when the last one does. Three attempts a day, more for
coin. The first completion pays the city's `jingyingfirst` reward, later ones `jingyingsweep`.

The client talks to the normal `private_city.*` methods for the map and the enemy preview and
to `hard_*` ones to start, fight and give up; a battle ends by calling the normal
`private_city.open`, which therefore answers elite cities from the attempt state.
"""

import time

from . import campaign
from .battle import WIN
from .handlers import Request, Services, fail, is_int, ok
from .rewards import Loot, client_cache, grant, merge_cache, pay
from .shop import DAILY, period

MAX_ATTEMPTS = 3        # a day, before buying more
NO_ATTEMPT = 1          # `hard_last_attack.chapter` for "nothing in progress"
BUY_PRICE_TABLE = "16"  # pay.config row: coin price of the k-th extra attempt


def _elite_cities(svc: Services) -> dict:
    """city -> map_main_story row for every city of an elite chapter."""
    def build():
        chapters = svc.configs.get("chapter")
        return {str(row["stage_id"]): row for row in svc.configs.get("map_main_story").values()
                if isinstance(row, dict)
                and (chapters.get(str(row.get("chapter")), {}).get("is_hard") or 0) > 0}
    return svc.configs.derived("elite_cities", build)


def is_elite(svc: Services, city: str) -> bool:
    return city in _elite_cities(svc)


def _count(svc, uid, name, now) -> int:
    return svc.store.counter(uid, f"elite:{name}", period(DAILY, now))


def _set_count(svc, uid, name, value, now) -> None:
    svc.store.set_counter(uid, f"elite:{name}", max(0, value), period(DAILY, now))


def _cleared(svc: Services, uid: str, city: str, plan) -> set:
    """The buildings the player's elite city shows as cleared: the attempt's progress, or
    everything once the city has been completed and no attempt is running."""
    attempt = svc.store.elite_attempt(uid)
    if attempt and attempt[0] == city:
        return svc.store.elite_cleared(uid)
    return set(plan.buildings) if city in svc.store.elite_done(uid) else set()


def world_map(req: Request, svc: Services, player: dict):
    """The normal world map plus the elite tab's state."""
    body = campaign.world_map(req, svc, player)
    uid, now = player["uid"], int(time.time())
    data, attempt = body["data"], svc.store.elite_attempt(uid)
    for city in _elite_cities(svc):
        if city in data["all_city_regain_percent"]:   # only the cities the level has reached
            plan = campaign._city_plan(svc, city)
            data["all_city_regain_percent"][city] = campaign._regain(
                plan.buildings, _cleared(svc, uid, city, plan))
    data.update({
        "hard_last_attack": {"chapter": attempt[1] if attempt else NO_ATTEMPT},
        "hard_last_chapter": str(attempt[1]) if attempt else "0",
        "hard_last_city": attempt[0] if attempt else "0",
        "hard_done_times": _count(svc, uid, "done", now), "hard_max_times": MAX_ATTEMPTS,
        "buy_hard_times": _count(svc, uid, "bought", now),
    })
    return body


def _city_body(svc: Services, uid: str, city: str) -> dict:
    plan = campaign._city_plan(svc, city)
    cleared = _cleared(svc, uid, city, plan)
    score, level, _ = campaign._world_progress(svc, uid)
    return {
        "city": city, "land": campaign._land(plan, cleared, {campaign._target(plan.buildings, cleared)}),
        "curt_regain": campaign._regain(plan.buildings, cleared),
        "recapture_log": {}, "sweep_log": {},
        "world_level": level, "world_score": score,
    }


def city_open(req: Request, svc: Services, player: dict):
    """`private_city.open` for any city; elite ones answer from the attempt state."""
    city = req.params.get("city", "")
    if not is_elite(svc, city) or city not in campaign._city_buildings(svc):
        return campaign.city_open(req, svc, player)
    return ok(_city_body(svc, player["uid"], city))


def hard_open(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    city, chapter = req.params.get("city", ""), req.params.get("chapter", "")
    row = _elite_cities(svc).get(city)
    if row is None or city not in campaign._city_buildings(svc) or not is_int(chapter):
        return fail("error_param", "Thành phố không tồn tại.")
    if row["open_level"] > player["level"]:
        return fail("error_level", "Chưa đủ cấp.")
    attempt = svc.store.elite_attempt(uid)
    if attempt is None or attempt[0] != city:
        done = _count(svc, uid, "done", now)
        if done >= MAX_ATTEMPTS:
            return fail("error_times", "Hết lượt khiêu chiến hôm nay.")
        _set_count(svc, uid, "done", done + 1, now)
        svc.store.start_elite_attempt(uid, city, int(chapter))
    return ok(_city_body(svc, uid, city))


def hard_giveup(req: Request, svc: Services, player: dict):
    """Abandon the attempt; the attempt stays counted."""
    svc.store.end_elite_attempt(player["uid"])
    return world_map(req, svc, player)


def buy_done_times(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    prices = svc.configs.get("pay")[BUY_PRICE_TABLE]["coin"]
    bought = _count(svc, uid, "bought", now)
    pay(svc, uid, {"coin": prices[min(bought, len(prices) - 1)]})
    _set_count(svc, uid, "bought", bought + 1, now)
    _set_count(svc, uid, "done", _count(svc, uid, "done", now) - 1, now)
    return world_map(req, svc, player)


def _attempt_target(svc, uid, city, plan):
    """The building the attempt may attack now, or None when there is no such attempt."""
    attempt = svc.store.elite_attempt(uid)
    if attempt is None or attempt[0] != city:
        return None
    return campaign._target(plan.buildings, svc.store.elite_cleared(uid))


def hard_recapture(req: Request, svc: Services, player: dict):
    target = campaign._requested_building(req, svc)
    step = req.params.get("step_n", "")
    if target is None or not is_int(step) or not is_elite(svc, target[0]):
        return fail("error_param", "Tham số không hợp lệ.")
    city, building_id, detail = target
    uid, now = player["uid"], int(time.time())
    plan = campaign._city_plan(svc, city)
    fights = detail["fight_list"]
    if _attempt_target(svc, uid, city, plan) != building_id or not 0 <= int(step) < len(fights):
        return fail("error_building_locked", "Công trình chưa mở.")
    if not svc.store.spend_action_point(uid, detail.get("action_point", 0), now):
        return fail("error_action_point", "Không đủ thể lực.")

    step = int(step)
    fight = svc.configs.get("map_fight")[str(fights[step][1])]
    attackers = campaign._attackers(svc, uid, player["level"])
    defenders = campaign._defenders(svc, city, fight)
    data = campaign.run_battle(svc, uid, player, attackers, defenders, fight)
    won, last_step = data["battle"]["winer"] == WIN, step == len(fights) - 1
    data.update({"city": city, "building": str(building_id), "reward": {},
                 "next_step": (-1 if last_step else step + 1) if won else step,
                 "is_recaptured": won and last_step})
    if won:
        data.update(_victory(svc, uid, city, building_id, detail, fight, attackers, last_step,
                             plan, now))
    data["curt_regain"] = campaign._regain(plan.buildings, _cleared(svc, uid, city, plan))
    return ok(data)


def _victory(svc, uid, city, building_id, detail, fight, attackers, last_step, plan, now) -> dict:
    """Exp for the fight; on a building's last step its loot, and the city's reward when it
    was the attempt's last building."""
    rewards, cards = campaign.battle_exp(svc, uid, fight, attackers, now)
    loot, granted = Loot(), None
    if last_step:
        svc.store.mark_elite_cleared(uid, building_id)
        first_key = f"elite:first:{building_id}"
        first = svc.store.counter(uid, first_key) == 0
        svc.store.set_counter(uid, first_key, 1)
        loot.merge(campaign._building_loot(detail, first))
        if campaign._target(plan.buildings, svc.store.elite_cleared(uid)) is None:
            loot.merge(_city_reward(svc, uid, city))
            svc.store.end_elite_attempt(uid, completed_city=city)
        granted = grant(svc, uid, loot, now)
    rewards["reward_character"] = [{"c_id": str(c["c_id"])}
                                   for c in campaign._new_cards(svc, uid, granted)]
    cache = client_cache(svc, uid, cards=cards)
    return {"battle_rewards": rewards, "reward": granted.reward if granted else {},
            "_client_cache_update": merge_cache(cache, granted.cache) if granted else cache}


def _city_reward(svc: Services, uid: str, city: str) -> Loot:
    """`jingyingfirst` the first time the city is completed, `jingyingsweep` afterwards."""
    row = _elite_cities(svc)[city]
    first = city not in svc.store.elite_done(uid)
    return Loot.of(row.get("jingyingfirst" if first else "jingyingsweep", []))


HANDLERS = {
    ("api", "private_city.world_map"): world_map,
    ("api", "private_city.open"): city_open,
    ("api", "private_city.hard_open"): hard_open,
    ("api", "private_city.hard_recapture"): hard_recapture,
    ("api", "private_city.hard_giveup"): hard_giveup,
    ("api", "private_city.buy_done_times"): buy_done_times,
}
