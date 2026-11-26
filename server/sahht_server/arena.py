"""The arena ("Đấu trường"): a ladder of real players and bots, arena points, shop and log.

The client opens the screen with `arena.index`, fights with `arena.battle`, buys extra
attempts with `arena.buy_count`, reads the ladder with `arena.top` and spends arena points
in `arena.exchange`. The old `game_pk` screen uses the same methods plus `arena.log` and
`arena.replay`; both are served here.

The ladder is dense: every rank from 1 to `FLOOR_RANK` has an occupant. A rank with no real
player belongs to a deterministic bot, so a lone player still has opponents and a full
ladder. A new player enters at the bottom (`FLOOR_RANK`, or the next free rank when more
than `FLOOR_RANK` players are ranked) and winning against the rank above swaps the two
ranks. Arena points accrue every `AWARD_SECONDS` at the rate of the player's rank
(`arena_award.config`), whether or not the screen is open.
"""

import random
import secrets
import time

from . import campaign, difficulty
from .battle import WIN
from .handlers import (Request, Services, current_formation, fail, is_int, ok,
                       team_combat)
from .player import vip_level
from .progression import Rules
from .rewards import Loot, grant, pay
from .shop import DAILY, period
from .skills import SkillBook

FLOOR_RANK = 100             # the bottom of the ladder; the client's five pages hold it
DAILY_BATTLES = 10           # free attempts per day
AWARD_SECONDS = 600          # arena points are paid every ten minutes
TOP_PAGE = 20                # rows per ladder page
MAX_PAGES = 5                # game_arena and game_new_rank stop at page 5
BOT_UID_PREFIX = "bot:"
BOT_TEAM_MAX = 5
BOT_LEVEL_MAX = 120
BOT_LEVEL_PER_RANK = 1.2
BOT_TEAM_PER_RANK = 20
BOT_STEP_PER_RANK = 20
BOT_NAMES = ("Lãng Khách", "Vô Danh", "Dạ Hành", "Bóng Đêm", "Thiết Quyền",
             "Lôi Đình", "Phong Vân", "Hắc Long", "Bạch Hổ", "Tu La")


def bot_uid(rank: int) -> str:
    return f"{BOT_UID_PREFIX}{rank}"


def bot_rank(uid: str):
    """The rank encoded in a bot uid, or None for a real player's uid."""
    if not uid.startswith(BOT_UID_PREFIX):
        return None
    value = uid[len(BOT_UID_PREFIX):]
    return int(value) if is_int(value) else None


def _bot_pool(svc: Services) -> list:
    """Card ids a bot can wear: the campaign's released-hero pool, or every configured
    hero for a small test config set."""
    pool = difficulty.Difficulty.load(svc.configs).pool
    if pool:
        return [hero.card_id for hero in pool]
    characters = svc.configs.get("character_detail")
    return sorted(int(key) for key, row in characters.items()
                  if key.isdigit() and isinstance(row, dict) and "base_hp" in row)


def _bot_documents(svc: Services, rank: int) -> dict:
    """The bot at `rank`: its team documents, units and displayed combat power."""
    return svc.configs.derived(("arena_bot", rank), lambda: _build_bot(svc, rank))


def _build_bot(svc: Services, rank: int) -> dict:
    pool = _bot_pool(svc)
    rules, book = Rules.load(svc.configs), SkillBook.load(svc.configs)
    level = max(1, min(BOT_LEVEL_MAX, 1 + round((FLOOR_RANK - rank) * BOT_LEVEL_PER_RANK)))
    step = min(4, max(0, FLOOR_RANK - rank) // BOT_STEP_PER_RANK)
    size = min(BOT_TEAM_MAX, max(1, 1 + max(0, FLOOR_RANK - rank) // BOT_TEAM_PER_RANK))
    picks = random.Random(f"arena-bot:{rank}").sample(pool, min(size, len(pool))) if pool else []
    docs = []
    for index, c_id in enumerate(picks):
        card = {"id": f"b{rank}_{index}", "c_id": c_id, "lv": level, "exp": 0, "step": step,
                "bre": 0, "skills": {}}
        docs.append(rules.card_document(card, level))
    name = f"{BOT_NAMES[(rank - 1) % len(BOT_NAMES)]} {rank:02d}"
    units = _bot_units(rules, book, docs, name)
    return {"name": name, "role": 1 + rank % 5, "level": level, "rank": rank,
            "combat": int(rules.team_combat(dict(enumerate(docs)))), "docs": docs,
            "units": units, "formation": 1}


def _bot_units(rules, book, docs, name) -> list:
    units = []
    for index, doc in enumerate(docs):
        character = rules.characters[str(doc["c_id"])]
        units.append({
            "pos": 100 + index, "card_id": str(doc["c_id"]), "id": doc["id"],
            "lv": doc["lv"], "hp": doc["hp"], "patk": doc["patk"], "matk": doc["matk"],
            "def": doc["def"], "speed": doc["speed"],
            **{stat: campaign.HERO_COMBAT[stat] + doc.get(stat, 0)
               for stat in ("crit", "hit", "dodge")},
            "subhurt": doc.get("subhurt", 0),
            "elements": {e: doc.get(e, 0) for e in campaign.ELEMENTS},
            "element_def": {f"{e}_dfs": doc.get(f"{e}_dfs", 0) for e in campaign.ELEMENTS},
            "animation": character.get("animation") or "vega",
            "race": character.get("race", -1), "rgb_sort": character.get("rgb_sort", 0),
            "name": name, "skills": campaign._card_skills(book, doc),
        })
    return units


def bot_entry(svc: Services, rank: int) -> dict:
    bot = _bot_documents(svc, rank)
    return {"uid": bot_uid(rank), "name": bot["name"], "rank": rank, "role": bot["role"],
            "title": 0, "level": bot["level"], "combat": bot["combat"], "real": False}


def occupant(svc: Services, rank: int) -> dict:
    """The real player at `rank`, else the bot that fills it."""
    row = svc.store.arena_row_at(rank)
    if row is None:
        return bot_entry(svc, rank)
    return {"uid": row["uid"], "name": row["name"], "rank": rank, "role": 1, "title": 0,
            "level": row["level"], "combat": team_combat(svc, row["uid"]), "real": True}


def opponent_ranks(rank: int) -> list:
    """Four ranks to challenge: the ones just above first, then the ones below at the top."""
    above = list(range(rank - 1, max(0, rank - 5), -1))
    below = list(range(rank + 1, min(FLOOR_RANK, rank + 5)))
    return (above + below)[:4]


def ensure_row(svc: Services, uid: str, now: int) -> tuple:
    """The player's (rank, award_at); a first visit joins the bottom of the ladder."""
    row = svc.store.arena_row(uid)
    if row is not None:
        return row
    rank = max(FLOOR_RANK, svc.store.arena_max_rank() + 1)
    svc.store.create_arena_row(uid, rank, now)
    return rank, now


def per_point(svc: Services, rank: int) -> int:
    """Arena points the rank earns every AWARD_SECONDS (`arena_award.config`)."""
    for row in svc.configs.get("arena_award").values():
        if row.get("start_rank", 0) <= rank <= row.get("end_rank", 0):
            return row.get("per_point", 0)
    return 2


def accrue(svc: Services, uid: str, now: int) -> tuple:
    """Pay every whole award period since the last one; (rank, seconds to the next)."""
    rank, award_at = ensure_row(svc, uid, now)
    periods = max(0, now - award_at) // AWARD_SECONDS
    if periods:
        amount = per_point(svc, rank) * periods
        if amount:
            svc.store.change_wallet(uid, {"arena_point": amount})
        award_at += periods * AWARD_SECONDS
        svc.store.set_arena_award_at(uid, award_at)
    return rank, max(0, min(AWARD_SECONDS, AWARD_SECONDS - (now - award_at)))


def _battles_used(svc, uid, now) -> int:
    return svc.store.counter(uid, "arena:battles", period(DAILY, now))


def _battles_bought(svc, uid, now) -> int:
    return svc.store.counter(uid, "arena:bought", period(DAILY, now))


def _remaining(svc, uid, now) -> int:
    return max(0, DAILY_BATTLES + _battles_bought(svc, uid, now) - _battles_used(svc, uid, now))


def _exchange_log(svc, uid, now) -> dict:
    log = {}
    for shop_id, entry in svc.configs.get("arena_shop").items():
        if not isinstance(entry, dict):
            continue
        bought = _shop_bought(svc, uid, shop_id, entry, now)
        if bought:
            log[str(shop_id)] = {"times": bought}
    return log


def _shop_period(entry: dict, now: int) -> str:
    return period(DAILY, now) if entry.get("refresh") == 1 else ""


def _shop_bought(svc, uid, shop_id, entry, now) -> int:
    return svc.store.counter(uid, f"arena_shop:{shop_id}", _shop_period(entry, now))


def index(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    rank, expire = accrue(svc, uid, now)
    return ok({
        "award_expire": expire,
        "can_battle_times": _remaining(svc, uid, now),
        "buy_count": _battles_bought(svc, uid, now),
        "rank": rank,
        "point": svc.store.wallet(uid).get("arena_point", 0),
        "combat": team_combat(svc, uid),
        "front_user": [occupant(svc, r) for r in opponent_ranks(rank)],
        "exchange_log": _exchange_log(svc, uid, now),
        "log": svc.store.arena_log(uid),
        "cd_expire": 0,
    })


def _defender(svc: Services, uid: str, target: str):
    """(team entry, defender units, display name, rank, combat, formation) or an error body."""
    rank = bot_rank(target)
    if rank is not None:
        if not 1 <= rank <= FLOOR_RANK or svc.store.arena_row_at(rank) is not None:
            return fail("error_param", "Đối thủ không tồn tại.")
        bot = _bot_documents(svc, rank)
        return ({"name": bot["name"], "rank": rank, "combat": bot["combat"],
                 "level": bot["level"], "real": False},
                bot["units"], bot["name"], rank, bot["combat"], bot["formation"])
    target_player = svc.store.player_for_uid(target)
    row = svc.store.arena_row(target) if target_player else None
    if target_player is None or row is None or target == uid:
        return fail("error_param", "Đối thủ không tồn tại.")
    units = []
    for unit in campaign._attackers(svc, target, target_player["level"]):
        unit = dict(unit)
        unit.update({"pos": 100 + unit["pos"], "id": f"d_{unit['id'][2:]}",
                     "name": target_player["name"], "rgb_sort": 0})
        units.append(unit)
    return ({"name": target_player["name"], "rank": row[0], "combat": team_combat(svc, target),
             "level": target_player["level"], "real": True},
            units, target_player["name"], row[0], team_combat(svc, target),
            current_formation(svc, target))


def battle(req: Request, svc: Services, player: dict):
    now, uid = int(time.time()), player["uid"]
    rank, _ = accrue(svc, uid, now)
    if _remaining(svc, uid, now) <= 0:
        return fail("error_times", "Hết lượt khiêu chiến hôm nay.")
    target = req.params.get("target", "")
    if not target:
        opponents = opponent_ranks(rank)
        if not opponents:
            return fail("error_param", "Không có đối thủ.")
        target = occupant(svc, opponents[0])["uid"]
    if target == uid:
        return fail("error_param", "Không thể tự khiêu chiến.")
    defender = _defender(svc, uid, target)
    if isinstance(defender, dict):
        return defender
    _, defenders, defender_name, defender_rank, defender_combat, formation = defender
    if not defenders:
        return fail("error_param", "Đối thủ chưa có đội hình.")
    if defender_rank == rank:
        return fail("error_param", "Đối thủ không hợp lệ.")

    attackers = campaign._attackers(svc, uid, player["level"])
    fight = {"formation_id": formation}
    data = campaign.run_battle(svc, uid, player, attackers, defenders, fight)
    won = data["battle"]["winer"] == WIN
    attacker_combat = team_combat(svc, uid)
    if won and defender_rank < rank:
        _swap(svc, uid, rank, target, defender_rank)
    svc.store.set_counter(uid, "arena:battles", _battles_used(svc, uid, now) + 1,
                          period(DAILY, now))
    new_rank = svc.store.arena_row(uid)[0]
    data.update({"cur_rank": new_rank, "reward": {}})
    key = secrets.token_hex(8)
    svc.store.add_arena_replay(key, data, now)
    common = {"attacker": player["name"], "defender": defender_name,
              "a_combat": attacker_combat, "d_combat": defender_combat,
              "is_win": won, "battle_log": key, "now": now}
    svc.store.add_arena_log(uid, tp="attack", **common)
    if bot_rank(target) is None:
        svc.store.add_arena_log(target, tp="defense", **common)
    return ok(data)


def _swap(svc: Services, uid: str, rank: int, target: str, target_rank: int) -> None:
    """The winner takes the loser's rank; a real loser drops to the winner's old rank."""
    svc.store.set_arena_rank(uid, target_rank)
    if bot_rank(target) is None:
        svc.store.set_arena_rank(target, rank)


def buy_count(req: Request, svc: Services, player: dict):
    now, uid = int(time.time()), player["uid"]
    accrue(svc, uid, now)
    level = vip_level(svc.configs, svc.store.wallet(uid).get("vip_exp", 0))
    limit = svc.configs.get("vip").get(str(level), {}).get("buy_arena", 0)
    bought = _battles_bought(svc, uid, now)
    if bought >= limit:
        return fail("error_times", "Số lần mua hôm nay đã dùng hết!")
    costs = svc.configs.get("pay").get("3", {}).get("coin", [])
    if not costs:
        return fail("error_param", "Không thể mua lượt.")
    pay(svc, uid, {"coin": costs[min(bought, len(costs) - 1)]})
    svc.store.set_counter(uid, "arena:bought", bought + 1, period(DAILY, now))
    return ok({})


def top(req: Request, svc: Services, player: dict):
    page = req.params.get("page", "0")
    page = min(max(int(page), 0), MAX_PAGES - 1) if is_int(page) else 0
    rows = ladder(svc)
    start = page * TOP_PAGE
    return ok({"top": rows[start:start + TOP_PAGE], "cur_page": page})


def ladder(svc: Services) -> list:
    """Every rank 1..FLOOR_RANK (real player or bot), then any ranked player past it."""
    real = {row["rank"]: row for row in svc.store.arena_rows()}
    rows = []
    for rank in range(1, FLOOR_RANK + 1):
        rows.append(occupant(svc, rank) if rank in real else bot_entry(svc, rank))
    rows.extend(occupant(svc, row["rank"]) for row in svc.store.arena_rows()
                if row["rank"] > FLOOR_RANK)
    return [{"uid": row["uid"], "name": row["name"], "rank": row["rank"],
             "role": row["role"], "title": row["title"], "combat": row["combat"],
             "guild_name": ""} for row in rows]


def log(req: Request, svc: Services, player: dict):
    return ok({"log": svc.store.arena_log(player["uid"])})


def replay(req: Request, svc: Services, player: dict):
    key = req.params.get("key", "")
    data = svc.store.arena_replay(key) if key else None
    if data is None:
        return fail("error_param", "Không tìm thấy trận đấu.")
    return ok(data)


def exchange(req: Request, svc: Services, player: dict):
    now, uid = int(time.time()), player["uid"]
    accrue(svc, uid, now)
    shop_id = req.params.get("shop_id", "")
    count = req.params.get("count", "1")
    entry = svc.configs.get("arena_shop").get(shop_id)
    if entry is None or not isinstance(entry, dict) or not is_int(count):
        return fail("error_param", "Tham số không hợp lệ.")
    count = int(count)
    low, high = (entry.get("show_level") or [1, 10**6])[:2]
    if not low <= player["level"] <= high:
        return fail("error_level", "Cấp của bạn không thể mua!")
    bought = _shop_bought(svc, uid, shop_id, entry, now)
    limit = entry.get("times", -1)
    if count <= 0 or count > 999 or (limit != -1 and bought + count > limit):
        return fail("error_times", "Đã mua hết lượt.")
    cost = entry.get("need_point", 0) * count
    pay(svc, uid, {"arena_point": cost})
    loot = Loot.of([[kind, ref, amount * count] for kind, ref, amount in entry["shop_reward"]])
    granted = grant(svc, uid, loot, now)
    svc.store.set_counter(uid, f"arena_shop:{shop_id}", bought + count,
                          _shop_period(entry, now))
    return ok({"point": svc.store.wallet(uid).get("arena_point", 0),
               "reward": granted.reward, "_client_cache_update": granted.cache,
               "exchange_log": {str(shop_id): {"times": bought + count}}})


HANDLERS = {
    ("api", "arena.index"): index,
    ("api", "arena.battle"): battle,
    ("api", "arena.buy_count"): buy_count,
    ("api", "arena.top"): top,
    ("api", "arena.log"): log,
    ("api", "arena.replay"): replay,
    ("api", "arena.exchange"): exchange,
}
