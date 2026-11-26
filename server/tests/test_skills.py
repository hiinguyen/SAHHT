"""Hero skill specs against the real client configs: coverage and a battle run per hero."""

import random
import unittest
from pathlib import Path

from sahht_server.battle import simulate
from sahht_server.handlers import ConfigCache
from sahht_server.skill_spec import validate_all
from sahht_server.skills import ANIMS_PATH, LAST_HERO_ID, SPECS_PATH, SkillBook, _load_json

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "decompiled" / "apk" / "assets" / "config"


@unittest.skipUnless((CONFIG_DIR / "skill_detail.config").is_file(), "needs the extracted APK configs")
class HeroSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configs = ConfigCache(CONFIG_DIR)
        cls.book = SkillBook.load(cls.configs)
        characters = cls.configs.get("character_detail")
        cls.heroes = {int(k): v for k, v in characters.items()
                      if k.isdigit() and int(k) <= LAST_HERO_ID}

    def test_spec_file_is_valid(self):
        self.assertEqual(validate_all(_load_json(SPECS_PATH)), [])

    def test_every_skill_tier_of_every_hero_up_to_38700_is_runnable(self):
        missing = []
        for hero_id, hero in self.heroes.items():
            for slot, base in self.book.hero_skills(hero):
                for tier in self.book.chain(base):
                    if self.book.skill(tier, 1) is None:
                        missing.append((hero_id, slot, tier))
        self.assertEqual(missing, [])
        self.assertEqual(len(self.heroes), 367)

    def test_every_hero_skill_has_a_client_script(self):
        anims = _load_json(ANIMS_PATH)
        wrong = []
        for hero_id, hero in self.heroes.items():
            animation = hero["animation"]
            if animation not in anims:
                continue  # six heroes have no art in the client at all
            for slot, base in self.book.hero_skills(hero):
                script = self.book.script(animation, self.book.skill(base), slot)
                if script not in anims[animation]:
                    wrong.append((hero_id, base, script))
        self.assertEqual(wrong, [])

    def test_every_hero_fights_with_its_whole_kit(self):
        for hero_id, hero in self.heroes.items():
            with self.subTest(hero=hero_id):
                self._fight(hero)

    def _fight(self, hero):
        skills = [(slot, self.book.skill(base)) for slot, base in self.book.hero_skills(hero)]
        attackers = [self._unit(pos, hero, skills) for pos in range(3)]
        defenders = [self._unit(100 + pos, hero, skills) for pos in range(3)]
        for seed in range(3):
            winer, frames = simulate(attackers, defenders, rng=random.Random(seed),
                                     script=lambda u, s, slot: "skill1")
            self.assertEqual(frames[-1], {"flag": "winer", "param": winer})
            for frame in frames:
                self._check_frame(frame)

    @staticmethod
    def _unit(pos, hero, skills):
        lv = 30
        stats = {s: hero[f"base_{s}"] + hero[f"growth_{s}"] * (lv - 1)
                 for s in ("hp", "patk", "matk", "def", "speed")}
        return {"pos": pos, **stats, "crit": 10, "hit": 100, "animation": hero["animation"],
                "race": hero.get("race", -1), "skills": skills}

    def _check_frame(self, frame):
        param = frame["param"]
        if frame["flag"] == "skill":
            self.assertEqual(len(param.get("des", ())), len(param.get("hurt", ())))
            # A buff-only cast has desh but an empty health: the client draws MISS for a 0.
            if param.get("health"):
                self.assertEqual(len(param["desh"]), len(param["health"]))
                self.assertTrue(all(h > 0 for h in param["health"]))
            elif "desh" in param:
                self.assertEqual(param["health"], [])
            self.assertTrue(param.get("des") or param.get("desh"))
            self.assertTrue(all(h >= 0 for h in param.get("hurt", []) + param.get("health", [])))
        if frame["flag"] == "cur_data":
            for hp in param.values():
                self.assertTrue(0 <= hp["tempHp"] <= hp["maxHp"])


if __name__ == "__main__":
    unittest.main()
