"""Hero management: formation, experience transfer, skill upgrades, evolution, selling.

Each handler checks what the client's own screen checks (ownership, materials, levels,
costs) before changing anything, applies the whole change in one transaction, and answers
with `_client_cache_update`: the client never re-reads cards.open after these calls.
"""

from .handlers import (FORMATION_COUNTER, FORMATION_SLOTS, Refused, Request, Services, alignment,
                       fail, formation_document, is_int, ok, owned_formations)
from .progression import ACTIVE, SKILL_SLOTS, Rules
from .rewards import client_cache, pay
from .store import ATTACK_SLOTS, BENCH_SLOTS

INHERIT_RATE = 0.7          # game_hero_inherit: below VIP 1 a transfer keeps 70% of the exp
EMPTY = "-1"
MAX_MATERIALS = 6           # evolution needs min(exp // 10, 6) material cards
UNIVERSAL_MATERIALS = range(1000, 1006)   # character_ID of the "any hero" evolution cards


def _ids(req: Request, key: str) -> list:
    return [v for v in req.lists.get(key, []) if v]


def _in_team(card: dict) -> bool:
    return card["slot"] is not None


def _owned(svc, uid, ids) -> list | None:
    """The cards for these ids, or None if any id is missing, repeated or not the player's."""
    if len(set(ids)) != len(ids):
        return None
    by_id = {c["id"]: c for c in svc.store.cards_for_player(uid)}
    cards = [by_id.get(str(i)) for i in ids]
    return None if any(c is None for c in cards) else cards


def _consume(svc, uid, card_ids) -> None:
    """Delete material or sold cards; a card already gone rolls the whole change back."""
    if not svc.store.remove_cards(uid, card_ids):
        raise Refused("error_param", "Đồng đội không còn nữa.")


def _rate(rules: Rules, character: dict) -> dict:
    return rules.rates.get(str(character.get("type", 1)), {})


# ---- formation ---------------------------------------------------------------

def _positions(raw: str, size: int) -> list | None:
    """'12_-1_7' -> ['12', None, '7']; None when malformed."""
    parts = raw.split("_") if raw else []
    if len(parts) > size or not all(p == EMPTY or is_int(p) for p in parts):
        return None
    return [None if p == EMPTY else p for p in parts]


def set_alignment(req: Request, svc: Services, player: dict):
    """The formation screen sends the final layout; equipment and the rest are not stored yet."""
    attack = _positions(req.params.get("align_1", ""), ATTACK_SLOTS)
    bench = _positions(req.params.get("align_2", ""), BENCH_SLOTS)
    formation = req.params.get("formation", "")
    if attack is None or bench is None or not any(attack):
        return fail("error_param", "Đội hình không hợp lệ.")
    if formation and (not is_int(formation) or int(formation) not in owned_formations(svc)):
        return fail("error_param", "Trận hình không hợp lệ.")
    with svc.store.transaction():
        if not svc.store.set_alignment(player["uid"], attack, bench):
            return fail("error_param", "Đội hình không hợp lệ.")
        if formation:
            svc.store.set_counter(player["uid"], FORMATION_COUNTER, int(formation))
    return ok({
        "alignment": alignment(svc.store.cards_for_player(player["uid"])),
        "formation": formation_document(svc, player["uid"]),
        "equip_pos": {str(i): ["0", "0", "0", "0"] for i in range(FORMATION_SLOTS)},
    })


# ---- experience transfer (cards.inherit) ---------------------------------------

def inherit(req: Request, svc: Services, player: dict):
    """Move a card's experience (70%) and/or the exp-ball balance into another card.
    The giving card drops back to level 1."""
    uid, rules = player["uid"], Rules.load(svc.configs)
    master_id, student_id = req.params.get("master", ""), req.params.get("student", "")
    use_ball = req.params.get("use_exp_ball") == "1"
    ids = [student_id] + ([master_id] if master_id else [])
    cards = _owned(svc, uid, ids)
    if cards is None:
        return fail("error_param", "Đồng đội không hợp lệ.")
    student, master = cards[0], (cards[1] if master_id else None)

    amount = 0
    if master is not None:
        character = rules.characters[str(master["c_id"])]
        amount += int((rules.card_pre_exp(character, master["lv"]) + master["exp"]) * INHERIT_RATE)
    ball = svc.store.wallet(uid).get("exp_ball", 0) if use_ball else 0
    if amount + ball <= 0:
        return fail("error_param", "Không có kinh nghiệm để truyền.")

    character = rules.characters[str(student["c_id"])]
    result = rules.add_exp(student["lv"], student["exp"], amount + ball,
                           lambda lv: rules.card_exp_needed(character, lv),
                           rules.card_level_max(player["level"]))
    if result.gained <= 0:
        return fail("error_max_level", "Đồng đội đã đạt cấp tối đa.")
    # The card's exp goes in first; exp balls pay only for what the student absorbs.
    with svc.store.transaction():
        pay(svc, uid, {"exp_ball": min(ball, max(0, result.gained - amount))})
        if master is not None:
            svc.store.update_card(uid, master["id"], lv=1, exp=0, step=master["step"])
        svc.store.update_card(uid, student["id"], lv=result.level, exp=result.exp, step=student["step"])
    return ok({"reward": {}, "_client_cache_update": client_cache(svc, uid, cards=ids)})


# ---- skill upgrade --------------------------------------------------------------

def _skill_feed(rules: Rules, metals: list, skill_id: int, player_level: int):
    """(exp, food) for feeding these cards to a skill (skills_strengthen_scene.setGainExp):
    each card gives its level's eaten_skill_exp, twice when it carries the same skill."""
    exp, food = 0, 0
    for metal in metals:
        character = rules.characters[str(metal["c_id"])]
        base_row, rate = rules.character_base[str(metal["lv"])], _rate(rules, character)
        gain = base_row["eaten_skill_exp"] * rate.get("eaten_skill_exp_rate", 1)
        doc = rules.card_document(metal, player_level)
        same = any(doc[f"s_{i}"]["s"] == skill_id for i in range(1, SKILL_SLOTS + 1))
        exp += gain * (2 if same else 1)
        food += base_row["skill_strengthen_food"] * rate.get("skill_strengthen_food_rate", 1)
    return int(exp), int(food)


def skill_levelup(req: Request, svc: Services, player: dict):
    uid, rules = player["uid"], Rules.load(svc.configs)
    major_id, pos, metal_ids = req.params.get("major", ""), req.params.get("pos", ""), _ids(req, "metal")
    cards = _owned(svc, uid, [major_id] + metal_ids)
    if cards is None or not metal_ids or not is_int(pos) or not 1 <= int(pos) <= SKILL_SLOTS:
        return fail("error_param", "Nguyên liệu không hợp lệ.")
    major, metals, slot = cards[0], cards[1:], int(pos)
    if any(_in_team(m) for m in metals):
        return fail("error_param", "Không dùng đồng đội đang ra trận làm nguyên liệu.")
    skill = rules.card_document(major, player["level"])[f"s_{slot}"]
    if skill["s"] == 0 or skill["avail"] != ACTIVE:
        return fail("error_param", "Skill chưa mở.")
    if rules.skill_exp_needed(skill["s"], skill["lv"]) is None:
        return fail("error_max_level", "Skill đã đạt cấp tối đa.")

    exp, food = _skill_feed(rules, metals, skill["s"], player["level"])
    result = rules.add_exp(skill["lv"], skill["exp"], exp,
                           lambda lv: rules.skill_exp_needed(skill["s"], lv), 10**6)
    with svc.store.transaction():
        pay(svc, uid, {"food": food})
        _consume(svc, uid, metal_ids)
        svc.store.set_card_skill(major["id"], slot, result.level, result.exp)
    return ok({"_client_cache_update": client_cache(svc, uid, cards=[major["id"]],
                                                    removed_cards=metal_ids)})


# ---- evolution ------------------------------------------------------------------

def _evolution_material(rules: Rules, major: dict, metal: dict) -> bool:
    """Same hero line, or one of the universal evolution cards."""
    mine = rules.characters[str(major["c_id"])].get("character_ID")
    theirs = rules.characters[str(metal["c_id"])].get("character_ID")
    return theirs == mine or theirs in UNIVERSAL_MATERIALS


def evolution(req: Request, svc: Services, player: dict):
    uid, rules = player["uid"], Rules.load(svc.configs)
    major_id, metal_ids = req.params.get("major", ""), _ids(req, "metal")
    cards = _owned(svc, uid, [major_id] + metal_ids)
    if cards is None:
        return fail("error_param", "Đồng đội không hợp lệ.")
    major, metals = cards[0], cards[1:]
    character = rules.characters[str(major["c_id"])]
    row = rules.evolution_table(character).get(str(major["step"] + 1))
    if row is None:
        return fail("error_max_evo", "Đã đạt giai đoạn cao nhất.")
    if major["lv"] < row.get("need_level", 0) or player["level"] < row.get("player_level", 0):
        return fail("error_level", "Chưa đạt cấp độ tiến hóa.")
    needed = min(row.get("exp", 0) // 10, MAX_MATERIALS)
    if len(metals) != needed or any(_in_team(m) or not _evolution_material(rules, major, m)
                                    for m in metals):
        return fail("error_param", "Nguyên liệu không hợp lệ.")
    with svc.store.transaction():
        pay(svc, uid, {"food": character.get("evo_food", 0)})
        _consume(svc, uid, metal_ids)
        svc.store.update_card(uid, major["id"], lv=major["lv"], exp=major["exp"],
                              step=major["step"] + 1)
    return ok({"reward": {}, "_client_cache_update": client_cache(
        svc, uid, cards=[major["id"]], removed_cards=metal_ids)})


# ---- selling --------------------------------------------------------------------

def butcher(req: Request, svc: Services, player: dict):
    """Sell cards for food: character_base sell_food times the type's sell_food_rate."""
    uid, rules = player["uid"], Rules.load(svc.configs)
    ids = _ids(req, "card_id")
    cards = _owned(svc, uid, ids)
    if not ids or cards is None or any(_in_team(c) for c in cards):
        return fail("error_param", "Không thể bán những đồng đội này.")
    food = 0
    for card in cards:
        character = rules.characters[str(card["c_id"])]
        food += int(rules.character_base[str(card["lv"])]["sell_food"]
                    * _rate(rules, character).get("sell_food_rate", 1))
    with svc.store.transaction():
        _consume(svc, uid, ids)
        svc.store.change_wallet(uid, {"food": food})
    return ok({"get_food": food, "_client_cache_update": client_cache(svc, uid, removed_cards=ids)})


HANDLERS = {
    ("api", "cards.set_alignment"): set_alignment,
    ("api", "cards.inherit"): inherit,
    ("api", "cards.card_skill_levelup"): skill_levelup,
    ("api", "cards.card_evolution"): evolution,
    ("api", "cards.butcher"): butcher,
}
