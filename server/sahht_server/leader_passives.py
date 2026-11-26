"""Passive leader-skill nodes: the 36 non-cast nodes of the four trees the client draws.

`leader_skill.config` gives each node a story and `base_effect1 + add_effect1 * level`; the
client owns no rule for them, so `data/leader_passive_specs.json` says what each one does as a
list of effects with a `kind` from `KINDS`. A node's value at its learned level is
`fixed`, else `per_level * level`, else `base_effect1 + add_effect1 * level` (the same
formula the shipped `331`/`333` rows use for "reduction, recovering 7% per level").

An effect names the cast skills it modifies: a list of skill ids, or `"tree"` for every skill
of the node's own tree. `LeaderMods` answers the engine's questions about the learned set.
"""

import json
from dataclasses import dataclass
from pathlib import Path

PASSIVE_SPECS_PATH = Path(__file__).resolve().parent.parent / "data" / "leader_passive_specs.json"

# kind -> the parameters it takes besides the common `kind`, `skills`, `fixed`, `per_level`.
KINDS = {
    "damage_up": {"vs"},                 # +value% damage; vs: stunned | slowed | burning
    "rage_cost": set(),                  # -value rage to cast
    "free_cast": set(),                  # value% chance a cast costs no rage
    "control_chance": {"control", "rounds"},   # value% chance to leave a control on the target
    "slow_chance": {"pct", "rounds"},    # value% chance to cut the target's speed by pct
    "burn_chance": {"scale", "rounds"},  # value% chance to burn: scale% of max HP per round
    "burn_up": set(),                    # +value% burn damage
    "extra_targets": {"count", "reduction_scale"},   # hit `count` more; value*scale% less each
    "extra_hit": set(),                  # value% chance to hit one more random enemy
    "crit_chance": set(),                # value% chance the hit crits (x1.5)
    "crit_damage": set(),                # +value% crit damage
    "falloff_down": set(),               # the per-target damage falloff shrinks by value
    "atk_down": {"stat", "rounds"},      # target loses value% of stat
    "ally_buff_chance": {"stats", "pct", "rounds"},   # value% chance allies gain pct% of stats
    "bonus_damage": {"stat", "low", "high"},   # value% chance of an extra hit: stat * low..high%
    "rage_start": set(),                 # +value rage when the battle starts
    "rage_on_hit": set(),                # value% chance of +1 rage when an ally is hit
    "rage_keep": set(),                  # a cast leaves at least value rage
}
NO_SKILLS = {"rage_start", "rage_on_hit", "rage_keep"}
COMMON = {"kind", "skills", "fixed", "per_level"}
VS = {"stunned": lambda unit: "stun" in unit.controls,
      "slowed": lambda unit: any(b.stat == "speed" and b.total < 0 for b in unit.buffs),
      "burning": lambda unit: unit.has("burn")}


@dataclass(frozen=True)
class PassiveEffect:
    kind: str
    tree: int
    skills: object        # tuple of skill ids, or "tree"
    value: float
    params: dict

    def applies(self, skill) -> bool:
        return skill.tree == self.tree if self.skills == "tree" else skill.id in self.skills


@dataclass(frozen=True)
class Passive:
    id: int
    effects: tuple


def effect_value(effect: dict, base: float, add: float, level: int) -> float:
    if "fixed" in effect:
        return float(effect["fixed"])
    if "per_level" in effect:
        return float(effect["per_level"]) * level
    return base + add * level


def make_passive(skill_id: int, tree: int, row: dict, spec: dict, level: int) -> Passive:
    """A learned node at `level`: its spec's effects with their values worked out."""
    base, add = float(row.get("base_effect1", 0)), float(row.get("add_effect1", 0))
    effects = []
    for raw in spec["effects"]:
        skills = raw.get("skills")
        params = {k: v for k, v in raw.items() if k not in COMMON}
        effects.append(PassiveEffect(
            raw["kind"], tree, tuple(skills) if isinstance(skills, list) else skills,
            effect_value(raw, base, add, level), params))
    return Passive(skill_id, tuple(effects))


def validate(skill_id, spec) -> list:
    """Problems with one passive spec, as human-readable strings."""
    where = f"passive {skill_id}"
    if not isinstance(spec, dict) or set(spec) - {"effects", "note"}:
        return [f"{where}: spec must be an object with `effects` and an optional `note`"]
    effects = spec.get("effects")
    if not isinstance(effects, list) or not effects:
        return [f"{where}: effects must be a non-empty list"]
    errors = []
    for i, effect in enumerate(effects):
        at = f"{where}.effects[{i}]"
        kind = effect.get("kind") if isinstance(effect, dict) else None
        if kind not in KINDS:
            errors.append(f"{at}: unknown kind {kind!r}")
            continue
        if set(effect) - COMMON - KINDS[kind]:
            errors.append(f"{at}: unknown keys {sorted(set(effect) - COMMON - KINDS[kind])}")
        skills = effect.get("skills")
        if kind in NO_SKILLS:
            if skills is not None:
                errors.append(f"{at}: {kind} takes no skills")
        elif skills != "tree" and not (isinstance(skills, list) and skills
                                       and all(isinstance(s, int) for s in skills)):
            errors.append(f"{at}: skills must be a list of ids or 'tree'")
        if kind == "damage_up" and "vs" in effect and effect["vs"] not in VS:
            errors.append(f"{at}: bad vs {effect['vs']!r}")
    return errors


def validate_all(specs: dict) -> list:
    errors = []
    for key, spec in specs.items():
        if not str(key).isdigit():
            errors.append(f"key {key!r} is not a skill id")
            continue
        errors.extend(validate(key, spec))
    return errors


def load_specs() -> dict:
    return json.loads(PASSIVE_SPECS_PATH.read_text(encoding="utf-8")) \
        if PASSIVE_SPECS_PATH.is_file() else {}


class LeaderMods:
    """What the player's learned passive nodes do to a battle. Empty: nothing changes."""

    def __init__(self, passives=()):
        self._effects = [e for p in passives for e in p.effects]

    def effects(self, kind: str, skill=None) -> list:
        return [e for e in self._effects
                if e.kind == kind and (skill is None or e.applies(skill))]

    def total(self, kind: str, skill=None) -> float:
        return sum(e.value for e in self.effects(kind, skill))

    def damage_pct(self, skill, target) -> float:
        """Damage bonus on one target; `vs` bonuses count only while the status holds."""
        return sum(e.value for e in self.effects("damage_up", skill)
                   if "vs" not in e.params or VS[e.params["vs"]](target))

    def keep_rage(self) -> float:
        return max((e.value for e in self.effects("rage_keep")), default=0.0)
