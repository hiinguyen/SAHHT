"""Passive leader-skill nodes: specs, values, their effect in a battle, and learning them."""

import json
import random
import unittest
from pathlib import Path
from types import SimpleNamespace

from sahht_server import campaign, leader_passives
from sahht_server.battle import Battle, build_unit, simulate
from sahht_server.leader_passives import LeaderMods, make_passive
from sahht_server.leader_skill import LeaderBook
from tests.test_flow import ServerCase
from tests.test_leader_skills import develop_config, leader_config, unit

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT.parent / "decompiled" / "apk" / "assets" / "config" / "leader_skill.config"
SPECS = json.loads((ROOT / "data" / "leader_skill_specs.json").read_text(encoding="utf-8"))
PASSIVES = leader_passives.load_specs()
needs_config = unittest.skipUnless(CONFIG.is_file(), "needs the configs")


class AlwaysRoll(random.Random):
    """Every chance roll succeeds (a roll is `random() * 100 < chance`)."""

    def random(self):
        return 0.0


def apk():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


class SpecTests(unittest.TestCase):
    def test_specs_are_valid(self):
        self.assertEqual(leader_passives.validate_all(PASSIVES), [])

    @needs_config
    def test_every_passive_node_of_the_four_trees_has_a_spec(self):
        passive_nodes = {k for k, v in apk().items()
                         if not v["script"] and 1 <= v["tree"] <= 4}
        self.assertEqual(set(PASSIVES), passive_nodes)

    @needs_config
    def test_specs_only_name_castable_skills_of_their_own_tree(self):
        config = apk()
        for skill_id, spec in PASSIVES.items():
            for effect in spec["effects"]:
                if isinstance(effect.get("skills"), list):
                    for target in effect["skills"]:
                        with self.subTest(passive=skill_id, skill=target):
                            self.assertIn(str(target), SPECS)
                            self.assertEqual(config[str(target)]["tree"],
                                             config[skill_id]["tree"])

    def test_a_bad_spec_is_reported(self):
        bad = {"1": {"effects": [{"kind": "nope"}]},
               "2": {"effects": [{"kind": "damage_up", "skills": "tree", "vs": "x"}]},
               "3": {"effects": [{"kind": "rage_start", "skills": [1]}]}}
        self.assertEqual(len(leader_passives.validate_all(bad)), 3)


@needs_config
class ValueTests(unittest.TestCase):
    def value(self, skill_id, level, index=0):
        row = apk()[str(skill_id)]
        return make_passive(skill_id, row["tree"], row, PASSIVES[str(skill_id)], level) \
            .effects[index].value

    def test_values_follow_the_config_per_level(self):
        self.assertEqual(self.value(111, 3), 12)       # 4% a level
        self.assertEqual(self.value(421, 5), 25)       # 5 rage a level

    def test_story_overrides_where_the_config_disagrees(self):
        self.assertEqual(self.value(192, 5), 30)       # config adds 10, story says 6%
        self.assertEqual(self.value(191, 1, index=1), 20)   # a fixed 20% extra hit

    def test_a_reduction_recovers_as_the_level_rises(self):
        self.assertEqual([self.value(331, level) for level in (1, 5)], [40, 12])


class ModsTests(unittest.TestCase):
    def test_vs_bonus_counts_only_while_the_status_holds(self):
        skill = SimpleNamespace(id=101, tree=1)
        passive = leader_passives.Passive(123, (leader_passives.PassiveEffect(
            "damage_up", 1, "tree", 10.0, {"vs": "stunned"}),))
        mods = LeaderMods([passive])
        stunned = SimpleNamespace(controls={"stun": 1}, buffs=[])
        free = SimpleNamespace(controls={}, buffs=[])
        self.assertEqual((mods.damage_pct(skill, stunned), mods.damage_pct(skill, free)), (10, 0))
        self.assertEqual(mods.damage_pct(SimpleNamespace(id=201, tree=2), stunned), 0)


@needs_config
class BattleTests(unittest.TestCase):
    def setUp(self):
        self.config = apk()
        self.book = LeaderBook(self.config, SPECS, PASSIVES)

    def mods(self, *learned):
        return LeaderMods(self.book.passive_at(skill_id, level) for skill_id, level in learned)

    def run_battle(self, skill_id, level, mods, rng=None, enemies=3):
        skill = self.book.get(skill_id).at_level(level)
        return simulate([unit(i) for i in range(5)], [unit(100 + i) for i in range(enemies)],
                        rng=rng or random.Random(1), leaders=[skill], mods=mods,
                        script=lambda u, s, slot: "skill1")[1]

    def first_cast(self, frames):
        return next(f["param"] for f in frames if f["flag"] == "skill_hero")

    def rounds(self, frames):
        round_no, found = 0, []
        for frame in frames:
            round_no += frame["flag"] == "sort"
            if frame["flag"] == "skill_hero":
                found.append(round_no)
        return found

    def test_damage_up_raises_the_hit(self):
        frames = self.run_battle(101, 1, self.mods((111, 5)))
        self.assertEqual(self.first_cast(frames)["hurt"], [54, 54, 54])   # 45% x 1.20

    def test_no_passives_leave_the_hit_alone(self):
        frames = self.run_battle(101, 1, self.mods())
        self.assertEqual(self.first_cast(frames)["hurt"], [45, 45, 45])

    def test_cheaper_casts_and_a_rage_head_start_cast_sooner(self):
        base = self.run_battle(101, 1, self.mods())
        quick = self.run_battle(101, 1, self.mods((121, 5), (421, 5)))   # cost 75, start 25
        self.assertEqual((self.rounds(base)[0], self.rounds(quick)[0]), (3, 2))

    def test_extra_targets_share_a_smaller_hit(self):
        frames = self.run_battle(301, 1, self.mods((331, 1)))
        cast = self.first_cast(frames)
        self.assertEqual(len(cast["des"]), 2)
        self.assertEqual(cast["hurt"], [39, 39])      # 65% cut by 40% to each of two targets

    def test_a_third_target_needs_the_upgrade(self):
        cast = self.first_cast(self.run_battle(301, 1, self.mods((331, 1), (333, 1))))
        self.assertEqual(len(cast["des"]), 3)
        self.assertEqual(cast["hurt"], [46, 46, 46])  # 65% cut by 30%

    def test_the_chain_loses_damage_on_each_target_until_a_passive_stops_it(self):
        chain = self.first_cast(self.run_battle(132, 1, self.mods()))["hurt"]
        self.assertEqual(chain, [70, 52, 39])         # 70% of 100, 25% less each hop
        steady = self.first_cast(self.run_battle(132, 1, self.mods((133, 5))))["hurt"]
        self.assertEqual(steady, [70, 70, 70])

    def test_a_stun_passive_leaves_the_target_stunned(self):
        frames = self.run_battle(101, 1, self.mods((122, 1)), rng=AlwaysRoll(1))
        self.assertIn("buff_giddy", [f["param"]["name"] for f in frames if f["flag"] == "add_buff"])

    def test_a_burn_passive_ticks_damage_on_later_rounds(self):
        plain = self.run_battle(201, 1, self.mods(), rng=AlwaysRoll(1))
        burning = self.run_battle(201, 1, self.mods((222, 5)), rng=AlwaysRoll(1))
        ticks = lambda frames: [f for f in frames if f["flag"] == "buff_skill"
                                and f["param"]["name"] == "buff_fire_skill"]
        self.assertEqual((len(ticks(plain)), bool(ticks(burning))), (0, True))

    def test_slowing_an_enemy_cuts_its_speed(self):
        skill = self.book.get(301).at_level(1)
        units = [build_unit(unit(i)) for i in range(5)] + [build_unit(unit(100))]
        battle = Battle(units, rng=AlwaysRoll(1), leaders=[skill], mods=self.mods((322, 1)))
        battle.rage = 100
        battle.round = 3
        battle._leader_cast()
        self.assertEqual(units[5].stat("speed"), 80)    # 100 less 20%

    def test_a_cast_keeps_the_rage_a_passive_holds_back(self):
        skill = self.book.get(101).at_level(1)
        battle = Battle([build_unit(unit(0)), build_unit(unit(100))], leaders=[skill],
                        mods=self.mods((423, 2)))
        battle.rage = 100
        battle._spend_rage(skill)
        self.assertEqual(battle.rage, 6)

    def test_ally_buff_blesses_the_side(self):
        skill = self.book.get(232).at_level(1)
        units = [build_unit(unit(0)), build_unit(unit(100))]
        battle = Battle(units, rng=AlwaysRoll(1), leaders=[skill], mods=self.mods((292, 1)))
        battle.rage = 100
        battle.round = 3
        battle._leader_cast()
        self.assertAlmostEqual(units[0].stat("patk"), 110)
        self.assertAlmostEqual(units[0].stat("matk"), 110)


class LearningTests(ServerCase):
    def extra_configs(self):
        develop = develop_config()
        develop["111"] = {"name": "Điện Cao Áp", "star_1": 10, "star_2": 10, "star_3": 10,
                          "star_4": 10, "star_5": 10, "step": 2}
        return {"leader_skill": leader_config(), "leader_skill_develop": develop}

    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]
        self.api("cards.open", self.rans, self.uid)

    def call(self, method, **params):
        _, body = self.api(method, self.rans, self.uid, None, **params)
        return body

    def max_out_the_root(self):
        self.call("leader_skill.train", skill="101", is_max="1")

    def test_a_child_opens_when_its_parent_reaches_the_top_level(self):
        self.assertNotIn("111", self.call("leader_skill.open")["data"]["available_skill"])
        self.max_out_the_root()
        self.assertEqual(self.call("leader_skill.open")["data"]["available_skill"],
                         {"101": 5, "111": 0})

    def test_a_passive_node_can_be_learned_but_not_equipped(self):
        self.max_out_the_root()
        body = self.call("leader_skill.train", skill="111")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["available_skill"]["111"], 1)
        equip = self.call("leader_skill.set_skill", skill_1="111", skill_2="0", skill_3="0")
        self.assertEqual(equip["status"], "error_param")

    def test_learned_passives_reach_the_battle(self):
        self.max_out_the_root()
        self.call("leader_skill.train", skill="111", is_max="1")
        mods = campaign._leader_mods(self.server.services, self.uid)
        skill = SimpleNamespace(id=101, tree=1)
        self.assertEqual(mods.total("damage_up", skill), 20)   # 4% x level 5


if __name__ == "__main__":
    unittest.main()
