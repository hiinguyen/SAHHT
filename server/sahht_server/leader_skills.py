"""Leader skills over the protocol: the main-hero screen (view 15, `skills_practice_scene`).

The client keeps the whole harbor document in one place and expects every reply to
carry `available_skill` (id -> learned level), `leader_skill` (the three equipped ids)
and `skill_point`; a null there is an unguarded Lua index.
"""

from .handlers import Request, Services, fail, is_int, ok
from .leader_skill import TREES, TREE_LEVEL, LeaderBook
from .rewards import pay


def document(svc: Services, player: dict) -> dict:
    """The harbor document every leader-skill method answers with."""
    book = LeaderBook.load(svc.configs)
    levels, slots = svc.store.leader_skills(player["uid"])
    learned = {skill_id: lv for skill_id, lv in levels.items() if book.get(skill_id)}
    return {
        "available_skill": {str(k): v for k, v in sorted(learned.items())},
        "leader_skill": {f"skill_{i + 1}": (slots[i] if i < len(slots) else 0)
                         for i in range(3)},
        # The tree-point pop indexes these two numbers; the tree system is closed.
        "skill_point": {str(tree): [0, 0] for tree in TREES},
        "available_tree": {},
    }


def open(req: Request, svc: Services, player: dict):
    return ok(document(svc, player))


def train(req: Request, svc: Services, player: dict):
    """Learn or upgrade one skill with the `star` currency (`is_max=1`: as far as paid)."""
    uid, raw = player["uid"], req.params.get("skill", "")
    book = LeaderBook.load(svc.configs)
    skill = book.get(int(raw)) if is_int(raw) else None
    if skill is None:
        return fail("error_not_open", "Kĩ năng chưa mở.")
    if player["level"] < TREE_LEVEL.get(skill.tree, 0):
        return fail("error_level", "Chưa đủ cấp mở nhánh kĩ năng này.")
    levels, _ = svc.store.leader_skills(uid)
    level = levels.get(skill.id, 0)
    if level >= skill.max_level:
        return fail("error_max_level", "Kĩ năng đã đạt cấp tối đa.")
    develop = svc.configs.get("leader_skill_develop").get(str(skill.id)) or {}
    stars = svc.store.wallet(uid).get("star", 0)
    wanted = range(level + 1, skill.max_level + 1) if req.params.get("is_max") == "1" \
        else [level + 1]
    total, reached = 0, level
    for next_level in wanted:
        cost = int(develop.get(f"star_{next_level}", 0))
        if total + cost > stars:
            break
        total += cost
        reached = next_level
    if reached == level:
        return fail("error_not_enough", "Không đủ Tinh Tú.")
    with svc.store.transaction():
        pay(svc, uid, {"star": total})
        svc.store.set_leader_skill_level(uid, skill.id, reached)
    return ok(document(svc, player))


def set_skill(req: Request, svc: Services, player: dict):
    """Equip three learned skills (`0` empties a slot); the client sends all three."""
    uid = player["uid"]
    book = LeaderBook.load(svc.configs)
    levels, _ = svc.store.leader_skills(uid)
    slots = []
    for i in range(1, 4):
        raw = req.params.get(f"skill_{i}", "0")
        if not is_int(raw):
            return fail("error_param", "Kĩ năng không hợp lệ.")
        skill_id = int(raw)
        if skill_id and (book.get(skill_id) is None or not levels.get(skill_id)):
            return fail("error_param", "Kĩ năng chưa học.")
        if skill_id and skill_id in slots:
            return fail("error_param", "Kĩ năng bị lặp.")
        slots.append(skill_id)
    svc.store.set_leader_skill_slots(uid, slots)
    return ok({"leader_skill": document(svc, player)["leader_skill"]})


HANDLERS = {
    ("api", "leader_skill.open"): open,
    ("api", "leader_skill.train"): train,
    ("api", "leader_skill.set_skill"): set_skill,
}
