"""Progression rules read from the client configs: levels, card documents, evolution, combat.

Everything here is derived from the same tables the client uses for its own previews,
so what the server grants matches what the client shows:
- player levels: role.config `exp` (experience needed to leave a level);
- card levels: character_base.config `exp` times character_base_rate `exp_rate`;
- evolution: evolution / evolution_3 / _4 / _5 by character_detail `evo_kind`;
- skill tiers: the evolution row's `skill` list (0 locked, n = n-th tier of the skill chain);
- combat power: game_util.getCombatValue, without the gear and bonus terms (none exist yet).
"""

import math
from dataclasses import dataclass

from .equipment import ELEMENT_KEYS
from .skills import SkillBook

SKILL_SLOTS = 5            # skill slots a 5-skill hero has (4-5 are extra swap options)
BATTLE_SKILLS = 3          # slots a card brings to a battle; the rest wait on the bench
STATS = ("hp", "patk", "matk", "def", "speed")
EVOLUTION_STATS = ("patk", "matk", "def", "speed", "hp")   # order of evolution typeN lists
TEAM_COMBAT_SLOTS = 8      # getCombatValue walks team slots 1..8: attack 1-5, bench 6-8
NO_SKILL = {"s": 0, "lv": 0, "exp": 0, "avail": 0}
LOCKED, UNLOCKED, ACTIVE = 0, 1, 2   # skill avail: locked, unlocked not in the battle set, active


@dataclass(frozen=True)
class LevelResult:
    level: int
    exp: int           # progress inside `level`
    gained: int        # experience actually added (capped levels absorb nothing)
    steps: list        # [[level, exp needed], ...] from the old level to the new one


class Rules:
    def __init__(self, configs):
        self._configs = configs
        self.role = configs.get("role")
        self.characters = configs.get("character_detail")
        self.character_base = configs.get("character_base")
        self.rates = configs.get("character_base_rate")
        self.skill_detail = configs.get("skill_detail")
        self.skill_levelup = configs.get("skill_levelup")
        self.combat_base = configs.get("combat_base") or dict.fromkeys(STATS, 0)
        self.combat_skill = configs.get("combat_skill")
        self.break_control = configs.get("break_control")
        self.book = SkillBook.load(configs)

    @classmethod
    def load(cls, configs) -> "Rules":
        return configs.derived("rules", lambda: cls(configs))

    # ---- levels ----------------------------------------------------------

    def player_exp_needed(self, level: int) -> int | None:
        row = self.role.get(str(level))
        return row["exp"] if row and str(level + 1) in self.role else None

    def player_exp_max(self, level: int) -> int:
        """The bar length the client shows; at the top level the last row's value."""
        row = self.role.get(str(level)) or self.role.get(str(len(self.role)), {})
        return row.get("exp", 0)

    def card_exp_needed(self, character: dict, level: int) -> int | None:
        row = self.character_base.get(str(level))
        if row is None or str(level + 1) not in self.character_base:
            return None
        rate = self.rates.get(str(character.get("type", 1)), {}).get("exp_rate", 1)
        return int(row["exp"] * rate)

    def card_level_max(self, player_level: int) -> int:
        """Heroes level up to the player's level (the client leaves the cap to the server)."""
        return max(1, min(player_level, len(self.character_base)))

    @staticmethod
    def add_exp(level: int, exp: int, amount: int, needed, level_max: int) -> LevelResult:
        """Generic level-up walk. `needed(lv)` is the exp to leave lv (None at the top).
        At the cap the bar fills to one point short of the next level and stops."""
        steps = [[level, needed(level) or 0]]
        total = exp + max(0, amount)
        while level < level_max and (need := needed(level)) is not None and total >= need:
            total -= need
            level += 1
            steps.append([level, needed(level) or 0])
        need = needed(level)
        if level >= level_max or need is None:
            total = min(total, max(0, (need or 0) - 1))
        gained = sum(n for _, n in steps[:-1]) + total - exp
        return LevelResult(level, total, max(0, gained), steps)

    def card_pre_exp(self, character: dict, level: int) -> int:
        """Experience spent on the levels below `level` (cards.inherit previews with it)."""
        return sum(self.card_exp_needed(character, lv) or 0 for lv in range(1, level))

    # ---- evolution -------------------------------------------------------

    def evolution_table(self, character: dict) -> dict:
        kind = character.get("evo_kind", character.get("quality", 0))
        name = ("evolution" if kind < 3 else "evolution_3" if kind == 3
                else "evolution_4" if kind == 4 else "evolution_5")
        return self._configs.get(name)

    def evolution_row(self, character: dict, step: int) -> dict:
        table = self.evolution_table(character)
        return table.get(str(step)) or table.get("0") or {"skill": [1, 0, 0]}

    def evolution_bonus(self, character: dict, step: int) -> dict:
        row = self.evolution_row(character, step)
        values = row.get(f"type{character.get('race', 0)}") or [0] * 5
        return {stat: int(v) for stat, v in zip(EVOLUTION_STATS, values)}

    def break_hp_add(self, bre: int) -> float:
        """Share of the hp a card at break level `bre` gains (break_control.config)."""
        return self.break_control.get(str(bre), {}).get("hp_add", 0)

    # ---- skills ----------------------------------------------------------

    def skill_slots(self, character: dict, step: int, chosen=()) -> list:
        """(slot, skill id, avail) for slots 1..skill_num; skill id 0 when the hero has no
        such slot. An evolved slot is unlocked; the three the card chose for battle are
        ACTIVE and the other unlocked ones are UNLOCKED (`avail` 1). Slots 4-5 exist only
        on 5-skill heroes, carry no evolution tier, and start unlocked."""
        tiers = self.evolution_row(character, step).get("skill", [1, 0, 0])
        chosen = set(chosen) if chosen else set(range(1, BATTLE_SKILLS + 1))
        # Slots 1-3 always exist (the client draws them); 4-5 only on 5-skill heroes.
        count = max(BATTLE_SKILLS, min(character.get("skill_num", 0), SKILL_SLOTS))
        slots = []
        for slot in range(1, count + 1):
            source = character.get(f"skill_{slot}_source") or []
            if slot > character.get("skill_num", 0) or not source:
                slots.append((slot, 0, LOCKED))
                continue
            base = source[0][0]
            if slot > BATTLE_SKILLS:
                slots.append((slot, base, ACTIVE if slot in chosen else UNLOCKED))
                continue
            tier = tiers[slot - 1] if slot - 1 < len(tiers) else 0
            chain = self.book.chain(base) or [base]
            if tier <= 0:
                slots.append((slot, base, LOCKED))
            else:
                slots.append((slot, chain[min(tier, len(chain)) - 1],
                              ACTIVE if slot in chosen else UNLOCKED))
        return slots

    def battle_slots(self, card: dict) -> tuple:
        """The skill slots a card casts in battle: its saved choice, else the first three."""
        chosen = card.get("battle_slots") or []
        return tuple(chosen) if len(chosen) == BATTLE_SKILLS else tuple(range(1, BATTLE_SKILLS + 1))

    def skill_exp_needed(self, skill_id: int, level: int) -> int | None:
        detail = self.skill_detail.get(str(skill_id), {})
        if level >= detail.get("max_lv", len(self.skill_levelup)):
            return None
        row = self.skill_levelup.get(str(level))
        if row is None:
            return None
        return row[min(detail.get("skill_quality", 0), len(row) - 1)]

    # ---- card document ---------------------------------------------------

    def card_document(self, card: dict, player_level: int) -> dict:
        """A card as the client reads it. The client never derives stats, so send them."""
        character = self.characters[str(card["c_id"])]
        lv, step = card["lv"], card["step"]
        doc = {
            "id": card["id"], "c_id": card["c_id"], "lv": lv,
            "level_max": self.card_level_max(player_level),
            "exp": card["exp"], "pre_exp": self.card_pre_exp(character, lv),
            "step": step, "evo": step, "bre": card.get("bre", 0), "star": 0,
            "quality": character.get("quality", 0),
            # Server-side: the three skill slots this card casts in battle.
            "battle_slots": list(self.battle_slots(card)),
            # The client reads "user" here as the player's lock; other flags are team,
            # training and dispatch, none of which this server stores.
            "remove_avail": ["user"] if card.get("locked") else [],
        }
        bonus = self.evolution_bonus(character, step)
        for stat in STATS:
            doc[stat] = (character[f"base_{stat}"] + character[f"growth_{stat}"] * (lv - 1)
                         + bonus.get(stat, 0))
        # The break level ("bre") scales the hp only, as the client's own stat preview does.
        doc["hp"] = int(doc["hp"] * (1 + self.break_hp_add(doc["bre"])))
        progress = card.get("skills", {})
        for slot, skill_id, avail in self.skill_slots(character, step, self.battle_slots(card)):
            if skill_id == 0:
                doc[f"s_{slot}"] = dict(NO_SKILL)
                continue
            skill_lv, skill_exp = progress.get(slot, (1, 0))
            doc[f"s_{slot}"] = {"s": skill_id, "lv": skill_lv, "exp": skill_exp, "avail": avail}
        return doc

    # ---- combat power ----------------------------------------------------

    def card_combat(self, doc: dict, fate: dict | None = None) -> float:
        factor = 1.0
        for slot in range(1, SKILL_SLOTS + 1):
            skill = doc.get(f"s_{slot}") or NO_SKILL
            if skill["s"] == 0 or skill["avail"] != ACTIVE or skill["lv"] <= 0:
                continue
            row = self.combat_skill.get(str(skill["lv"]))
            quality = self.skill_detail.get(str(skill["s"]), {}).get("skill_quality", -1)
            if row and 0 <= quality <= 7:
                factor += row.get(str(quality), 0)
        # Fate scales a whole stat (card + gear) before it enters combat, as getCombatValue.
        base = sum(math.floor(doc[stat] * self.combat_base.get(stat, 0)
                              * (1 + (fate or {}).get(stat, 0) / 100)) for stat in STATS)
        # Elemental stats enter combat power at face value, outside the skill factor
        # (getCombatValue's COMBAT_ABILITY_TABLE.card loop).
        elemental = sum(doc.get(stat, 0) for stat in ELEMENT_KEYS)
        return base * factor + elemental

    def team_combat(self, docs_by_slot: dict, fates_by_slot: dict | None = None) -> int:
        """Combat power of the attack and bench slots (team slots 1..8)."""
        fates = fates_by_slot or {}
        return int(sum(self.card_combat(doc, fates.get(slot))
                       for slot, doc in docs_by_slot.items()
                       if slot < TEAM_COMBAT_SLOTS))
