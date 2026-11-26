"""Auto battle ("càn quét") of a building the player already recaptured.

The client sends `private_city.auto_recapture` for a cleared building; it plays no battle and
shows `auto_battle_over_pop` from the reply. A sweep wins every step of the building, costs the
building's whole action point bill, and is limited per building per day by `map_title_detail`'s
`max_sweep`. Spent sweeps are in `private_city.open`'s `sweep_log`; players whose vip row has
`sweep_times == 1` buy a fresh allowance for the `pay` row 11 coin price.
"""

import time

from . import campaign
from .campaign import sweep_counter
from .handlers import Refused, Request, Services, fail, ok
from .player import vip_level
from .rewards import client_cache, grant, merge_cache
from .shop import DAILY, period

RESET_PACK = "11"   # pay.config row the client quotes for a sweep reset




def _cleared_target(req: Request, svc: Services, uid: str):
    """(building_id, detail), or an error body when the request cannot be swept."""
    target = campaign._requested_building(req, svc)
    if target is None:
        return fail("error_param", "Tham số không hợp lệ.")
    _, building_id, detail = target
    if building_id not in svc.store.cleared_buildings(uid):
        return fail("error_building_locked", "Công trình chưa được thu hồi.")
    return building_id, detail


def auto_recapture(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    target = _cleared_target(req, svc, uid)
    if isinstance(target, dict):
        return target
    building_id, detail = target
    day, name = period(DAILY, now), sweep_counter(building_id)
    try:
        with svc.store.transaction():
            used = svc.store.counter(uid, name, day)
            if used >= detail.get("max_sweep", 0):
                raise Refused("error_sweep_limit", "Số lần càn quét hôm nay đã dùng hết.")
            cost = len(detail["fight_list"]) * detail.get("action_point", 0)
            if not svc.store.spend_action_point(uid, cost, now):
                raise Refused("error_action_point", "Không đủ thể lực.")
            svc.store.set_counter(uid, name, used + 1, day)
            return ok(_rewards(svc, uid, player, detail, now))
    except Refused as refused:
        return refused.body


def _rewards(svc: Services, uid: str, player: dict, detail: dict, now: int) -> dict:
    """Experience of every step of the building plus one sweep loot roll."""
    map_fight = svc.configs.get("map_fight")
    fights = [map_fight[str(fight_id)] for _, fight_id in detail["fight_list"]]
    total = {key: sum(fight.get(key, 0) for fight in fights)
             for key in ("reward_exp_role", "reward_exp_character")}
    attackers = campaign._attackers(svc, uid, player["level"])
    battle_rewards, cards = campaign.battle_exp(svc, uid, total, attackers, now)
    granted = grant(svc, uid, campaign._building_loot(detail, first_clear=False), now)
    battle_rewards["reward_character"] = [{"c_id": str(c["c_id"])}
                                          for c in campaign._new_cards(svc, uid, granted)]
    items = {}
    for item in granted.reward.get("item", []):
        items[str(item)] = items.get(str(item), 0) + 1
    battle_rewards["reward_item"] = items
    return {
        "battle_rewards": battle_rewards, "reward": granted.reward, "godgift": {},
        "_client_cache_update": merge_cache(client_cache(svc, uid, cards=cards), granted.cache),
    }


def clear_sweep_log(req: Request, svc: Services, player: dict):
    """Buy a fresh sweep allowance for one building (vip rows with `sweep_times == 1`)."""
    uid, now = player["uid"], int(time.time())
    target = _cleared_target(req, svc, uid)
    if isinstance(target, dict):
        return target
    building_id, _ = target
    vip = vip_level(svc.configs, svc.store.wallet(uid).get("vip_exp", 0))
    if svc.configs.get("vip").get(str(vip), {}).get("sweep_times") != 1:
        return fail("error_vip", "Cần nâng cấp VIP để mua thêm lượt càn quét.")
    price = svc.configs.get("pay")[RESET_PACK]["coin"][0]
    with svc.store.transaction():
        if not svc.store.change_wallet(uid, {"coin": -price}):
            return fail("error_coin", "Không đủ xu.")
        svc.store.set_counter(uid, sweep_counter(building_id), 0, period(DAILY, now))
    return ok({})


HANDLERS = {
    ("api", "private_city.auto_recapture"): auto_recapture,
    ("api", "private_city.clear_sweep_log"): clear_sweep_log,
}
