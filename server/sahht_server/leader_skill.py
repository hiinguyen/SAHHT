"""Leader skills (nộ khí): the party-wide actives bought in the main-hero screen.

The client owns no rule for these either; `leader_skill.config` gives the numbers
(`base_effect1/2` plus `add_effect1/2` per level), `cd`, `ready_time`, `script`
(the client script in `skill_effect/leader_skill/`) and `icon`. This module reads
the curated specs in `data/leader_skill_specs.json` and builds a runnable skill.

Only the 12 skills whose `script` has a file in the APK are specced; the other
config rows are passive nodes whose effect scripts never shipped, so they stay
closed (see `SKILLS.md`).
"""

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SPECS_PATH = DATA_DIR / "leader_skill_specs.json"

# Trees the client draws (skills_practice_scene's four tabs) and the player level
# each one opens at (checkSkillOpen).
TREE_LEVEL = {1: 0, 2: 10, 3: 20, 4: 30}
TREES = tuple(TREE_LEVEL)
RAGE_MAX = 100

# A leader skill's damage source: an aggregate of one side's live units.
LEADER_STATS = ("ally_max_matk", "ally_avg_matk", "ally_max_patk",
                "enemy_max_matk", "enemy_max_patk")
LEADER_TARGETS = ("enemy_all", "enemy_front", "enemy_random", "enemy_lowest_hp",
                  "ally_all", "ally_lowest_hp")
CONTROLS = ("stun", "freeze", "petrify", "sleep", "paralyze", "root", "fear",
            "silence", "chaos", "charm")
OPS = {"damage": {"type", "stat", "scale"}, "control": {"kind", "rounds"}}
VALUE_RE = re.compile(r"^-?effect[12]$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


@dataclass(frozen=True)
class LeaderSkill:
    id: int
    name: str
    script: str
    tree: int
    cd: int
    ready_time: int
    max_level: int
    effect1: float
    effect2: float
    add1: float
    add2: float
    aim: str
    effects: tuple

    def value(self, v) -> float:
        if isinstance(v, str):
            sign = -1 if v.startswith("-") else 1
            word = v[1:] if sign < 0 else v
            return sign * (self.effect1 if word == "effect1" else self.effect2)
        return float(v)

    def at_level(self, level: int) -> "LeaderSkill":
        """The same skill with `add_effect1/2` applied for each level above 1."""
        steps = max(0, level - 1)
        return replace(self, effect1=self.effect1 + self.add1 * steps,
                       effect2=self.effect2 + self.add2 * steps)


def validate(skill_id, spec) -> list:
    """Problems with one leader skill spec, as human-readable strings."""
    where = f"leader skill {skill_id}"
    if not isinstance(spec, dict):
        return [f"{where}: spec must be an object"]
    errors = []
    unknown = set(spec) - {"aim", "effects", "note"}
    if unknown:
        errors.append(f"{where}: unknown keys {sorted(unknown)}")
    if spec.get("aim") not in LEADER_TARGETS:
        errors.append(f"{where}: bad aim {spec.get('aim')!r}")
    effects = spec.get("effects")
    if not isinstance(effects, list) or not effects:
        errors.append(f"{where}: effects must be a non-empty list")
        return errors
    for i, effect in enumerate(effects):
        at = f"{where}.effects[{i}]"
        if not isinstance(effect, dict) or effect.get("op") not in OPS:
            errors.append(f"{at}: unknown op")
            continue
        op = effect["op"]
        if set(effect) - {"op", "target"} - OPS[op]:
            errors.append(f"{at}: unknown keys for {op}")
        scale = effect.get("scale")
        if "scale" in effect and not (VALUE_RE.match(str(scale))
                                      or isinstance(scale, (int, float))):
            errors.append(f"{at}: scale must be a number, 'effect1' or 'effect2'")
        if op == "damage" and effect.get("stat") not in LEADER_STATS:
            errors.append(f"{at}: bad stat {effect.get('stat')!r}")
        if op == "damage" and effect.get("type") not in ("phys", "magic", "true"):
            errors.append(f"{at}: bad damage type {effect.get('type')!r}")
        if op == "control" and effect.get("kind") not in CONTROLS:
            errors.append(f"{at}: bad control {effect.get('kind')!r}")
        if "target" in effect and effect["target"] not in LEADER_TARGETS:
            errors.append(f"{at}: bad target {effect['target']!r}")
    return errors


def validate_all(specs: dict) -> list:
    errors = []
    for key, spec in specs.items():
        if not str(key).isdigit():
            errors.append(f"key {key!r} is not a skill id")
            continue
        errors.extend(validate(key, spec))
    return errors


class LeaderBook:
    """The learnable leader skills, resolved from config plus the curated specs."""

    def __init__(self, config: dict, specs: dict):
        self._skills = {}
        for key, spec in specs.items():
            row = config.get(str(key))
            if not isinstance(row, dict):
                continue
            self._skills[int(key)] = LeaderSkill(
                id=int(key), name=str(row.get("name", "")),
                script=str(row.get("script", "")), tree=int(row.get("tree", 0)),
                cd=int(row.get("cd", 0)), ready_time=int(row.get("ready_time", 0)),
                max_level=int(row.get("max_level", 1)),
                effect1=float(row.get("base_effect1", 0)),
                effect2=float(row.get("base_effect2", 0)),
                add1=float(row.get("add_effect1", 0)),
                add2=float(row.get("add_effect2", 0)),
                aim=spec["aim"], effects=tuple(spec["effects"]))

    @classmethod
    def load(cls, configs) -> "LeaderBook":
        return configs.derived("leader_book", lambda: cls(
            configs.get("leader_skill"), _load_json(SPECS_PATH)))

    def get(self, skill_id) -> LeaderSkill | None:
        return self._skills.get(int(skill_id))

    def ids(self) -> list:
        return sorted(self._skills)

    def spec_file(self) -> dict:
        return _load_json(SPECS_PATH)
