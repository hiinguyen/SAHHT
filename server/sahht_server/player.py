"""Player-wide state: the starter kit, player experience, tutorial progress, user_status."""

import time

from .progression import Rules

# The client's own starter (role_detail position1) plus two basic quality-3 heroes.
STARTER_HEROES = (5300, 100, 200)
STARTER_ROLE = "1"   # role_detail row whose `item` list is the starting bag
# Starting money. `silver` ("Vàng") pays gold recruits: the tutorial draw costs 250.
STARTER_WALLET = {"coin": 1000, "food": 10000, "silver": 2000}
STARTER_COUNTER = "starter_kit"

FIRST_GUIDE_TEAM, FIRST_GUIDE_START, FIRST_GUIDE_DONE = "1", 1, 27
# The main tutorial teams run one after another: game_guide_controller.getCurrentId
# switches to team 2 as soon as guide["2"] is 28, so a team may only start once the
# previous one is done. Each team's first and last step come from guide.config.
GUIDE_CHAIN = ("1", "2", "3", "5")
GUIDE_CITY_REACHED, GUIDE_BUILDING_CLEARED = 4, 3   # guide_team.config open_sort values

# Currencies the client reads from user_status; balances come from the wallet.
CURRENCIES = (
    "coin", "food", "metal", "energy", "crystal", "silver", "star", "exp_ball", "metalcore",
    "dirt_silver", "dirt_gold", "adv_crystal", "super_crystal", "pet_crystal", "world_cup_oil",
    "small_forge_stone", "middle_forge_stone", "high_forge_stone", "grace", "grace_high",
    "cmdr_energy", "free_train_times", "ticket", "universe_coin", "rune_stone", "pink_coin",
    "pet_exp_ball", "enchant", "association_dedication", "arena_point", "refine_stone",
    "pet_skill_stone",
)
# Keys read with no `or default` fallback that have no game system behind them yet.
_FIXED_STATUS = {
    "vip": 0, "vip_exp": 0, "association_id": 0, "cur_title": 0,
    "card_max": 200, "equip_max": 100, "role": 1,
}


def ensure_starter(svc, player: dict) -> None:
    """Give a new player the starter heroes, money, bag and tutorial start, exactly once."""
    uid = player["uid"]
    with svc.store.transaction():
        if svc.store.counter(uid, STARTER_COUNTER):
            return
        veteran = bool(svc.store.cleared_buildings(uid))  # played before the kit existed
        svc.store.grant_starter_cards(uid, STARTER_HEROES)
        svc.store.change_wallet(uid, STARTER_WALLET)
        role = svc.configs.get("role_detail").get(STARTER_ROLE, {})
        items = {}
        for item_id, count in role.get("item", []):
            items[item_id] = items.get(item_id, 0) + count
        svc.store.change_items(uid, items)
        svc.store.advance_guide(uid, FIRST_GUIDE_TEAM,
                                FIRST_GUIDE_DONE if veteran else FIRST_GUIDE_START)
        # Players from before role.config levels may hold more exp than their level
        # needs; adding nothing runs the level-up walk once and settles them.
        gain_exp(svc, uid, 0, int(time.time()))
        svc.store.set_counter(uid, STARTER_COUNTER, 1)


def gain_exp(svc, uid: str, amount: int, now: int):
    """Add player experience; every level gained also restores role.config recover_point stamina."""
    rules = Rules.load(svc.configs)
    with svc.store.transaction():
        level = svc.store.player_for_uid(uid)["level"]
        exp = svc.store.state(uid, now)["exp"]
        result = rules.add_exp(level, exp, amount, rules.player_exp_needed, len(rules.role))
        svc.store.set_level(uid, result.level, result.exp, now)
        restored = sum(rules.role.get(str(lv), {}).get("recover_point", 0)
                       for lv, _ in result.steps[1:])
        if restored:
            svc.store.change_action_point(uid, restored, now)
        seed_guides(svc, uid)
    return result


def guide_steps(svc) -> dict:
    """team -> (first step, last step) from guide.config."""
    steps = {}
    for team, rows in svc.configs.get("guide").items():
        ids = [int(k) for k in rows if k.isdigit()] if isinstance(rows, dict) else []
        if ids:
            steps[team] = (min(ids), max(ids))
    return steps


def seed_guides(svc, uid: str) -> None:
    """Start the next main tutorial team once the previous one is done and its
    guide_team.config condition (city reached, building cleared) holds."""
    level = svc.store.player_for_uid(uid)["level"]
    open_level = {str(row.get("stage_id")): row.get("open_level", 1)
                  for row in svc.configs.get("map_main_story").values() if isinstance(row, dict)}
    rules, steps = svc.configs.get("guide_team"), guide_steps(svc)
    guide = svc.store.guide(uid)
    for previous, team in zip(GUIDE_CHAIN, GUIDE_CHAIN[1:]):
        rule = rules.get(team)
        if team in guide or rule is None or team not in steps or previous not in steps:
            continue
        if guide.get(previous, 0) < steps[previous][1]:
            return  # the chain is still on an earlier team
        value = rule.get("open_value")
        if rule.get("open_sort") == GUIDE_CITY_REACHED:
            holds = open_level.get(str(value), float("inf")) <= level
        elif rule.get("open_sort") == GUIDE_BUILDING_CLEARED:
            holds = value in svc.store.cleared_buildings(uid)
        else:
            holds = False
        if holds:
            svc.store.advance_guide(uid, team, steps[team][0])
        return


def user_status(svc, uid: str) -> dict:
    """Built after the handler ran, so it reflects everything the handler changed."""
    rules = Rules.load(svc.configs)
    player = svc.store.player_for_uid(uid)
    now = int(time.time())
    wallet = svc.store.wallet(uid)
    return {
        **_FIXED_STATUS,
        **{c: wallet.get(c, 0) for c in CURRENCIES},
        **svc.store.state(uid, now),  # action_point, action_point_update_left, exp
        "action_point_max": svc.store.ap_max, "action_point_rate": svc.store.ap_interval,
        "exp_max": rules.player_exp_max(player["level"]),
        "guide": svc.store.guide(uid),
        "uid": player["uid"],
        "show_name": player["name"],
        "level": player["level"],
        "server_time": now,
    }
