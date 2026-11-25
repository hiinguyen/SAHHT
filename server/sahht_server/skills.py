"""Hero skills as the battle engine runs them.

A spec in `data/skill_specs.json` (see SKILLS.md) is written once per base
skill and covers its whole evolution chain; the numbers of the tier a card
actually has (`effect`, `cd`, `rate`, ...) come from `skill_detail`.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SPECS_PATH = DATA_DIR / "skill_specs.json"
ENEMY_SPECS_PATH = DATA_DIR / "enemy_skill_specs.json"
ANIMS_PATH = DATA_DIR / "skill_anims.json"
LAST_HERO_ID = 38700           # the last hero released in 2018; specs cover heroes up to it
NORMAL_ATTACK_SCRIPT = "skill1"  # every hero animation folder has it

TRIGGER_BY_SKILL_TYPE = {
    "KBEFOREATTACK": "active", "KBEFOREBATTLE": "before_battle",
    "KBEFOREROUND": "before_round", "KBEFOREHERT": "before_hit",
    "KBEATTACK": "after_hit", "KDEAD": "on_death", "KATTACK": "on_attack",
}


@dataclass(frozen=True)
class Skill:
    """One skill tier at one level, ready to run."""
    id: int
    root: int                   # base skill id the spec is keyed by
    trigger: str
    aim: str
    count: int
    effects: tuple
    effect: float               # resolved 'effect' value
    attr: float                 # resolved 'attr' value
    cd: int
    pre_cd: int
    rate: float
    limit_per_round: int        # 0: unlimited
    once: bool
    rounds: tuple               # (first, last) round window
    sprite: str                 # sprite_py without extension, for picking a script

    def value(self, v) -> float:
        if isinstance(v, str):
            sign, word = (-1, v[1:]) if v.startswith("-") else (1, v)
            offset = 0.0
            for separator in ("+", "-"):
                if separator in word:
                    word, _, tail = word.partition(separator)
                    offset = float(tail) * (1 if separator == "+" else -1)
                    break
            base = {"effect": self.effect, "attr": self.attr,
                    "effect100": self.effect / 100, "attr100": self.attr / 100}[word]
            return sign * (base + offset)
        return float(v)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


class SkillBook:
    """Specs, skill_detail and the client's animation scripts, indexed once.

    Heroes and campaign enemies are two separate sets of specs (`skill_specs.json`
    and `enemy_skill_specs.json`) on the same DSL. Ids are unique across both so
    `skill()` needs no source argument.
    """

    def __init__(self, skill_detail: dict, specs: dict, anims: dict, enemy_specs: dict = None):
        enemy_specs = enemy_specs or {}
        duplicates = set(specs) & set(enemy_specs)
        if duplicates:
            raise ValueError(f"skill specs defined twice: {sorted(duplicates)}")
        self._detail = skill_detail
        self._specs = {**specs, **enemy_specs}
        self._anims = {name: frozenset(scripts) for name, scripts in anims.items()}
        self._root = {}
        for base in sorted(int(k) for k in self._specs):
            for tier in self.chain(base):
                self._root.setdefault(tier, base)

    @classmethod
    def load(cls, configs) -> "SkillBook":
        return configs.derived("skill_book", lambda: cls(
            configs.get("skill_detail"), _load_json(SPECS_PATH), _load_json(ANIMS_PATH),
            _load_json(ENEMY_SPECS_PATH)))

    def chain(self, base: int) -> list:
        """The base skill and every tier reached through is_evolution."""
        tiers, current = [], base
        while current and str(current) in self._detail and current not in tiers:
            tiers.append(current)
            current = int(self._detail[str(current)].get("is_evolution") or 0)
        return tiers

    def root(self, skill_id: int):
        return self._root.get(int(skill_id))

    def spec(self, skill_id: int):
        root = self.root(skill_id)
        return None if root is None else self._specs[str(root)]

    def skill(self, skill_id: int, level: int = 1):
        """The runnable skill, or None when the id has no spec (unknown or not a hero skill)."""
        spec, detail = self.spec(skill_id), self._detail.get(str(skill_id))
        if spec is None or detail is None:
            return None
        effect = float(detail.get("effect", 0)) + float(detail.get("effect_lvchange", 0)) * level
        return Skill(
            id=int(skill_id), root=self.root(skill_id),
            trigger=spec.get("trigger") or TRIGGER_BY_SKILL_TYPE.get(detail.get("skill_type"), "active"),
            aim=spec.get("aim", "enemy_front"), count=spec.get("count", 1),
            effects=tuple(spec.get("effects", ())),
            effect=effect, attr=float(detail.get("attr_effect", 0)),
            cd=int(detail.get("cd", 0)), pre_cd=int(detail.get("pre_cd", 0)),
            rate=float(detail.get("rate", 100)),
            limit_per_round=spec.get("limit_per_round", 0), once=spec.get("once", False),
            rounds=tuple(spec.get("rounds", (1, 10**6))),
            sprite=re.sub(r"\.py$", "", detail.get("sprite_py") or ""),
        )

    def script(self, animation: str, skill: Skill, slot: int) -> str:
        """The client script that animates `skill` for a hero drawn with `animation`.

        Prefers the script named by sprite_py (with or without its trailing tier
        digit), then the hero's script for that skill slot, then its normal attack.
        """
        scripts = self._anims.get(animation, frozenset())
        stem = skill.sprite
        for name in (stem, stem.rstrip("0123456789").rstrip("_")):
            if name and name in scripts:
                return name
        slot_pattern = re.compile(rf"_s{slot}(_\d+)?$")
        by_slot = sorted(s for s in scripts if slot_pattern.search(s))
        return by_slot[0] if by_slot else NORMAL_ATTACK_SCRIPT

    def has_animation(self, animation: str) -> bool:
        """Whether the client ships skill scripts for a hero animation."""
        return animation in self._anims

    def hero_skills(self, character: dict) -> list:
        """(slot, base skill id) for every skill slot of a hero."""
        result = []
        for slot in range(1, character.get("skill_num", 0) + 1):
            source = character.get(f"skill_{slot}_source") or []
            if source:
                result.append((slot, int(source[0][0])))
        return result
