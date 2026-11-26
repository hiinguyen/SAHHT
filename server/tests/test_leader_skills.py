"""Leader skills: config, protocol (learn/equip) and the rage cast in a battle."""

import json
import random
import unittest
from pathlib import Path

from sahht_server.battle import simulate
from sahht_server.handlers import ConfigCache
from sahht_server.leader_skill import LeaderBook, validate_all
from tests.test_flow import ServerCase

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT.parent / "decompiled" / "apk" / "assets" / "config"
LUA_DIR = ROOT.parent / "decompiled" / "lua"
SPECS = json.loads((ROOT / "data" / "leader_skill_specs.json").read_text(encoding="utf-8"))


def leader_config():
    """Two scripted skills (tree 1) and one passive node of the same tree."""
    return {
        "101": {"name": "Giật Điện", "script": "leader_lighting_lighting", "tree": 1,
                "cd": 3, "ready_time": 0, "max_level": 5, "is_positive": 1,
                "base_effect1": 45, "add_effect1": 5, "base_effect2": 0,
                "add_effect2": 0, "icon": "s_dianji.png"},
        "201": {"name": "Bình Xăng", "script": "leader_fire_fireball", "tree": 2,
                "cd": 3, "ready_time": 0, "max_level": 5, "is_positive": 1,
                "base_effect1": 70, "add_effect1": 10, "base_effect2": 0,
                "add_effect2": 0, "icon": "s_qiyou.png"},
        "111": {"name": "Điện Cao Áp", "script": "", "tree": 1, "cd": 0,
                "ready_time": 0, "max_level": 5, "is_positive": 0, "pre_skill": [101],
                "base_effect1": 0, "add_effect1": 4, "base_effect2": 0,
                "add_effect2": 0},
    }


def develop_config():
    return {"101": {"name": "Giật Điện", "star_1": 20, "star_2": 30, "star_3": 40,
                    "star_4": 60, "star_5": 100, "step": 1},
            "201": {"name": "Bình Xăng", "star_1": 50, "star_2": 60, "star_3": 70,
                    "star_4": 80, "star_5": 90, "step": 1}}


class SpecTests(unittest.TestCase):
    def test_specs_are_valid(self):
        self.assertEqual(validate_all(SPECS), [])

    @unittest.skipUnless((CONFIG_DIR / "leader_skill.config").is_file(), "needs the configs")
    def test_every_specced_skill_has_a_client_effect_script(self):
        config = json.loads((CONFIG_DIR / "leader_skill.config").read_text(encoding="utf-8"))
        scripts = {f.stem for f in (LUA_DIR / "skill_effect" / "leader_skill").glob("*.lua")}
        for skill_id, spec in SPECS.items():
            with self.subTest(skill=skill_id):
                self.assertIn(config[skill_id]["script"], scripts)

    @unittest.skipUnless((CONFIG_DIR / "leader_skill.config").is_file(), "needs the configs")
    def test_the_book_reads_the_apk_config(self):
        config = json.loads((CONFIG_DIR / "leader_skill.config").read_text(encoding="utf-8"))
        book = LeaderBook(config, SPECS)
        self.assertEqual(len(book.ids()), 12)
        self.assertEqual(book.get(101).script, "leader_lighting_lighting")
        self.assertIsNone(book.get(111))   # passive node, no effect script
        self.assertEqual(book.get(101).at_level(3).effect1, 55)  # 45 + 5 * 2


def unit(pos, hp=100000, patk=100, matk=100, defense=10, speed=100, **kw):
    return {"pos": pos, "hp": hp, "patk": patk, "matk": matk, "def": defense,
            "speed": speed, "crit": 0, "hit": 100, "dodge": 0, "skills": [], **kw}


def run(leaders, seed=1):
    return simulate([unit(i) for i in range(5)],
                    [unit(100 + i) for i in range(3)],
                    rng=random.Random(seed), script=lambda u, s, slot: "skill1",
                    leaders=leaders)


class LeaderBattleTests(unittest.TestCase):
    def setUp(self):
        self.book = LeaderBook(leader_config(), SPECS)

    def rounds(self, frames, flag):
        """The round number each frame with `flag` was emitted in."""
        round_no, found = 0, []
        for frame in frames:
            if frame["flag"] == "sort":
                round_no += 1
            elif frame["flag"] == flag:
                found.append(round_no)
        return found

    def test_rage_fills_and_the_skill_fires_then_resets(self):
        _, frames = run([self.book.get(101).at_level(1)])
        cast = next(f["param"] for f in frames if f["flag"] == "skill_hero")
        # 5 allies acting (+10 each) plus 3 enemies hitting allies (+5 each) fills 100 by round 3.
        self.assertEqual(self.rounds(frames, "skill_hero")[0], 3)
        self.assertEqual((cast["src"], cast["name"], cast["skillid"]),
                         (0, "leader_lighting_lighting", 101))
        # 45% of the highest ally matk (100), on every enemy.
        self.assertEqual(cast["hurt"], [45, 45, 45])
        self.assertEqual(cast["des"], [100, 101, 102])
        anger = [f["param"]["value"] for f in frames if f["flag"] == "anger"]
        self.assertEqual(anger[0], 0)
        self.assertEqual(max(anger), 100)
        self.assertNotIn("pre_battle", [f["flag"] for f in frames])

    def test_cooldown_spaces_the_casts(self):
        _, frames = run([self.book.get(101).at_level(1)])
        self.assertEqual(self.rounds(frames, "skill_hero")[:3], [3, 6, 9])  # cd 3

    def test_level_raises_the_damage(self):
        _, frames = run([self.book.get(101).at_level(5)])   # 45 + 5 * 4 = 65%
        cast = next(f["param"] for f in frames if f["flag"] == "skill_hero")
        self.assertEqual(cast["hurt"], [65, 65, 65])

    def test_no_leaders_means_no_leader_frames(self):
        _, frames = run([])
        self.assertFalse([f for f in frames if f["flag"] in ("skill_hero", "anger")])


class LeaderProtocolTests(ServerCase):
    def extra_configs(self):
        return {"leader_skill": leader_config(), "leader_skill_develop": develop_config()}

    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]
        self.api("cards.open", self.rans, self.uid)

    def call(self, method, form=None, **params):
        _, body = self.api(method, self.rans, self.uid, form, **params)
        return body

    def test_open_answers_every_field_the_scene_reads(self):
        body = self.call("leader_skill.open")
        self.assertEqual(body["status"], 0, body)
        data = body["data"]
        self.assertEqual(data["available_skill"], {"101": 0})   # roots are ready to learn
        self.assertEqual(data["leader_skill"], {"skill_1": 0, "skill_2": 0, "skill_3": 0})
        self.assertEqual(data["skill_point"], {"1": [0, 0], "2": [0, 0],
                                               "3": [0, 0], "4": [0, 0]})
        self.assertEqual(body["user_status"]["star"], 1000)

    def test_training_pays_stars_and_raises_the_level(self):
        body = self.call("leader_skill.train", skill="101")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["user_status"]["star"], 980)
        self.assertEqual(body["data"]["available_skill"], {"101": 1})

    def test_is_max_buys_as_far_as_the_stars_allow(self):
        store = self.server.services.store
        store.change_wallet(self.uid, {"star": 50 - store.wallet(self.uid).get("star", 0)})
        body = self.call("leader_skill.train", skill="101", is_max="1")
        # 20 + 30 = 50, the next level costs 40 and is out of reach.
        self.assertEqual(body["data"]["available_skill"], {"101": 2})
        self.assertEqual(body["user_status"]["star"], 0)
        self.assertEqual(self.call("leader_skill.train", skill="101")["status"],
                         "error_not_enough")

    def test_a_node_waits_for_its_parent_to_reach_the_top_level(self):
        self.assertEqual(self.call("leader_skill.train", skill="111")["status"],
                         "error_not_open")
        self.assertEqual(self.call("leader_skill.train", skill="999999")["status"],
                         "error_not_open")

    def test_a_tree_needs_the_player_level(self):
        self.assertEqual(self.call("leader_skill.train", skill="201")["status"], "error_level")

    def test_equipping_requires_learned_skills(self):
        self.assertEqual(self.call("leader_skill.set_skill", skill_1="101",
                                   skill_2="0", skill_3="0")["status"], "error_param")
        self.call("leader_skill.train", skill="101")
        body = self.call("leader_skill.set_skill", skill_1="101", skill_2="0", skill_3="0")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["leader_skill"],
                         {"skill_1": 101, "skill_2": 0, "skill_3": 0})

    def test_the_same_skill_cannot_fill_two_slots(self):
        self.call("leader_skill.train", skill="101")
        self.assertEqual(self.call("leader_skill.set_skill", skill_1="101",
                                   skill_2="101", skill_3="0")["status"], "error_param")

    def test_the_choice_and_levels_survive_a_reopen(self):
        self.call("leader_skill.train", skill="101")
        self.call("leader_skill.set_skill", skill_1="101", skill_2="0", skill_3="0")
        store = self.server.services.store
        levels, slots = store.leader_skills(self.uid)
        self.assertEqual((levels, slots), ({101: 1}, [101, 0, 0]))

    def test_a_battle_carries_the_equipped_skill_and_a_role(self):
        self.call("leader_skill.train", skill="101")
        self.call("leader_skill.set_skill", skill_1="101", skill_2="0", skill_3="0")
        body = self.call("private_city.recapture", city="100", building="100001",
                         step_n="0")
        init = body["data"]["battle"]["init"]
        self.assertEqual(init["atk_skill"], [101, 0, 0])
        self.assertEqual(init["dfd_skill"], [0, 0, 0])
        self.assertEqual((init["atk_role"], init["dfd_role"]), (1, 0))
        self.assertTrue(any(frame["flag"] == "anger"
                            for frame in body["data"]["battle"]["battle"].values()))


if __name__ == "__main__":
    unittest.main()
