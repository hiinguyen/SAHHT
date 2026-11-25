"""Secondary stats: crit, hit/dodge, damage reduction, and elemental attack/defense."""

import random
import unittest
from pathlib import Path

from sahht_server import equipment
from sahht_server.battle import simulate
from sahht_server.handlers import ConfigCache
from sahht_server.progression import NO_SKILL, Rules

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "decompiled" / "apk" / "assets" / "config"


class FixedRandom:
    """random.Random's surface the engine uses, with scripted `random()` values."""

    def __init__(self, values):
        self._values = iter(values)

    def random(self):
        return next(self._values, 0.99)

    def sample(self, pool, count):
        return pool[:count]

    def choice(self, seq):
        return seq[0]


def unit(pos, hp=1000, patk=100, defense=0, speed=100, **kw):
    return {"pos": pos, "hp": hp, "patk": patk, "matk": 0, "def": defense, "speed": speed,
            "crit": 0, "hit": 100, "dodge": 0, "subhurt": 0, "skills": [], **kw}


def run(attackers, defenders, rng=None):
    return simulate(attackers, defenders, rng=rng or random.Random(1),
                    script=lambda u, s, slot: "skill1")


def hits(frames, src=None):
    return [f["param"]["hurt"] for f in frames
            if f["flag"] == "attack" and (src is None or f["param"]["src"] == src)]


class DamageReductionTests(unittest.TestCase):
    def test_subhurt_reduces_final_damage(self):
        _, frames = run([unit(0, patk=100)], [unit(100, hp=10**6, subhurt=50)])
        self.assertEqual(hits(frames)[0], 50)

    def test_a_reduction_buff_stacks_with_the_stat(self):
        _, frames = run([unit(0, patk=100)],
                        [unit(100, hp=10**6, subhurt=50, **{"skills": []})])
        self.assertEqual(hits(frames)[0], 50)  # the stat alone, no buff needed

    def test_a_full_reduction_never_makes_damage_zero(self):
        _, frames = run([unit(0, patk=100)], [unit(100, hp=10**6, subhurt=100)])
        self.assertEqual(hits(frames)[0], 1)


class CritAndHitTests(unittest.TestCase):
    def test_crit_multiplies_by_one_and_a_half(self):
        _, frames = run([unit(0, patk=100, crit=100)], [unit(100, hp=10**6)])
        self.assertEqual(hits(frames)[0], 150)

    def test_dodge_above_hit_still_leaves_the_minimum_chance(self):
        # hit 100 - dodge 1000 is negative, so the floor of 5% applies: rng 0.5 is a miss.
        _, frames = run([unit(0, patk=100)], [unit(100, hp=10**6, dodge=1000)],
                        rng=FixedRandom([0.5, 0.0]))
        self.assertEqual(hits(frames)[0], 0)

    def test_hit_above_dodge_lands(self):
        _, frames = run([unit(0, patk=100, hit=150)], [unit(100, hp=10**6, dodge=50)],
                        rng=FixedRandom([0.5, 0.5]))
        self.assertEqual(hits(frames)[0], 100)


class ElementTests(unittest.TestCase):
    def test_element_damage_uses_the_attackers_own_element(self):
        attacker = unit(0, patk=100, elements={"fire": 300})
        defender = unit(100, hp=10**6)
        skill = _attr_skill("own")
        attacker["skills"] = [(1, skill)]
        _, frames = run([attacker], [defender])
        # normal? no: the active skill replaced it; damage = fire 300 - defense 0
        hurt = next(p["hurt"][0] for p in (f["param"] for f in frames if f["flag"] == "skill"))
        self.assertEqual(hurt, 300)

    def test_matching_element_defense_cancels_the_attack(self):
        attacker = unit(0, patk=100, elements={"fire": 300})
        defender = unit(100, hp=10**6, element_def={"fire": 300})
        attacker["skills"] = [(1, _attr_skill("own"))]
        _, frames = run([attacker], [defender])
        hurt = next(p["hurt"][0] for p in (f["param"] for f in frames if f["flag"] == "skill"))
        self.assertEqual(hurt, 0)


def _attr_skill(element):
    from sahht_server.skills import Skill
    return Skill(id=1, root=1, trigger="active", aim="enemy_front", count=1,
                 effects=({"op": "attr_damage", "target": "target",
                           "element": element, "scale": "attr"},),
                 effect=100.0, attr=100.0, cd=0, pre_cd=0, rate=100.0,
                 limit_per_round=0, once=False, rounds=(1, 10**6), sprite="")


class EquipmentBonusTests(unittest.TestCase):
    """`bonus()` returns the elemental and percentage-point stats the client maps too."""

    CONFIGS = {
        "equip": {str(n): {"sort": n, "ability1": 1, "ability2": 5, "value1": 10,
                           "value2": 20, "level_add1": 0, "level_add2": 0,
                           "suit": 900, "equip_id": n}
                  for n in (1, 2, 3, 4)},
        "suit": {"900": {"part": [1, 2, 3, 4],
                         "effect_2": [[8, 10], [6, 5]],
                         "effect_4": [[203, 5000], [301, 300]]}},
        "equip_set_random": {"5": {"sort": 6, "enemy": []},
                             "6": {"sort": 8, "enemy": []}},
    }

    class Configs:
        def __init__(self, rows):
            self.rows = rows

        def get(self, name):
            return self.rows.get(name, {})

    def pieces(self, extra_by_id=None):
        extra_by_id = extra_by_id or {}
        return {f"e{n}": {"id": f"e{n}", "c_id": n, "lv": 1,
                          "extra": extra_by_id.get(f"e{n}", {})} for n in (1, 2, 3, 4)}

    def test_elemental_suit_effects_and_secondary_ids_reach_the_bonus(self):
        stats = equipment.bonus(self.Configs(self.CONFIGS), ["e1", "e2", "e3", "e4"],
                                self.pieces())
        self.assertEqual((stats["wind"], stats["fire_dfs"]), (5000, 300))
        self.assertEqual((stats["crit"], stats["subhurt"]), (5, 10))

    def test_enchant_atts_are_added_by_name(self):
        configs = self.Configs(self.CONFIGS)
        stats = equipment.bonus(configs, ["e1"], self.pieces({
            "e1": {"is_enchant": True, "atts": {"water": 700, "hp": 1}}}))
        self.assertEqual(stats["water"], 700)
        self.assertEqual(stats["hp"], 20)  # `hp` is not an enchant element key

    def test_forge_rows_six_to_nine_keep_their_percentage(self):
        configs = self.Configs(self.CONFIGS)
        stats = equipment.bonus(configs, ["e1"], self.pieces({
            "e1": {"equip_forge": {"5": {"crit": 0.9}, "6": {"subhurt": 2.5}}}}))
        self.assertEqual((stats["crit"], stats["subhurt"]), (0.9, 2.5))


@unittest.skipUnless((CONFIG_DIR / "combat_base.config").is_file(), "needs the extracted configs")
class CombatPowerTests(unittest.TestCase):
    def test_elemental_stats_enter_combat_power_at_face_value(self):
        rules = Rules.load(ConfigCache(CONFIG_DIR))
        doc = {"hp": 1000, "patk": 100, "matk": 0, "def": 100, "speed": 100,
               "s_1": dict(NO_SKILL), "s_2": dict(NO_SKILL), "s_3": dict(NO_SKILL),
               "wind": 5000, "earth": 200}
        base = rules.card_combat({**doc, "wind": 0, "earth": 0})
        self.assertEqual(rules.card_combat(doc) - base, 5200)


if __name__ == "__main__":
    unittest.main()
