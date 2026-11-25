"""Enemy skills: the specs the campaign's enemies run, against the real client configs."""

import random
import unittest
from pathlib import Path

from sahht_server import campaign
from sahht_server.battle import simulate
from sahht_server.handlers import ConfigCache
from sahht_server.skill_spec import validate_all
from sahht_server.skills import ENEMY_SPECS_PATH, SPECS_PATH, SkillBook, _load_json
from tools.audit_enemy_skills import enemy_skills, services

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "decompiled" / "apk" / "assets" / "config"


@unittest.skipUnless((CONFIG_DIR / "skill_detail.config").is_file(), "needs the extracted APK configs")
class EnemySkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configs = ConfigCache(CONFIG_DIR)
        cls.book = SkillBook.load(cls.configs)
        cls.svc = services(CONFIG_DIR)
        cls.used = enemy_skills(cls.svc)

    def test_spec_file_is_valid(self):
        self.assertEqual(validate_all(_load_json(ENEMY_SPECS_PATH)), [])

    def test_the_two_spec_files_do_not_share_keys(self):
        self.assertEqual(set(_load_json(SPECS_PATH)) & set(_load_json(ENEMY_SPECS_PATH)), set())

    def test_every_campaign_enemy_skill_has_a_spec(self):
        missing = sorted(i for i in self.used if self.book.root(i) is None)
        self.assertEqual(missing, [])

    def test_skill_book_reads_the_enemy_file_and_rejects_unknown_ids(self):
        self.assertIsNotNone(self.book.skill(90007, 1))
        self.assertIsNone(self.book.skill(999999, 1))

    def test_duplicate_keys_between_the_files_raise(self):
        with self.assertRaises(ValueError):
            SkillBook({"1": {}}, {"1": {}}, {}, {"1": {}})

    def test_every_enemy_skill_runs_in_the_engine(self):
        for skill_id in sorted(self.used):
            with self.subTest(skill=skill_id):
                skill = self.book.skill(skill_id, 1)
                self.assertIsNotNone(skill)
                attacker = self._unit(0, skills=[(1, skill)], hp=200)
                defender = self._unit(100, hp=100000)
                winer, frames = simulate(
                    [attacker], [defender], rng=random.Random(skill_id),
                    script=lambda u, s, slot: "skill1")
                self.assertEqual(frames[-1], {"flag": "winer", "param": winer})
                for frame in frames:
                    if frame["flag"] == "cur_data":
                        for hp in frame["param"].values():
                            self.assertTrue(0 <= hp["tempHp"] <= hp["maxHp"])

    def test_attack_skill_deals_physical_and_element_damage(self):
        # 90007: 150% physical plus 100% of the caster's own element.
        attacker = self._unit(0, skills=[(1, self.book.skill(90007, 1))], hp=100,
                              elements={"wind": 500})
        defender = self._unit(100, hp=100000)
        _, frames = simulate([attacker], [defender], rng=random.Random(1),
                             script=lambda u, s, slot: "skill1")
        hurt = next(p["hurt"][0] for p in (f["param"] for f in frames if f["flag"] == "skill"))
        # physical 150 (150% of patk 100, no defense) + wind 500 (100 * 500 / 100)
        self.assertEqual(hurt, 650)

    def test_element_damage_subtracts_the_same_element_defense(self):
        # 90007's element is the caster's own (wind); the defender's wind defense applies.
        attacker = self._unit(0, skills=[(1, self.book.skill(90007, 1))], hp=100,
                              elements={"wind": 500})
        defender = self._unit(100, hp=100000, element_def={"wind": 200})
        _, frames = simulate([attacker], [defender], rng=random.Random(1),
                             script=lambda u, s, slot: "skill1")
        hurt = next(p["hurt"][0] for p in (f["param"] for f in frames if f["flag"] == "skill"))
        self.assertEqual(hurt, 450)

    def test_on_attack_debuff_weakens_the_enemy(self):
        # 90046: a normal attack lowers the victim's physical attack by 10% for 3 rounds.
        attacker = self._unit(0, skills=[(1, self.book.skill(90046, 1))], hp=10000,
                              patk=10, hit=1000)
        defender = self._unit(100, hp=1000, patk=300, hit=1000, speed=200)
        _, frames = simulate([attacker], [defender], rng=random.Random(2),
                             script=lambda u, s, slot: "skill1")
        hits = [p["hurt"] for p in (f["param"] for f in frames if f["flag"] == "attack")
                if p["src"] == 100]
        self.assertLess(hits[-1], hits[0])

    def test_campaign_defenders_carry_their_configured_skills(self):
        fight = self.svc.configs.get("map_fight")
        city = next(c for c in campaign._city_buildings(self.svc) if c == "100")
        fight_id = next(iter(
            self.svc.configs.get("map_title_detail")[f"{city}001"]["fight_list"]))[1]
        defenders = campaign._defenders(self.svc, city, fight[str(fight_id)])
        self.assertTrue(defenders)
        self.assertTrue(any(unit["skills"] for unit in defenders))
        for unit in defenders:
            enemy = campaign._enemy(self.svc, city, unit["card_id"])
            expected = [int(s[0]) for s in (enemy.get(f"skill{i}") for i in (1, 2, 3))
                        if s]
            self.assertEqual([skill.id for _, skill in unit["skills"]], expected)

    @staticmethod
    def _unit(pos, skills=(), hp=1000, patk=100, matk=0, defense=0, speed=100,
              crit=0, hit=100, dodge=0, elements=None, element_def=None):
        return {"pos": pos, "hp": hp, "patk": patk, "matk": matk, "def": defense,
                "speed": speed, "crit": crit, "hit": hit, "dodge": dodge,
                "elements": elements or {}, "element_def": element_def or {},
                "race": -1, "skills": list(skills)}


if __name__ == "__main__":
    unittest.main()
