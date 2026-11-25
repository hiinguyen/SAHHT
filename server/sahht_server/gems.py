"""Gems: stacks of stones placed on formation positions, and the stats they add.

The client keeps gems as `gem` (key -> count) and `gem_pos` (position "0".."9" -> four
keys, "0" for an empty slot). A key is `"<gem.config id>"` for a plain gem and
`"<evolution level>-<gem.config id>"` for an evolved one (`game_util:getRealGemLvAndCid`).

A gem's `career` decides where it fits: career 1 (attack gems, abilities 201-204) goes
to slot 0, career 2 (defence gems, abilities 301-304 plus a second ability) to slots 1-3
(`game_data:gemInGemPos`).

Stats follow `game_util:getGemCombatValue`: `value + evolution bonus` for `ability`
and `value2 + evolution bonus 2` for `ability2`, where the bonus is the row of
`gem_evolution.config[level].ability` whose first entry is the ability id. The stats
use the same names as equipment (`equipment.STAT_BY_ABILITY`), so a team slot's gem
stats are simply added to its gear stats.
"""

import re
from collections import Counter

from . import equipment

SLOTS = 4                # one attack gem and three defence gems per position
POSITIONS = equipment.POSITIONS
ATTACK_SLOT = 0
DEFENCE_SLOTS = (1, 2, 3)
ATTACK_CAREER, DEFENCE_CAREER = 1, 2
EMPTY = "0"
KEY_RE = re.compile(r"\d+(-\d+)?")   # "1001" or "3-1001"


def split_key(key: str) -> tuple[int, str]:
    """'3-1001' -> (3, '1001'); '1001' -> (0, '1001')."""
    level, _, cid = str(key).partition("-")
    return (int(level), cid) if cid and level.isdigit() else (0, str(key))


def make_key(level: int, cid) -> str:
    return f"{level}-{cid}" if level > 0 else str(cid)


def config(configs, key: str) -> dict | None:
    """The gem.config row of a gem key, or None for an unknown gem."""
    cfg = configs.get("gem").get(split_key(key)[1])
    return cfg if isinstance(cfg, dict) else None


def fits_slot(cfg: dict, slot: int) -> bool:
    career = cfg.get("career")
    if career == ATTACK_CAREER:
        return slot == ATTACK_SLOT
    return career == DEFENCE_CAREER and slot in DEFENCE_SLOTS


def grid(placements) -> dict:
    """The client's gem_pos: position "0".."9" -> four keys, "0" for an empty slot."""
    cells = {str(position): [EMPTY] * SLOTS for position in range(POSITIONS)}
    for position, slot, key in placements:
        if str(position) in cells and 0 <= slot < SLOTS:
            cells[str(position)][slot] = str(key)
    return cells


def placed_counts(placements) -> Counter:
    return Counter(key for _, _, key in placements)


def free_counts(store, uid: str) -> dict:
    """key -> copies not placed on any position (the only ones a gem action may spend)."""
    placed = placed_counts(store.gem_positions(uid))
    free = {key: count - placed.get(key, 0) for key, count in store.gems(uid).items()}
    return {key: count for key, count in free.items() if count > 0}


def _evolution_bonus(configs, level: int, ability: int) -> tuple[int, int]:
    """(bonus for `ability`, second bonus) of an evolution level; (0, 0) when plain."""
    if level <= 0:
        return 0, 0
    row = configs.get("gem_evolution").get(str(level), {})
    for entry in row.get("ability", []):
        if entry and entry[0] == ability:
            return entry[1], entry[2] if len(entry) > 2 else 0
    return 0, 0


def key_stats(configs, key: str) -> dict:
    """The stats one placed gem adds, by stat name."""
    cfg = config(configs, key)
    if cfg is None:
        return {}
    level = split_key(key)[0]
    first, second = _evolution_bonus(configs, level, cfg.get("ability", 0))
    stats = {}
    stat = equipment.STAT_BY_ABILITY.get(cfg.get("ability"))
    if stat:
        stats[stat] = cfg.get("value", 0) + first
    stat2 = equipment.STAT_BY_ABILITY.get(cfg.get("ability2"))
    if stat2:
        stats[stat2] = stats.get(stat2, 0) + cfg.get("value2", 0) + second
    return stats


def bonus(configs, keys) -> dict:
    """Total stats of the gems placed on one position, over every bonus stat name."""
    total = {stat: 0 for stat in equipment.BONUS_KEYS}
    for key in keys:
        if key == EMPTY:
            continue
        for stat, value in key_stats(configs, key).items():
            total[stat] += value
    return total


def add_stats(base: dict, extra: dict) -> dict:
    """Sum two stat dicts (gear + gems) over every bonus stat name."""
    return {stat: base.get(stat, 0) + extra.get(stat, 0) for stat in equipment.BONUS_KEYS}


def keys_by_position(placements) -> dict:
    """position -> the keys placed on it."""
    by_position = {}
    for position, _, key in placements:
        by_position.setdefault(position, []).append(key)
    return by_position
