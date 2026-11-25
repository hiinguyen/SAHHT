"""Equipment documents, the equipped grid, and the stat bonus gear gives a team slot.

An equipment instance is `{id, c_id, lv, st_lv}` plus an `extra` dict holding the fields
features add later (refine, enchant, forge, fate, and their pending rolls). The client
derives the two base attributes from `equip.config` (`value1/value2` plus
`level_add1/level_add2` per level) and the `ability1/ability2` stat index: 1 patk,
2 matk, 3 def, 4 speed, 5 hp.

`bonus()` adds, exactly where the client's `getCombatValue` adds them, the two base
attributes, the suit effects, `equip_refine` and the forge attributes. Fate (`bind_data`)
is a percentage applied to the card's whole stat, so it is a separate `fate_percent`.
Fields that feed the elemental attributes (`is_enchant`/`atts`, suit `att_type` over 5)
are sent to the client but the battle engine has no elemental stats yet.
"""

import math

SLOTS = 4                 # equip.config sort 1-4 -> slot 0-3
POSITIONS = 10            # team positions 0-9 (5 attack, 5 bench)
# game_config.lua PUBLIC_ABILITY_TABLE: id -> the stat name the client uses.
STAT_BY_ABILITY = {
    1: "patk", 2: "matk", 3: "def", 4: "speed", 5: "hp",
    6: "crit", 7: "hit", 8: "subhurt", 9: "dodge",
    201: "fire", 202: "water", 203: "wind", 204: "earth",
    301: "fire_dfs", 302: "water_dfs", 303: "wind_dfs", 304: "earth_dfs",
}
STAT_KEYS = ("hp", "patk", "matk", "def", "speed")
ELEMENT_ATTACKS = ("fire", "water", "wind", "earth")
ELEMENT_DEFENSES = ("fire_dfs", "water_dfs", "wind_dfs", "earth_dfs")
# The percentage-point stats gear can add (forge rows 6-9).
SECONDARY_KEYS = ("crit", "hit", "subhurt", "dodge")
ELEMENT_KEYS = ELEMENT_ATTACKS + ELEMENT_DEFENSES
BONUS_KEYS = STAT_KEYS + SECONDARY_KEYS + ELEMENT_KEYS
SUIT_PIECES = 4           # suit.config `part` lists one config per slot
SUIT_MIN, SUIT_MAX = 2, 4  # effect_2/3/4 turn on at that many matching pieces
FORGE_BATTLE_SORTS = 9    # forge rows 1-5 are flat stats; 6-9 are crit/hit/subhurt/dodge
PENDING = "_pending"      # extra keys ending in _pending are rolls not saved yet
INTERNAL = "_"            # extra keys starting with _ are server bookkeeping
EQUIP_MAX = 100           # the bag size the client shows and the server enforces


def extra(row: dict) -> dict:
    """The feature fields of a stored piece (empty for a plain row)."""
    return row.get("extra") or {}


def document(row: dict) -> dict:
    """One equipment as `cards.open` and `_client_cache_update` send it."""
    doc = {"id": str(row["id"]), "c_id": row["c_id"], "lv": row["lv"],
           "st_lv": row.get("st_lv", 0)}
    fields = extra(row)
    doc.update({k: v for k, v in fields.items()
                if not k.startswith(INTERNAL) and not k.endswith(PENDING)})
    # The client tests these two flags (`== true`) to draw the enchant and forge rows.
    if fields.get("equip_forge"):
        doc["is_equip_forge"] = True
    return doc


def documents(rows) -> dict:
    return {row["id"]: document(row) for row in rows}


def grid(placements) -> dict:
    """The client's equip_pos: position "0".."9" -> four ids, "0" for an empty slot."""
    cells = {str(position): ["0"] * SLOTS for position in range(POSITIONS)}
    for position, slot, equip_id in placements:
        if str(position) in cells and 0 <= slot < SLOTS:
            cells[str(position)][slot] = str(equip_id)
    return cells


def slot_of(configs, c_id) -> int | None:
    """The grid slot an equip config belongs to, or None for an unknown config."""
    row = configs.get("equip").get(str(c_id))
    if not isinstance(row, dict):
        return None
    sort = row.get("sort", 0)
    return sort - 1 if 1 <= sort <= SLOTS else None


def _suit_row(configs, suit_id) -> dict | None:
    row = configs.get("suit").get(str(suit_id))
    return row if isinstance(row, dict) else None


def _suit_count(equip_cfg: dict, suit_part: list, worn: dict) -> int:
    """How many of a suit's parts the slot holds (the client's getEquipSuit count).

    A part matches when the piece in that part's `sort` slot has the same `equip_id`
    family as the part's config, so evolved pieces still count.
    """
    count = 0
    for part_c_id in suit_part:
        part = equip_cfg.get(str(part_c_id))
        if not isinstance(part, dict):
            continue
        piece = worn.get(part.get("sort"))
        if piece and piece.get("equip_id") == part.get("equip_id"):
            count += 1
    return count


def _suit_stats(configs, equip_ids, by_id: dict) -> dict:
    """The attributes suit effects 2/3/4 add; att types over 5 are elemental."""
    stats = {stat: 0 for stat in BONUS_KEYS}
    equip_cfg = configs.get("equip")
    worn, suits = {}, set()
    for equip_id in equip_ids:
        row = by_id.get(str(equip_id))
        cfg = equip_cfg.get(str(row["c_id"])) if row else None
        if not isinstance(cfg, dict):
            continue
        sort = cfg.get("sort")
        if isinstance(sort, int):
            worn[sort] = cfg
        suits.add(cfg.get("suit", 0))
    for suit_id in suits:
        suit = _suit_row(configs, suit_id)
        parts = suit.get("part") if suit else None
        if not suit or not isinstance(parts, list) or len(parts) != SUIT_PIECES:
            continue
        count = _suit_count(equip_cfg, parts, worn)
        for pieces in range(SUIT_MIN, SUIT_MAX + 1):
            if pieces > count:
                break
            for att_type, value in suit.get(f"effect_{pieces}", []):
                stat = STAT_BY_ABILITY.get(att_type)
                if stat is not None:
                    stats[stat] += value
    return stats


def _refine_stats(configs, cfg: dict, fields: dict, stats: dict) -> None:
    """`equip_refine` feeds the piece's own two abilities, exactly as game_util does."""
    refine = fields.get("equip_refine")
    if not isinstance(refine, dict):
        return
    for ability_key in ("ability1", "ability2"):
        stat = STAT_BY_ABILITY.get(cfg.get(ability_key))
        if stat is not None:
            stats[stat] += int(refine.get(stat, 0))


def _forge_stats(configs, fields: dict, stats: dict) -> None:
    """`equip_forge` rows 1-5 are flat stats, 6-9 crit/hit/subhurt/dodge; enemy
    (debuff) rows are not applied."""
    forge = fields.get("equip_forge")
    if not isinstance(forge, dict):
        return
    rows = configs.get("equip_set_random")
    for property_id, values in forge.items():
        row = rows.get(str(property_id))
        if not isinstance(row, dict) or not isinstance(values, dict) or not values:
            continue
        sort = row.get("sort", 0)
        enemy = row.get("enemy") or []
        if not 1 <= sort <= FORGE_BATTLE_SORTS or (enemy and enemy[0] == -1):
            continue
        stat = STAT_BY_ABILITY.get(sort)
        if stat is not None:
            value = next(iter(values.values()), 0)
            stats[stat] += float(value)


def _enchant_stats(fields: dict, stats: dict) -> None:
    """`atts` holds the enchant result keyed by stat name (only the eight element keys)."""
    atts = fields.get("atts")
    if not isinstance(atts, dict) or not fields.get("is_enchant"):
        return
    for key, value in atts.items():
        if key in ELEMENT_KEYS:
            stats[key] += int(value)


def bonus(configs, equip_ids, by_id: dict) -> dict:
    """The stats four equipped ids add to their card: attributes, suit, refine, forge
    and enchant. Elemental and percentage-point stats are included; combat power adds
    only the elemental part (see progression.card_combat)."""
    stats = {stat: 0 for stat in BONUS_KEYS}
    equip_cfg = configs.get("equip")
    for equip_id in equip_ids:
        row = by_id.get(str(equip_id))
        if row is None:
            continue
        cfg = equip_cfg.get(str(row["c_id"]))
        if not isinstance(cfg, dict):
            continue
        levels = max(0, row.get("lv", 1) - 1)
        for value_key, add_key, ability_key in (("value1", "level_add1", "ability1"),
                                                ("value2", "level_add2", "ability2")):
            stat = STAT_BY_ABILITY.get(cfg.get(ability_key))
            if stat is not None:
                stats[stat] += cfg.get(value_key, 0) + cfg.get(add_key, 0) * levels
        fields = extra(row)
        _refine_stats(configs, cfg, fields, stats)
        _forge_stats(configs, fields, stats)
        _enchant_stats(fields, stats)
    suit = _suit_stats(configs, equip_ids, by_id)
    return {stat: stats[stat] + suit[stat] for stat in BONUS_KEYS}


def bound_by_card(configs, rows) -> dict[str, dict[str, str]]:
    """card id -> {equip sort: equipment id} for the pieces fate-bound to that card."""
    equip_cfg = configs.get("equip")
    bound = {}
    for row in rows:
        card_id = extra(row).get("bind_card")
        cfg = equip_cfg.get(str(row["c_id"])) if card_id else None
        if not isinstance(cfg, dict) or not card_id:
            continue
        bound.setdefault(str(card_id), {})[str(cfg.get("sort", 0))] = str(row["id"])
    return bound


def add_bound_equipment(configs, rows, docs: dict) -> dict:
    """Add `bind_equip` (sort -> id) to the cards that have fate-bound gear."""
    for card_id, pieces in bound_by_card(configs, rows).items():
        if card_id in docs:
            docs[card_id]["bind_equip"] = pieces
    return docs


def fate_percent(configs, equip_ids, by_id: dict) -> dict:
    """The per-stat percentage fate-bound pieces add to their card (bind_data keys are
    ability indexes as strings; only the five base stats are bound)."""
    percent = {stat: 0.0 for stat in STAT_KEYS}
    for equip_id in equip_ids:
        row = by_id.get(str(equip_id))
        bound = extra(row).get("bind_data") if row else None
        if not isinstance(bound, dict):
            continue
        for ability, value in bound.items():
            stat = STAT_BY_ABILITY.get(int(ability)) if str(ability).isdigit() else None
            if stat is not None:
                percent[stat] += float(value)
    return percent


def with_bonus(doc: dict, stats: dict) -> dict:
    return {**doc, **{stat: doc.get(stat, 0) + stats.get(stat, 0) for stat in BONUS_KEYS}}


def apply_fate(doc: dict, percent: dict) -> dict:
    """Scale every stat by its fate percentage, as `getCombatValue` does (floor)."""
    return {**doc, **{stat: math.floor(doc.get(stat, 0) * (1 + percent.get(stat, 0) / 100))
                      for stat in STAT_KEYS if percent.get(stat)}}
