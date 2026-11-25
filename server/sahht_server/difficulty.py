"""Campaign difficulty: how much harder the server makes the APK's enemies, and who they are.

The APK's normal campaign is easy and its enemies are generic mobs (police, zombies) all the
way to the last chapter. The server hardens each enemy on its way into a battle, so the
preview the client shows and the fight the engine runs agree:

* Stats grow along the campaign and take a step up after every milestone, the first city that
  needs player level 20, 30, ... 120. A milestone city is a gate: every enemy there is stronger
  again, and its bosses most of all.
* From `HEROES_FROM` on, enemy slots are filled by released heroes instead of mobs. The era of
  the heroes follows the campaign (old heroes early, the newest of 2018 at the end), bosses
  are always heroes from the top of the era window, and they bring the hero's own skills.

The first `UNTOUCHED` cities stay exactly as the APK ships them: they carry the tutorial.
Everything is derived from the configs and is deterministic: the same enemy of the same city is
always the same hero, so the preview matches the fight and a retry meets the same enemy.
"""

import math
import random
from dataclasses import dataclass

from .skills import LAST_HERO_ID, SkillBook

UNTOUCHED = 5              # campaign cities (by order) left as shipped: the tutorial
HEROES_FROM = 8            # first city where a mob slot may become a hero
MILESTONE_EVERY = 10       # player levels between two milestone cities
FIRST_MILESTONE = 20
HERO_QUALITIES = (3, 4)    # A and S quality; quality 2 heroes are clones used as fodder
GROWTH = 6.5               # extra enemy power the ramp approaches, on top of 1.0
GROWTH_RATE = 3.5          # how fast: the ramp is steep early, flat late (late enemies of the
                           # APK are already far stronger than early ones)
BAND_STEP = 0.03           # extra power per milestone already passed
GATE_POWER = 1.4           # a milestone city
ELITE_POWER = 1.6          # an elite city, over the normal city of the same player level
ELITE_HERO_BONUS = 0.4
BOSS_HP = 2.2              # bosses last longer and hit a little harder
BOSS_ATTACK = 1.25
GATE_BOSS_ATTACK = 1.2     # on top of that, in a milestone city
SKILL_LEVELS = 10
BOSS_SKILL_LEVELS = 3
ERA_SPREAD = 0.12          # share of the hero list a city draws from, either side
BOSS_ERA_SPREAD = 0.04     # bosses draw from a narrower window
MAX_HERO_SHARE = 0.95
HERO_SHARE_RAMP = 55       # cities from HEROES_FROM until mob slots are almost all heroes
GATE_HERO_BONUS = 0.3
MAX_CRIT_BONUS = 25        # extra crit and dodge at the last city, in points


@dataclass(frozen=True)
class Tier:
    """How hard one city is."""
    index: int
    progress: float         # 0 at the first hardened city, 1 at the last
    power: float
    gate: bool
    hero_share: float


@dataclass(frozen=True)
class Hero:
    """A released hero an enemy can wear: look and skills (base skill ids in slot order)."""
    card_id: int
    animation: str
    img: str
    name: str
    race: int
    rgb_sort: int
    skills: tuple


def gate_cities(order: list) -> set:
    """The milestone cities: for each player level 20, 30, ... the first city needing it."""
    top = max((level for _, level in order), default=0)
    return {next(city for city, level in order if level >= need)
            for need in range(FIRST_MILESTONE, top + 1, MILESTONE_EVERY)}


def build_tiers(order: list) -> dict:
    """city -> Tier for a campaign order of (city, player level needed) pairs."""
    gates = gate_cities(order)
    last = max(len(order) - 1 - UNTOUCHED, 1)
    tiers, passed = {}, 0
    for index, (city, _) in enumerate(order):
        gate = city in gates
        if index >= UNTOUCHED:
            progress = (index - UNTOUCHED) / last
            growth = (1 + GROWTH * (1 - math.exp(-GROWTH_RATE * progress))) * (1 + BAND_STEP * passed)
            share = 0.0 if index < HEROES_FROM else min(
                MAX_HERO_SHARE, (index - HEROES_FROM) / HERO_SHARE_RAMP)
            if gate and index >= HEROES_FROM:
                share = min(1.0, share + GATE_HERO_BONUS)
            tiers[city] = Tier(index, progress, growth * (GATE_POWER if gate else 1.0), gate, share)
        passed += gate
    return tiers


def build_elite_tiers(order: list, tiers: dict, elites: list) -> dict:
    """city -> Tier for elite cities (city, player level needed): the normal city reached at
    the same level, harder and more heroes."""
    hardened = [(level, tiers[city]) for city, level in order if city in tiers]
    if not hardened:
        return {}
    result = {}
    for city, level in elites:
        base = next((t for need, t in reversed(hardened) if need <= level), hardened[0][1])
        result[city] = Tier(base.index, base.progress, base.power * ELITE_POWER, False,
                            min(1.0, base.hero_share + ELITE_HERO_BONUS))
    return result


class Difficulty:
    """The tiers of the normal campaign and the hero pool, built once per config set."""

    def __init__(self, order: list, characters: dict, book: SkillBook, elites: list = ()):
        self.tiers = build_tiers(order)
        self.tiers.update(build_elite_tiers(order, self.tiers, list(elites)))
        self.book = book
        self.pool = _hero_pool(characters, book)

    @classmethod
    def load(cls, configs) -> "Difficulty":
        return configs.derived("difficulty", lambda: cls(
            _campaign_order(configs), configs.get("character_detail"), SkillBook.load(configs),
            _campaign_order(configs, elite=True)))

    def harden(self, city: str, enemy_id, enemy: dict) -> dict:
        """The enemy as this city fields it; cities outside the hardened campaign are as shipped."""
        tier = self.tiers.get(str(city))
        if tier is None:
            return enemy
        boss = enemy.get("is_boss") == 1
        hero = self._pick(tier, boss, random.Random(f"{city}:{enemy_id}"))
        return {**self._stats(enemy, tier, boss), **(self._wear(hero, tier, boss) if hero else {})}

    def _stats(self, enemy: dict, tier: Tier, boss: bool) -> dict:
        power = tier.power
        attack = power * (BOSS_ATTACK * (GATE_BOSS_ATTACK if tier.gate else 1.0) if boss else 1.0)
        bonus = round(MAX_CRIT_BONUS * tier.progress)
        return {
            **enemy,
            "hp": round(enemy["hp"] * power * (BOSS_HP if boss else 1.0)),
            "patk": round(enemy["patk"] * attack),
            "matk": round(enemy.get("matk", 0) * attack),
            "def": round(enemy["def"] * power ** 0.6),
            "speed": round(enemy["speed"] * (1 + 0.08 * (power - 1))),
            "crit": enemy.get("crit", 0) + bonus,
            "dr": enemy.get("dr", 0) + bonus,
        }

    def _pick(self, tier: Tier, boss: bool, rng: random.Random):
        """The hero an enemy slot becomes, or None to stay the mob the APK ships."""
        wants_hero = boss and tier.index >= HEROES_FROM
        if not self.pool or not (wants_hero or rng.random() < tier.hero_share):
            return None
        top = len(self.pool) - 1
        spread = round((BOSS_ERA_SPREAD if boss else ERA_SPREAD) * top)
        centre = round(tier.progress * top)
        if boss:
            centre = min(top, centre + round(ERA_SPREAD * top))
        return self.pool[rng.randint(max(0, centre - spread), min(top, centre + spread))]

    def _wear(self, hero: Hero, tier: Tier, boss: bool) -> dict:
        """The hero's look and skills; the stats stay the slot's own."""
        level = 1 + round(tier.progress * (SKILL_LEVELS - 1)) + (BOSS_SKILL_LEVELS if boss else 0)
        skills = {f"skill{slot}": [self._tier_skill(base, tier.progress), level]
                  for slot, base in enumerate(hero.skills[:3], start=1)}
        return {"animation": hero.animation, "img": hero.img, "enemy_name": hero.name,
                "race": hero.race, "rgb_sort": hero.rgb_sort,
                **{f"skill{slot}": skills.get(f"skill{slot}", []) for slot in (1, 2, 3)}}

    def _tier_skill(self, base: int, progress: float) -> int:
        """The evolution tier of a hero skill an enemy has reached: later cities, higher tier."""
        chain = self.book.chain(base)
        return chain[min(len(chain) - 1, int(progress * len(chain)))]


def _hero_pool(characters: dict, book: SkillBook) -> list:
    """Playable heroes whose animation and skills the engine can run, oldest first."""
    pool = []
    for key, row in characters.items():
        if not (isinstance(row, dict) and key.isdigit() and 100 <= int(key) <= LAST_HERO_ID):
            continue
        skills = tuple(base for _, base in book.hero_skills(row))
        if (row.get("quality") not in HERO_QUALITIES or not row.get("is_evo") or not skills
                or "clone" in str(row.get("name", "")).lower()
                or not book.has_animation(row.get("animation", ""))
                or any(book.skill(base) is None for base in skills)):
            continue
        pool.append(Hero(int(key), row["animation"], row.get("img", ""), row.get("name", ""),
                         row.get("race", -1), row.get("rgb_sort", 0), skills))
    return sorted(pool, key=lambda hero: hero.card_id)


def _campaign_order(configs, elite=False) -> list:
    """(city, player level needed) for the normal campaign (or the elite one), in play order.

    The level comes from the APK's own `map_main_story`: the served copy opens every normal
    city at level 1."""
    chapters = configs.get("chapter")
    normal = {key for key, row in chapters.items()
              if isinstance(row, dict) and row.get("is_hard") == 0}
    levels = {str(row["stage_id"]): row["open_level"]
              for row in configs.raw("map_main_story").values()
              if isinstance(row, dict) and (str(row.get("chapter")) in normal) != elite}
    order = configs.get("cityid_cityorderid")
    return [(city, levels[city])
            for city, _ in sorted(order.items(), key=lambda kv: int(kv[1])) if city in levels]
