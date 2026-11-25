"""Schema of the curated skill specs in `data/skill_specs.json` (see SKILLS.md).

The original server ran one Python script per skill (`sprite_py`); none of them
shipped. Each skill chain is therefore described once, by hand, as a list of
effects the battle engine (`battle.py`) knows how to run. This module is the
single definition of that vocabulary: the engine imports its constants and the
tests and curation tooling call `validate`.

Run `python3 -m sahht_server.skill_spec <specs.json>...` to check files.
"""

import json
import re
import sys

TRIGGERS = (
    "active",         # KBEFOREATTACK: replaces the unit's normal attack when ready
    "before_battle",  # KBEFOREBATTLE: once, before round 1
    "before_round",   # KBEFOREROUND: at the start of every round
    "before_hit",     # KBEFOREHERT: when the unit is about to be hit
    "after_hit",      # KBEATTACK: after the unit was hit and survived
    "on_death",       # KDEAD: when the unit dies
    "on_attack",      # KATTACK: after the unit's own attack or skill landed
    "passive",        # always on: its buffs are applied before battle, silently
)

ENEMY_TARGETS = (
    "enemy_front", "enemy_back", "enemy_row_front", "enemy_row_back", "enemy_line",
    "enemy_all", "enemy_random", "enemy_lowest_hp", "enemy_highest_hp",
    "enemy_highest_atk", "enemy_fastest",
)
ALLY_TARGETS = (
    "ally_all", "ally_others", "ally_lowest_hp", "ally_random", "ally_front",
    "ally_dead",
)
TARGETS = ("self", "target", "hit") + ENEMY_TARGETS + ALLY_TARGETS

STATS = (
    "patk", "matk", "def", "speed", "max_hp", "all",      # percent of the unit's base value
    "crit", "dodge", "hit",                                 # percentage points
    "dmg_dealt", "dmg_taken", "heal_taken",                 # percentage points
    "lifesteal", "reflect",                                 # percent of damage dealt / taken
    "attr_atk", "attr_def",                                 # percent of element stats
)
CONTROLS = ("stun", "freeze", "petrify", "sleep", "paralyze", "root", "fear",
            "silence", "chaos", "charm")
DOTS = ("burn", "bleed", "poison")
DAMAGE_TYPES = ("phys", "magic", "true")
DAMAGE_STATS = ("patk", "matk", "def", "speed", "max_hp", "hp_lost",
                "target_max_hp", "target_hp", "target_def", "damage_taken")
HEAL_OF = ("max_hp", "lost_hp", "patk", "matk", "def", "damage")
DOT_OF = ("target_max_hp", "patk", "matk")
SHIELD_OF = ("max_hp", "patk", "matk", "def")
ELEMENTS = ("fire", "water", "wind", "earth", "own")
STATUSES = CONTROLS + DOTS + ("control", "debuff", "buff", "shield", "invincible")

# name -> regex for the argument after ':' (None: no argument)
CONDITIONS = {
    "target_has": re.compile(r"^(%s)$" % "|".join(STATUSES)),
    "target_lacks": re.compile(r"^(%s)$" % "|".join(STATUSES)),
    "self_has": re.compile(r"^(%s)$" % "|".join(STATUSES)),
    "self_state": re.compile(r"^[a-z_]+$"),
    "self_lacks_state": re.compile(r"^[a-z_]+$"),
    "target_boss": None,
    "target_not_boss": None,
    "target_race": re.compile(r"^[0-5]$"),
    "target_not_race": re.compile(r"^[0-5]$"),
    "enemy_has_race": re.compile(r"^[0-5]$"),
    "ally_has_race": re.compile(r"^[0-5]$"),
    "ally_lacks_race": re.compile(r"^[0-5]$"),
    "target_hp_below": re.compile(r"^\d+$"),
    "target_hp_above": re.compile(r"^\d+$"),
    "self_hp_below": re.compile(r"^\d+$"),
    "self_hp_above": re.compile(r"^\d+$"),
    "round_ge": re.compile(r"^\d+$"),
    "round_le": re.compile(r"^\d+$"),
    "target_atk_higher": None,
    "target_atk_lower": None,
    "target_speed_higher": None,
    "target_count": re.compile(r"^\d+(,\d+)*$"),
    "normal_attack": None,
}

_COMMON = {"op", "target", "chance", "if", "count"}
OPS = {
    "damage": {"type", "scale", "stat", "ignore_def", "hits", "bonus", "crit",
               "sure_hit", "crit_bonus"},
    "attr_damage": {"element", "scale"},
    "heal": {"scale", "of"},
    "buff": {"stat", "value", "rounds", "max_stack"},
    "control": {"kind", "rounds"},
    "dot": {"kind", "scale", "of", "rounds"},
    "shield": {"scale", "of", "rounds"},
    "invincible": {"rounds", "hits"},
    "immune_control": {"rounds", "times"},
    "dispel": {"what"},
    "revive": {"scale"},
    "execute": {"below"},
    "hp_cost": {"scale", "of"},
    "rage": {"value", "side"},
    "state": {"name", "rounds"},
    "extra_action": set(),
}
# Ops whose target defaults to the caster; every other op must name a target.
SELF_DEFAULT_OPS = ("revive", "state", "extra_action", "rage")
REQUIRED = {
    "damage": ("type", "scale"), "attr_damage": ("element", "scale"),
    "heal": ("scale", "of"), "buff": ("stat", "value", "rounds"),
    "control": ("kind", "rounds"), "dot": ("kind", "scale", "of", "rounds"),
    "shield": ("scale", "of"), "dispel": ("what",), "revive": ("scale",),
    "execute": ("below",), "hp_cost": ("scale", "of"), "rage": ("value", "side"),
    "state": ("name", "rounds"),
}
ENUMS = {
    ("damage", "type"): DAMAGE_TYPES, ("damage", "stat"): DAMAGE_STATS,
    ("damage", "crit"): ("always", "never"),
    ("attr_damage", "element"): ELEMENTS, ("heal", "of"): HEAL_OF,
    ("buff", "stat"): STATS, ("control", "kind"): CONTROLS,
    ("dot", "kind"): DOTS, ("dot", "of"): DOT_OF, ("shield", "of"): SHIELD_OF,
    ("dispel", "what"): ("debuffs", "buffs", "all"), ("hp_cost", "of"): ("max_hp", "hp"),
    ("rage", "side"): ("ally", "enemy"),
}
SPEC_KEYS = {"trigger", "aim", "count", "limit_per_round", "once", "rounds",
             "effects", "note"}


VALUE_WORDS = ("effect", "attr", "-effect", "-attr")
# A number, or one of the words above; `effect100` / `attr100` are the same value
# divided by 100 (tables whose effect is written in basis points), and an optional
# `+n` / `-n` adds to it ("effect+20").
VALUE_RE = re.compile(r"^-?(effect|attr)(100)?([+-]\d+(?:\.\d+)?)?$")


def is_value(v) -> bool:
    """A number, or 'effect' / 'attr' / 'effect100' / 'attr100' with an optional offset."""
    return ((isinstance(v, str) and VALUE_RE.match(v) is not None)
            or (isinstance(v, (int, float)) and not isinstance(v, bool)))


def _positive_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _check_condition(cond, where, errors):
    for c in cond if isinstance(cond, list) else [cond]:
        if not isinstance(c, str):
            errors.append(f"{where}: condition must be a string")
            continue
        name, _, arg = c.partition(":")
        if name not in CONDITIONS:
            errors.append(f"{where}: unknown condition {name!r}")
        elif CONDITIONS[name] is None and arg:
            errors.append(f"{where}: condition {name} takes no argument")
        elif CONDITIONS[name] is not None and not CONDITIONS[name].match(arg):
            errors.append(f"{where}: bad argument for {name}: {arg!r}")


def _check_bonus(bonuses, where, errors):
    if not isinstance(bonuses, list):
        errors.append(f"{where}: bonus must be a list")
        return
    for i, bonus in enumerate(bonuses):
        bw = f"{where}.bonus[{i}]"
        if not isinstance(bonus, dict) or set(bonus) - {"if", "pct"} or "pct" not in bonus:
            errors.append(f"{bw}: bonus must be {{'if': cond, 'pct': value}}")
            continue
        if not is_value(bonus["pct"]):
            errors.append(f"{bw}: pct must be a number or 'effect'")
        if "if" in bonus:
            _check_condition(bonus["if"], bw, errors)


def _check_fields(e, op, where, errors):
    for key in REQUIRED.get(op, ()):
        if key not in e:
            errors.append(f"{where}: {op} needs {key}")
    for key in ("scale", "value", "ignore_def", "below", "chance", "crit_bonus"):
        if key in e and not is_value(e[key]):
            errors.append(f"{where}: {key} must be a number, 'effect' or 'attr'")
    if "sure_hit" in e and not isinstance(e["sure_hit"], bool):
        errors.append(f"{where}: sure_hit must be a bool")
    for key in ("rounds", "hits", "max_stack", "times"):
        if key in e and not (isinstance(e[key], int) and not isinstance(e[key], bool)
                             and e[key] >= 0):
            errors.append(f"{where}: {key} must be a non-negative int")
    if "count" in e and not _positive_int(e["count"]):
        errors.append(f"{where}: count must be a positive int")
    for (eop, key), allowed in ENUMS.items():
        if op == eop and key in e and e[key] not in allowed:
            errors.append(f"{where}: {key} must be one of {allowed}, got {e[key]!r}")
    if op == "state" and not re.match(r"^[a-z_]+$", str(e.get("name", ""))):
        errors.append(f"{where}: state name must be snake_case")


def _check_effect(e, where, errors):
    if not isinstance(e, dict):
        errors.append(f"{where}: effect must be an object")
        return
    op = e.get("op")
    if op not in OPS:
        errors.append(f"{where}: unknown op {op!r}")
        return
    unknown = set(e) - _COMMON - OPS[op]
    if unknown:
        errors.append(f"{where}: unknown keys for {op}: {sorted(unknown)}")
    target = e.get("target", "self" if op in SELF_DEFAULT_OPS else None)
    if op != "rage" and target not in TARGETS:
        errors.append(f"{where}: bad target {target!r}")
    if "if" in e:
        _check_condition(e["if"], where, errors)
    _check_fields(e, op, where, errors)
    if op == "damage" and "bonus" in e:
        _check_bonus(e["bonus"], where, errors)


def _check_spec_fields(spec, where, errors):
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        errors.append(f"{where}: unknown keys {sorted(unknown)}")
    if spec.get("trigger") not in TRIGGERS:
        errors.append(f"{where}: trigger must be one of {TRIGGERS}")
    if "aim" in spec and spec["aim"] not in ENEMY_TARGETS + ALLY_TARGETS + ("self",):
        errors.append(f"{where}: bad aim {spec['aim']!r}")
    for key in ("count", "limit_per_round"):
        if key in spec and not _positive_int(spec[key]):
            errors.append(f"{where}: {key} must be a positive int")
    if "once" in spec and not isinstance(spec["once"], bool):
        errors.append(f"{where}: once must be a bool")
    rounds = spec.get("rounds")
    if rounds is not None and not (isinstance(rounds, list) and len(rounds) == 2
                                   and all(_positive_int(r) for r in rounds)
                                   and rounds[0] <= rounds[1]):
        errors.append(f"{where}: rounds must be [first, last] with 1 <= first <= last")
    if "note" in spec and not isinstance(spec["note"], str):
        errors.append(f"{where}: note must be a string")


def validate(skill_id, spec) -> list:
    """Every problem with one skill spec, as human-readable strings (empty: valid)."""
    where = f"skill {skill_id}"
    if not isinstance(spec, dict):
        return [f"{where}: spec must be an object"]
    errors = []
    _check_spec_fields(spec, where, errors)
    effects = spec.get("effects")
    if not isinstance(effects, list):
        errors.append(f"{where}: effects must be a list")
        return errors
    for i, effect in enumerate(effects):
        _check_effect(effect, f"{where}.effects[{i}]", errors)
    return errors


def validate_all(specs: dict) -> list:
    errors = []
    for skill_id, spec in specs.items():
        if not str(skill_id).isdigit():
            errors.append(f"key {skill_id!r} is not a skill id")
            continue
        errors.extend(validate(skill_id, spec))
    return errors


def main(paths) -> int:
    failed = False
    for path in paths:
        with open(path, encoding="utf-8") as f:
            specs = json.load(f)
        errors = validate_all(specs)
        for error in errors:
            print(f"{path}: {error}")
        print(f"{path}: {len(specs)} specs, {len(errors)} errors")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
