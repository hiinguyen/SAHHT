"""The ranking screens ("Xếp hạng") and `user.info`.

`game_new_rank` is one screen with twelve tabs. The tabs the server can fill are served
with real data: combat power, level, the arena ladder, survival and world recovery. The
rest (world boss, strongest cards, equipment, commander, likes, guilds) answer an empty
list, which the screen draws as an empty table. `user.info` feeds the player card popup
opened from a ranking row or an arena opponent.
"""

from . import arena, equipment, gems
from .handlers import (Request, Services, alignment, card_documents, fail, formation_document,
                       is_int, ok, owned_formations, team_combat)

PAGE = 20
MAX_PAGES = 5
EMPTY = "-1"
ATTACK_SLOTS, BENCH_SLOTS = 5, 3


def _page(req: Request) -> int:
    value = req.params.get("page", "0")
    return min(max(int(value), 0), MAX_PAGES - 1) if is_int(value) else 0


def _players(svc: Services) -> list:
    """Every player with the numbers every tab shows."""
    rows = []
    for player in svc.store.players_overview():
        uid = player["uid"]
        rows.append({"uid": uid, "name": player["name"], "level": player["level"],
                     "combat": team_combat(svc, uid), "role": 1, "title": 0})
    return rows


def _reply(rows: list, page: int, key: str = "top") -> dict:
    start = page * PAGE
    return ok({key: rows[start:start + PAGE], "cur_page": page})


def top_combat(req: Request, svc: Services, player: dict):
    page = _page(req)
    rows = sorted(_players(svc), key=lambda row: (-row["combat"], -row["level"], row["uid"]))
    return _reply(rows, page)


def top_level(req: Request, svc: Services, player: dict):
    page = _page(req)
    rows = sorted(_players(svc), key=lambda row: (-row["level"], -row["combat"], row["uid"]))
    return _reply(rows, page)


def top_boss(req: Request, svc: Services, player: dict):
    """No world boss exists yet; the tab draws an empty table."""
    return _reply([], _page(req))


def top_rank(req: Request, svc: Services, player: dict):
    """`user.top_rank`: the tabs the server can fill from stored progress."""
    page, sort = _page(req), req.params.get("sort", "")
    rows = []
    if sort == "world_regain":
        for row in _players(svc):
            row["score"] = len(svc.store.cleared_buildings(row["uid"]))
            rows.append(row)
        rows.sort(key=lambda row: (-row["score"], -row["combat"], row["uid"]))
    elif sort == "equipment":
        for row in _players(svc):
            row["score"] = sum(e["lv"] + e["st_lv"]
                               for e in svc.store.equipment_rows(row["uid"]))
            rows.append(row)
        rows.sort(key=lambda row: (-row["score"], -row["combat"], row["uid"]))
    return _reply(rows, page)


def top_survival(req: Request, svc: Services, player: dict):
    """`active.top`: the survival ladder's best level per player, highest first."""
    rows = []
    for row in _players(svc):
        best = svc.store.counter(row["uid"], "live:best")
        if best:
            rows.append(row | {"rank": best})
    rows.sort(key=lambda row: (-row["rank"], -row["combat"], row["uid"]))
    return ok({"users": rows})


def _bot_document(svc: Services, rank: int) -> dict:
    bot = arena._bot_documents(svc, rank)
    cards = {doc["id"]: doc for doc in bot["docs"]}
    ids = [doc["id"] for doc in bot["docs"]]
    attack = (ids + [EMPTY] * ATTACK_SLOTS)[:ATTACK_SLOTS]
    return {
        "cards": cards,
        "alignment": [attack, [EMPTY] * BENCH_SLOTS],
        "equip_pos": equipment.grid(()), "gem_pos": gems.grid(()), "equip": {},
        "formation": {"current": 1, "own": owned_formations(svc)},
        "ass_equip_pos": equipment.grid(()),
        "user": {"uid": arena.bot_uid(rank), "name": bot["name"], "level": bot["level"],
                 "combat": bot["combat"], "role": bot["role"], "title": 0},
    }


def _player_document(svc: Services, uid: str) -> dict | None:
    player = svc.store.player_for_uid(uid)
    if player is None:
        return None
    cards = svc.store.cards_for_player(uid)
    return {
        "cards": card_documents(svc, uid),
        "alignment": alignment(cards),
        "equip_pos": equipment.grid(svc.store.equipment_positions(uid)),
        "gem_pos": gems.grid(svc.store.gem_positions(uid)),
        "equip": equipment.documents(svc.store.equipment_rows(uid)),
        "formation": formation_document(svc, uid),
        # Empty grids: the popup indexes these positions unguarded while it draws.
        "ass_equip_pos": equipment.grid(()),
        "user": {"uid": uid, "name": player["name"], "level": player["level"],
                 "combat": team_combat(svc, uid), "role": 1, "title": 0},
    }


def user_info(req: Request, svc: Services, player: dict):
    uid = req.params.get("uid", "")
    rank = arena.bot_rank(uid)
    data = _bot_document(svc, rank) if rank is not None else _player_document(svc, uid)
    if data is None:
        return fail("error_param", "Không tìm thấy người chơi.")
    return ok({"new_data": data})


HANDLERS = {
    ("api", "user.top_combat"): top_combat,
    ("api", "user.top_level"): top_level,
    ("api", "user.top_world_boss_hurt"): top_boss,
    ("api", "user.top_rank"): top_rank,
    ("api", "active.top"): top_survival,
    ("api", "user.info"): user_info,
}
