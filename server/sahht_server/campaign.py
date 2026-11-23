"""Single-player campaign ("Xuất chiến"): world map, city grid, enemy preview, battles.

Battles are resolved here. The client sends city, building and step, then only
plays back the frame list this module returns.
"""

import random
import re
import time
from dataclasses import dataclass

from .battle import WIN, formation_layout, simulate
from .handlers import Request, Services, current_formation, fail, formation_cards, is_int, ok
from .player import gain_exp, seed_guides
from .progression import ACTIVE, Rules
from .rewards import Loot, client_cache, grant, merge_cache, roll
from .skills import SkillBook

# A land cell covers 4x4 tiles of the city's tmx map; maps range from 20x20 to 28x32
# tiles, so the grid is read from each city's own map (land rows = tmx height).
TILES_PER_CELL = 4
DEFAULT_TMX = "sinjiapo.tmx"            # game_small_map_scene's map when a city names none
TMX_DIR = ("iphonehd", "building_img")  # where the APK keeps the maps, beside config/
DEFAULT_GRID = (7, 7)                    # (columns, rows) when the map file is unavailable
TMX_SIZE_RE = re.compile(r'<map\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"')
BASE_BUILDING = 100000   # the player's own camp, drawn on every city grid
EMPTY_CELL = (1, 0, "", 1)
VISIBLE, CLEARED, TARGET = 0, 1, 2   # land cell open types the client understands
# Heroes have no crit/hit/dodge columns; these match an ordinary campaign enemy.
HERO_COMBAT = {"crit": 10, "hit": 100, "dodge": 0}
ELEMENTS = ("fire", "water", "wind", "earth")


@dataclass(frozen=True)
class CityPlan:
    """Where each building of a city sits; fixed per city, so computed once."""
    buildings: tuple     # ids in unlock order; only buildings that fit on the grid
    cells: tuple         # (y, x, building_id, anchor_flag, icon)
    width: int
    height: int


# ---- config indexes --------------------------------------------------------

def _city_buildings(svc: Services) -> dict:
    """city id -> attackable building ids from map_title_detail (ids are <city><3 digits>).

    Cities 100 and 101 pad their maps with placeholder buildings that all share one fight
    (28 and 15 copies of fight 100002); the tutorial expects city 100 to be fully
    recovered after its single real building, so a fight list repeated inside a city
    marks decoration, not a building to attack."""
    def build():
        details = svc.configs.get("map_title_detail")
        by_city = {}
        for key, detail in details.items():
            if key.isdigit() and len(key) > 3 and not key.endswith("000"):
                by_city.setdefault(key[:-3], []).append((int(key), str(detail.get("fight_list"))))
        index = {}
        for city, entries in by_city.items():
            copies = {}
            for _, fights in entries:
                copies[fights] = copies.get(fights, 0) + 1
            index[city] = sorted(b for b, fights in entries if copies[fights] == 1)
        return index
    return svc.configs.derived("city_buildings", build)


def _cities_in_order(svc: Services) -> list:
    order = svc.configs.get("cityid_cityorderid")
    known = _city_buildings(svc)
    return [city for city, _ in sorted(order.items(), key=lambda kv: int(kv[1])) if city in known]


def _chapter(svc: Services, city: str) -> str:
    order_id = svc.configs.get("cityid_cityorderid").get(city)
    entry = svc.configs.get("map_main_story").get(str(order_id))
    return str(entry["chapter"]) if entry else "1"


def _city_plan(svc: Services, city: str) -> CityPlan:
    return svc.configs.derived(("city_plan", city), lambda: _pack_city(svc, city))


def _land_size(svc: Services, city: str) -> tuple:
    """(columns, rows) of a city's land grid, from its tmx map's size in tiles."""
    order_id = svc.configs.get("cityid_cityorderid").get(city)
    story = svc.configs.get("map_main_story").get(str(order_id)) or {}
    path = svc.config_dir.parent.joinpath(*TMX_DIR, story.get("tmx") or DEFAULT_TMX)
    if not path.is_file():
        return DEFAULT_GRID
    with path.open(encoding="utf-8", errors="replace") as f:
        match = TMX_SIZE_RE.search(f.read(2048))
    if match is None:
        return DEFAULT_GRID
    return int(match[1]) // TILES_PER_CELL, int(match[2]) // TILES_PER_CELL


def _pack_city(svc: Services, city: str) -> CityPlan:
    """First-fit the camp and each building (title_x by title_y cells) onto the grid."""
    details = svc.configs.get("map_title_detail")
    cols, rows = _land_size(svc, city)
    grid = [[None] * cols for _ in range(rows)]
    cells, placed = [], []

    def place(building_id, width, height, icon):
        for y in range(rows - height + 1):
            for x in range(cols - width + 1):
                spots = [(y + dy, x + dx) for dy in range(height) for dx in range(width)]
                if all(grid[sy][sx] is None for sy, sx in spots):
                    for sy, sx in spots:
                        grid[sy][sx] = building_id
                        cells.append((sy, sx, building_id, 0 if (sy, sx) == (y, x) else 1, icon))
                    return True
        return False

    place(BASE_BUILDING, 1, 1, "")
    for building_id in _city_buildings(svc).get(city, []):
        detail = details[str(building_id)]
        if place(building_id, detail.get("title_x", 1), detail.get("title_y", 1),
                 detail.get("title_img", "")):
            placed.append(building_id)
    # Always the whole grid: land cells the server leaves out are drawn as fog, and a
    # cell outside the map makes the client's TMX lookup fail.
    return CityPlan(buildings=tuple(placed), cells=tuple(cells), width=cols, height=rows)


# ---- progress --------------------------------------------------------------

def _regain(buildings, cleared) -> int:
    return len(set(buildings) & cleared) * 100 // len(buildings) if buildings else 100


def _target(buildings, cleared):
    """The next building to attack: the first one, in id order, not yet cleared."""
    return next((b for b in buildings if b not in cleared), None)


def _reached_cities(svc: Services, level: int) -> list:
    """Cities in campaign order whose map_main_story open_level the player has reached.
    This is the world map's own rule (map_world_scene.createChapterTips)."""
    open_level = {str(row.get("stage_id")): row.get("open_level", 1)
                  for row in svc.configs.get("map_main_story").values() if isinstance(row, dict)}
    return [city for city in _cities_in_order(svc) if open_level.get(city, 1) <= level]


def _land(plan: CityPlan, cleared) -> list:
    target = _target(plan.buildings, cleared)
    rows = [[list(EMPTY_CELL) for _ in range(plan.width)] for _ in range(plan.height)]
    for y, x, building_id, anchor, icon in plan.cells:
        if building_id == BASE_BUILDING or building_id in cleared:
            state = CLEARED
        elif building_id == target:
            state = TARGET
        else:
            state = VISIBLE
        rows[y][x] = [state, building_id, icon, anchor]
    return rows


def _requested_building(req: Request, svc: Services):
    """(city, building_id, detail) for a building of the requested city, or None."""
    city, building = req.params.get("city", ""), req.params.get("building", "")
    if not is_int(building) or int(building) not in _city_buildings(svc).get(city, []):
        return None
    return city, int(building), svc.configs.get("map_title_detail")[building]


# ---- handlers --------------------------------------------------------------

def world_map(req: Request, svc: Services, player: dict):
    cleared = svc.store.cleared_buildings(player["uid"])
    reached = _reached_cities(svc, player["level"])
    last = reached[-1] if reached else "100"
    return ok({
        "last_chapter": _chapter(svc, last), "last_city": last,
        "hard_last_chapter": "0", "hard_last_city": "0",
        "hard_last_attack": {"chapter": 1},  # read unguarded by map_world_scene
        "buy_hard_times": 0, "hard_done_times": 0, "hard_max_times": 3,
        "all_city_regain_percent": {
            city: _regain(_city_plan(svc, city).buildings, cleared) for city in reached},
        "world_level": 1, "world_score": 0,
    })


def city_open(req: Request, svc: Services, player: dict):
    city = req.params.get("city", "")
    if city not in _city_buildings(svc):
        return fail("error_param", "Thành phố không tồn tại.")
    plan = _city_plan(svc, city)
    cleared = svc.store.cleared_buildings(player["uid"])
    steps = svc.store.building_steps(player["uid"])
    return ok({
        "city": city, "land": _land(plan, cleared),
        "curt_regain": _regain(plan.buildings, cleared),
        # building -> 0-based steps already won; the client resumes at len(list)
        "recapture_log": {str(b): list(range(n)) for b, n in steps.items() if b in plan.buildings},
        "world_level": 1, "world_score": 0,
    })


def _enemy(svc: Services, city: str, enemy_id) -> dict:
    """Per-city enemy_soldier_<city> first, then the shared enemy_detail (the client's order)."""
    key = str(enemy_id)
    return (svc.configs.get(f"enemy_soldier_{city}").get(key)
            or svc.configs.get("enemy_detail")[key])


def _enemy_ids(fight: dict) -> list:
    """(slot 1-5, enemy id) for each occupied front-row position."""
    return [(i, ids[0]) for i in range(1, 6) if (ids := fight.get(f"position{i}"))]


def map_fight_and_enemy(req: Request, svc: Services, player: dict):
    target = _requested_building(req, svc)
    if target is None:
        return fail("error_param", "Công trình không tồn tại.")
    city, _, detail = target
    map_fight = svc.configs.get("map_fight")
    fights = {str(fid): map_fight[str(fid)] for _, fid in detail["fight_list"]}
    return ok({
        "map_fight": fights,
        "enemy_detail": {str(e): _enemy(svc, city, e)
                         for fight in fights.values() for _, e in _enemy_ids(fight)},
    })


def recapture(req: Request, svc: Services, player: dict):
    target = _requested_building(req, svc)
    step = req.params.get("step_n", "")
    if target is None or not is_int(step):
        return fail("error_param", "Tham số không hợp lệ.")
    city, building_id, detail = target
    step, fights = int(step), detail["fight_list"]
    plan = _city_plan(svc, city)
    if not 0 <= step < len(fights) or building_id not in plan.buildings:
        return fail("error_param", "Tham số không hợp lệ.")

    uid, now = player["uid"], int(time.time())
    cleared = svc.store.cleared_buildings(uid)
    unlocked = building_id in cleared or building_id == _target(plan.buildings, cleared)
    if city not in _reached_cities(svc, player["level"]) or not unlocked:
        return fail("error_building_locked", "Công trình chưa mở.")
    if building_id not in cleared and step > svc.store.building_steps(uid).get(building_id, 0):
        return fail("error_param", "Chưa thắng các bước trước.")
    if not svc.store.spend_action_point(uid, detail.get("action_point", 0), now):
        return fail("error_action_point", "Không đủ thể lực.")

    fight = svc.configs.get("map_fight")[str(fights[step][1])]
    attackers, defenders = _attackers(svc, uid, player["level"]), _defenders(svc, city, fight)
    formation = current_formation(svc, uid)
    winer, frames = _fight(svc, attackers, defenders, fight, formation)
    won, last_step = winer == WIN, step == len(fights) - 1
    data = {
        "has_battled": 1,  # the client does nothing unless this is exactly 1
        "city": city, "building": str(building_id),
        "next_step": (-1 if last_step else step + 1) if won else step,
        "is_recaptured": won and last_step,
        "reward": {},
        "battle": {
            "winer": winer,
            "init": _battle_init(player, attackers, defenders, fight, formation),
            "battle": {str(i): frame for i, frame in enumerate(frames, start=1)},
        },
    }
    if won:
        data.update(_victory(svc, uid, building_id, detail, fight, attackers, last_step, step, now))
    data["curt_regain"] = _regain(plan.buildings, svc.store.cleared_buildings(uid))
    return ok(data)


def _victory(svc, uid, building_id, detail, fight, attackers, last_step, step, now) -> dict:
    """Experience for the player and every attacking card; building loot on the last step."""
    rules = Rules.load(svc.configs)
    with svc.store.transaction():
        old_exp = svc.store.state(uid, now)["exp"]
        level = gain_exp(svc, uid, fight.get("reward_exp_role", 0), now)
        card_exp, cards = _card_exp(svc, rules, uid, attackers, fight.get("reward_exp_character", 0),
                                    level.level)
        granted = None
        if last_step:
            first = svc.store.mark_cleared(uid, building_id)
            granted = grant(svc, uid, _building_loot(detail, first), now)
            seed_guides(svc, uid)
        elif building_id not in svc.store.cleared_buildings(uid):
            # Replaying an earlier step never moves the building's progress back.
            won = svc.store.building_steps(uid).get(building_id, 0)
            svc.store.set_building_steps(uid, building_id, max(won, step + 1))
    rewards = {
        "reward_exp_player": [level.gained, old_exp, level.steps],
        "reward_exp_character": card_exp,
        "reward_character": [{"c_id": str(c["c_id"])} for c in _new_cards(svc, uid, granted)],
    }
    cache = client_cache(svc, uid, cards=cards)
    return {
        "battle_rewards": rewards,
        "reward": granted.reward if granted else {},
        "_client_cache_update": merge_cache(cache, granted.cache) if granted else cache,
    }


def _card_exp(svc, rules, uid, attackers, amount, player_level):
    """Give each attacking card the fight's card exp. Returns the client's
    reward_exp_character ({card id: [added, old exp, [[lv, need], ...]]}) and the card ids.
    Every attacker must have an entry, or the result screen errors."""
    cap = rules.card_level_max(player_level)
    entries, ids = {}, []
    for unit in attackers:
        card = svc.store.card(uid, unit["id"].removeprefix("x_"))
        character = rules.characters[str(card["c_id"])]
        result = rules.add_exp(card["lv"], card["exp"], amount,
                               lambda lv, ch=character: rules.card_exp_needed(ch, lv), cap)
        svc.store.update_card(uid, card["id"], lv=result.level, exp=result.exp, step=card["step"])
        entries[card["id"]] = [result.gained, card["exp"], result.steps]
        ids.append(card["id"])
    return entries, ids


def _building_loot(detail: dict, first_clear: bool) -> Loot:
    """First clear: reward_first_base plus one reward_first_rate roll; later clears the sweep pair."""
    prefix = "reward_first" if first_clear else "reward_sweep"
    loot = Loot.of(detail.get(f"{prefix}_base", []))
    extra = roll(detail.get(f"{prefix}_rate", []), random.Random())
    if extra is not None:
        loot.add(*extra)
    return loot


def _new_cards(svc, uid, granted) -> list:
    if granted is None or not granted.card_ids:
        return []
    wanted = set(granted.card_ids)
    return [c for c in svc.store.cards_for_player(uid) if c["id"] in wanted]


# ---- battle ----------------------------------------------------------------

def _attackers(svc: Services, uid: str, player_level: int) -> list:
    rules = Rules.load(svc.configs)
    book = SkillBook.load(svc.configs)
    units = []
    for card in formation_cards(svc.store.cards_for_player(uid)):
        character = rules.characters[str(card["c_id"])]
        doc = rules.card_document(card, player_level)
        units.append({
            "pos": card["slot"], "card_id": str(card["c_id"]), "id": f"x_{card['id']}",
            "lv": doc["lv"], "hp": doc["hp"], "patk": doc["patk"], "matk": doc["matk"],
            "def": doc["def"], "speed": doc["speed"], **HERO_COMBAT,
            "animation": character.get("animation", ""), "race": character.get("race", -1),
            "skills": _card_skills(book, doc),
        })
    return units


def _card_skills(book: SkillBook, doc: dict) -> list:
    """(slot, Skill) for each active skill of a card document."""
    skills = []
    for slot in range(1, 8):
        entry = doc.get(f"s_{slot}")
        if entry and entry["s"] and entry["avail"] == ACTIVE:
            skill = book.skill(entry["s"], entry["lv"])
            if skill is not None:
                skills.append((slot, skill))
    return skills


def _defenders(svc: Services, city: str, fight: dict) -> list:
    units = []
    for slot, enemy_id in _enemy_ids(fight):
        enemy = _enemy(svc, city, enemy_id)
        units.append({
            "pos": 99 + slot, "card_id": str(enemy_id), "id": f"e_{slot}",
            "lv": enemy["lv"], "hp": enemy["hp"], "patk": enemy["patk"],
            "matk": enemy.get("matk", 0), "def": enemy["def"], "speed": enemy["speed"],
            "crit": enemy.get("crit", 0), "hit": enemy.get("hr", 100), "dodge": enemy.get("dr", 0),
            "boss": enemy.get("is_boss", 0) == 1, "race": enemy.get("race", -1),
            "elements": {e: enemy.get(e, 0) for e in ELEMENTS},
            "element_def": {e: enemy.get(f"{e}_dfs", 0) for e in ELEMENTS},
            "animation": enemy["animation"],
            "rgb_sort": enemy.get("rgb_sort", 0), "name": enemy.get("enemy_name", ""),
        })
    return units


def _fight(svc: Services, attackers: list, defenders: list, fight: dict, formation: int):
    """Run the battle with hero skills; enemies fight with normal attacks.
    The attackers stand in the player's chosen formation layout."""
    book = SkillBook.load(svc.configs)
    formations = svc.configs.get("formation")
    layouts = tuple(formation_layout(formations.get(str(f), {}))
                    for f in (formation, fight.get("formation_id", 1)))
    return simulate(attackers, defenders, rng=random.Random(), layouts=layouts,
                    script=lambda unit, skill, slot: book.script(unit.animation, skill, slot))


def _battle_init(player: dict, attackers: list, defenders: list, fight: dict,
                 formation: int) -> dict:
    atk, dfd = [0] * 10, [0] * 10
    for u in attackers:
        atk[u["pos"]] = {k: u[k] for k in ("card_id", "id", "hp", "lv", "speed")}
    for u in defenders:
        # Campaign defenders get no config lookup, so they carry their own animation.
        dfd[u["pos"] - 100] = {k: u[k] for k in
                               ("card_id", "id", "hp", "lv", "speed", "animation", "rgb_sort")}
    return {
        "aform": formation, "dform": fight.get("formation_id", 1),
        "atk_skill": [0, 0, 0], "dfd_skill": [0, 0, 0],
        "card_att": {}, "card_def": {},
        "atk": atk, "dfd": dfd,
        "atk_name": player["name"], "atk_lv": player["level"],
        "dfd_name": defenders[0]["name"] if defenders else "",
        "dfd_lv": defenders[0]["lv"] if defenders else 1,
    }


HANDLERS = {
    ("api", "private_city.world_map"): world_map,
    ("api", "private_city.open"): city_open,
    ("api", "private_city.map_fight_and_enemy"): map_fight_and_enemy,
    ("api", "private_city.recapture"): recapture,
}
