"""Elite stages: attempts, daily allowance, rewards, and the elite tier of the difficulty."""

import unittest

from sahht_server import config_overrides, difficulty
from tests.test_campaign import CampaignCase
from tests.test_flow import FIXTURE_CONFIGS, _building, _enemy, _fight
from tools.audit_enemy_skills import CONFIG_DIR, services

CITY = "301"


class EliteCase(CampaignCase):
    def extra_configs(self):
        return {
            "chapter": {"1": {"is_hard": 0, "open_level": 1}, "201": {"is_hard": 2, "open_level": 1}},
            "map_main_story": {
                "1": {"stage_id": "100", "open_level": 1, "chapter": 1},
                "2001": {"stage_id": CITY, "open_level": 1, "chapter": 201,
                         "jingyingfirst": [[9, 0, 500]], "jingyingsweep": [[9, 0, 50]]}},
            "cityid_cityorderid": {"100": "1", CITY: "2001"},
            "map_title_detail": {**FIXTURE_CONFIGS["map_title_detail"],
                                 "301001": {**_building([301001], ap=0), "reward_first_base": [[9, 0, 7]]},
                                 "301002": _building([301002], ap=0)},
            "map_fight": {**FIXTURE_CONFIGS["map_fight"], "301001": _fight(301100),
                          "301002": _fight(301100)},
            "enemy_soldier_301": {"301100": _enemy(40, patk=5)},
            "pay": {"16": {"coin": [100, 300]}},
        }

    def fight(self, building, step=0, city=CITY):
        return self.call("hard_recapture", city=city, building=str(building), step_n=str(step),
                         chapter="201")

    def open_city(self, chapter="201"):
        return self.call("hard_open", city=CITY, chapter=chapter)

    def world(self):
        return self.call("world_map")["data"]

    def attack_cells(self, data, state):
        return [cell[1] for row in data["land"] for cell in row
                if cell[0] == state and cell[1] and cell[1] != 100000]


class AttemptTests(EliteCase):
    def test_the_world_map_reports_an_idle_elite_tab(self):
        data = self.world()
        self.assertEqual(data["hard_last_attack"], {"chapter": 1})
        self.assertEqual((data["hard_done_times"], data["hard_max_times"]), (0, 3))
        self.assertEqual(data["all_city_regain_percent"][CITY], 0)

    def test_opening_a_city_starts_one_attempt_with_the_first_building_attackable(self):
        body = self.open_city()
        self.assertEqual(body["status"], 0)
        self.assertEqual(self.attack_cells(body["data"], 2), [301001])
        world = self.world()
        self.assertEqual((world["hard_last_attack"], world["hard_done_times"]),
                         ({"chapter": 201}, 1))
        self.open_city()           # resuming is free
        self.assertEqual(self.world()["hard_done_times"], 1)

    def test_a_building_cannot_be_fought_without_an_attempt_or_out_of_order(self):
        self.assertEqual(self.fight(301001)["status"], "error_building_locked")
        self.open_city()
        self.assertEqual(self.fight(301002)["status"], "error_building_locked")

    def test_completing_the_city_pays_and_ends_the_attempt(self):
        self.open_city()
        first = self.fight(301001)
        self.assertEqual((first["status"], first["data"]["curt_regain"], first["data"]["reward"]),
                         (0, 50, {"coin": 7}))
        coin = first["user_status"]["coin"]
        last = self.fight(301002)
        self.assertEqual((last["data"]["curt_regain"], last["data"]["next_step"]), (100, -1))
        self.assertEqual(last["data"]["reward"], {"coin": 500})
        self.assertEqual(last["user_status"]["coin"], coin + 500)
        world = self.world()
        self.assertEqual(world["hard_last_attack"], {"chapter": 1})
        self.assertEqual(world["all_city_regain_percent"][CITY], 100)
        shown = self.call("open", city=CITY, chapter="201")["data"]
        self.assertEqual((shown["curt_regain"], self.attack_cells(shown, 2)), (100, []))

    def test_a_repeat_pays_the_sweep_reward_and_starts_from_nothing(self):
        self.open_city()
        self.fight(301001)
        self.fight(301002)
        again = self.open_city()["data"]
        self.assertEqual((again["curt_regain"], self.attack_cells(again, 2)), (0, [301001]))
        self.fight(301001)
        self.assertEqual(self.fight(301002)["data"]["reward"], {"coin": 50})

    def test_three_attempts_a_day_then_buying_one_back(self):
        for _ in range(3):
            self.open_city()
            self.call("hard_giveup")
            self.assertEqual(self.world()["hard_last_attack"], {"chapter": 1})
        self.assertEqual(self.open_city()["status"], "error_times")
        bought = self.call("buy_done_times")["data"]
        self.assertEqual((bought["hard_done_times"], bought["buy_hard_times"]), (2, 1))
        self.assertEqual(self.open_city()["status"], 0)


class EliteConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = services(CONFIG_DIR)

    def test_the_elite_tab_opens_by_player_level(self):
        row = self.svc.configs.get("guide_team")[config_overrides.ELITE_GUIDE_TEAM]
        self.assertEqual((row["open_sort"], row["open_value"]),
                         (2, config_overrides.ELITE_OPEN_LEVEL))

    def test_elite_cities_are_harder_than_the_normal_city_of_their_level(self):
        tiers = difficulty.Difficulty.load(self.svc.configs).tiers
        for elite, normal in (("310", "158"), ("320", "177")):
            self.assertGreater(tiers[elite].power, tiers[normal].power)
        self.assertTrue({"301", "420"} <= set(tiers))


if __name__ == "__main__":
    unittest.main()
