"""Campaign difficulty: tiers, milestone gates, newer heroes as enemies (APK configs)."""

import statistics
import unittest

from sahht_server import campaign, difficulty
from sahht_server.skills import SkillBook
from tools import simulate_campaign
from tools.audit_enemy_skills import CONFIG_DIR, campaign_fights, services


class DifficultyCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = services(CONFIG_DIR)
        cls.diff = difficulty.Difficulty.load(cls.svc.configs)
        cls.order = difficulty._campaign_order(cls.svc.configs)

    def enemies(self, city):
        ids = {}
        for c, _, _, fight_id in campaign_fights(self.svc):
            if c == city:
                fight = self.svc.configs.get("map_fight")[str(fight_id)]
                ids.update({str(e): None for _, e in campaign._enemy_ids(fight)})
        return [campaign._enemy(self.svc, city, e) for e in ids]


class TierTests(DifficultyCase):
    def test_milestones_are_the_first_cities_needing_each_tenth_level(self):
        gates = difficulty.gate_cities(self.order)
        levels = dict(self.order)
        self.assertEqual(sorted(levels[c] for c in gates)[:6], [20, 30, 40, 50, 60, 70])
        for city in ("151", "161", "171"):   # the 50, 60 and 70 gates
            self.assertIn(city, gates)

    def test_tutorial_cities_are_untouched(self):
        for city, _ in self.order[:difficulty.UNTOUCHED]:
            raw = [self.svc.configs.raw(t) for t in (f"enemy_soldier_{city}", "enemy_detail")]
            for enemy in self.enemies(city):
                self.assertIn(enemy, [row for table in raw for row in table.values()])

    def test_power_grows_and_each_gate_is_a_step_up(self):
        tiers = self.diff.tiers
        plain = [tiers[c].power for c, _ in self.order[difficulty.UNTOUCHED:]
                 if not tiers[c].gate]
        self.assertEqual(plain, sorted(plain))
        for gate in difficulty.gate_cities(self.order):
            index = [c for c, _ in self.order].index(gate)
            before, after = (self.order[index - 1][0], self.order[index + 1][0])
            self.assertGreater(tiers[gate].power, tiers[before].power)
            self.assertGreater(tiers[gate].power, tiers[after].power)

    def test_late_enemies_are_far_stronger_than_the_apk_ships(self):
        raw = self.svc.configs.raw("enemy_soldier_150")
        hardened = {e["hp"] for e in self.enemies("150")}
        self.assertGreater(statistics.median(hardened), 3 * statistics.median(e["hp"] for e in raw.values()))


class HeroEnemyTests(DifficultyCase):
    def era(self, city):
        by_name = {h.name: h.card_id for h in self.diff.pool}
        return statistics.mean(by_name[e["enemy_name"]] for e in self.enemies(city)
                               if e["enemy_name"] in by_name)

    def test_later_cities_field_newer_heroes(self):
        self.assertLess(self.era("115"), self.era("150"))
        self.assertLess(self.era("150"), self.era("210"))

    def test_late_cities_have_no_mobs_left_but_a_few(self):
        names = {h.name for h in self.diff.pool}
        for city in ("200", "210", "219"):
            enemies = self.enemies(city)
            heroes = sum(1 for e in enemies if e["enemy_name"] in names)
            self.assertGreater(heroes / len(enemies), 0.9)

    def test_bosses_are_heroes_with_skills_the_engine_runs(self):
        book = SkillBook.load(self.svc.configs)
        bosses = [e for e in self.enemies("171") if e.get("is_boss") == 1]
        self.assertTrue(bosses)
        for boss in bosses:
            self.assertTrue(book.has_animation(boss["animation"]))
            skills = [boss[f"skill{s}"] for s in (1, 2, 3) if boss[f"skill{s}"]]
            self.assertTrue(skills)
            for skill_id, level in skills:
                self.assertIsNotNone(book.skill(skill_id, level))

    def test_the_same_enemy_is_always_the_same_hero(self):
        first = campaign._enemy(self.svc, "171", 171001)
        self.assertEqual(first, campaign._enemy(self.svc, "171", 171001))

    def test_every_hero_in_the_pool_is_a_2018_hero_the_client_can_draw(self):
        self.assertGreater(len(self.diff.pool), 100)
        self.assertLessEqual(max(h.card_id for h in self.diff.pool), 38700)
        self.assertTrue(all(self.diff.book.has_animation(h.animation) for h in self.diff.pool))


class FightTests(DifficultyCase):
    def test_gate_cities_run_in_the_engine_and_beat_a_weak_team_more_often(self):
        rows = simulate_campaign.run(CONFIG_DIR, cities={"151", "161", "171"})
        self.assertGreater(len(rows), 200)
        self.assertTrue(all(r["frames"] > 0 for r in rows))
        wins = sum(r["won"] for r in rows)
        self.assertLess(wins, len(rows) * 0.5)


if __name__ == "__main__":
    unittest.main()
