"""Activity hall: today's chapters, runs and attempts, buying, sweeping, survival ladder."""

import random
import unittest
from datetime import datetime

from sahht_server import active, campaign, config_overrides, survival
from sahht_server.shop import LOCAL
from tests.test_flow import FIXTURE_CONFIGS, ServerCase, _enemy, _fight
from tools.audit_enemy_skills import CONFIG_DIR, services

OPEN_ALL = [1, 300]


def local(year, month, day, hour=12) -> int:
    return int(datetime(year, month, day, hour, tzinfo=LOCAL).timestamp())


class TodaysChapterTests(unittest.TestCase):
    """Real configs: the hall indexes today's chapter with no nil guard, so every weekday
    must yield exactly one chapter per row."""

    @classmethod
    def setUpClass(cls):
        cls.svc = services(CONFIG_DIR)

    def chapters(self, day):
        return active.todays_chapters(self.svc, local(2026, 11, day))   # 23 Nov 2026 is a Monday

    def test_daily_challenge_follows_the_weekday(self):
        self.assertEqual([self.chapters(d)["50"] for d in range(23, 30)],
                         [100, 110, 120, 130, 140, 150, 160])

    def test_extreme_challenge_repeats_twice_a_week(self):
        self.assertEqual([self.chapters(d)["60"] for d in range(23, 30)],
                         [200, 210, 220, 200, 210, 220, 230])

    def test_resource_war_and_exp_stage_are_always_open(self):
        for day in range(23, 30):
            self.assertEqual((self.chapters(day)["40"], self.chapters(day)["70"]), (1, 80))


class HallOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = services(CONFIG_DIR)

    def test_only_served_rows_stay_visible(self):
        rows = self.svc.configs.get("active")
        shown = {k for k, v in rows.items() if v["is_see"] < config_overrides.HIDDEN}
        self.assertEqual(shown, config_overrides.SERVED_HALL_ROWS)

    def test_survival_ladder_keeps_only_levels_that_have_fights(self):
        levels = self.svc.configs.get("active_fight_forever")
        self.assertEqual((len(levels), max(int(k) for k in levels)), (150, 150))
        fights = self.svc.configs.get("map_fight")
        self.assertTrue(all(str(row["fight"]) in fights for row in levels.values()))

    def test_every_survival_enemy_resolves(self):
        documents = survival._fight_documents(self.svc)
        self.assertEqual(len(documents["map_fight"]), 150)
        self.assertTrue(all("img" in e for e in documents["enemy_detail"].values()))

    def test_weighted_slots_are_drawn_in_battle_and_left_out_of_the_preview(self):
        fight = {"position1": [[11, 1]], "position2": [[21, 1], [22, 3]], "position3": [31]}
        self.assertEqual(campaign._enemy_ids(fight, None), [(3, 31)])
        drawn = campaign._enemy_ids(fight, random.Random(1))
        self.assertEqual([slot for slot, _ in drawn], [1, 2, 3])
        self.assertIn(drawn[1][1], (21, 22))


def _detail(fights, reward, need=0):
    return {"active_name": "stage", "fight": [[f"t{f}", f] for f in fights], "level": OPEN_ALL,
            "reward": reward, "combat_need": need, "reward_first_base": [],
            "reward_first_rate": []}


class ActiveCase(ServerCase):
    def extra_configs(self):
        return {
            "vip": FIXTURE_CONFIGS["vip"] | {"0": {"need_exp": 200, "active_times": 0},
                                              "1": {"need_exp": 1200, "active_times": 1}},
            "active": {key: {"active_chapterID": ids, "is_see": 1, "level": OPEN_ALL}
                       for key, ids in {"40": [1], "50": [], "60": [], "70": [80],
                                        "80": []}.items()},
            "active_chapter": {
                "1": {"active_detail": [1, 2], "times": 2, "vip_buy": [50, 50], "level": OPEN_ALL,
                      "time_sort": 1, "open": [[0, 24]]},
                "80": {"active_detail": [3], "times": 1, "vip_buy": [], "level": OPEN_ALL,
                       "time_sort": 1, "open": [[0, 24]]}},
            "active_detail": {"1": _detail([900001, 900002, 900003], [[9, 0, 100]]),
                              "2": _detail([900001], [[9, 0, 1]], need=10 ** 9),
                              "3": _detail([900001], [[9, 0, 7]])},
            "map_fight": {**FIXTURE_CONFIGS["map_fight"], "900001": _fight(777001),
                          "900002": _fight(777001), "900003": _fight(777001)},
            "enemy_detail": {"777001": _enemy(30, patk=5)},
            "active_fight_forever": {
                "1": {"fight": 900001, "reward": [[9, 0, 5]], "name": "1", "animation": "vega"},
                "2": {"fight": 900002, "reward": [[9, 0, 6]], "name": "2", "animation": "vega"},
                "3": {"fight": 900003, "reward": [[9, 0, 7]], "name": "3", "animation": "vega"}},
        }

    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]
        self.api("cards.open", self.rans, self.uid)

    def call(self, method, **params):
        return self.api(f"active.{method}", self.rans, self.uid, **params)[1]

    def stage(self, step, active_id=1, chapter=1, **extra):
        return self.call("fight", chapter=str(chapter), active_id=str(active_id),
                         step_n=str(step), **extra)

    def index(self):
        return self.call("index")["data"]


class HallTests(ActiveCase):
    def test_index_carries_every_field_the_hall_reads_unguarded(self):
        data = self.index()
        self.assertEqual(set(data["index"]), {"1", "80"})
        self.assertEqual(data["index"]["1"], {"cur_times": 0, "times": 2, "cur_buy_times": 0,
                                              "active_steps": {}})
        self.assertEqual(data["gift_reward"], {})
        forever = data["active_forever"]
        self.assertEqual((forever["done"], forever["forever_fails"], forever["forever_max_step"]),
                         ([], 0, 0))
        self.assertTrue(forever["map_fight"] and forever["enemy_detail"])

    def test_enemy_preview_sends_the_requested_fight(self):
        data = self.call("map_fight_and_enemy", chapter="1", active_id="1", step_n="1")["data"]
        self.assertEqual(set(data["map_fight"]), {"900002"})
        self.assertEqual(data["enemy_detail"]["777001"]["animation"], "vega")

    def test_a_stage_outside_the_chapter_is_refused(self):
        self.assertEqual(self.stage(0, active_id=3)["status"], "error_param")


class RunTests(ActiveCase):
    def test_a_run_costs_one_attempt_and_pays_on_the_last_step(self):
        first = self.stage(0)
        self.assertEqual((first["status"], first["data"]["next_step"], first["data"]["has_battled"]),
                         (0, 1, 1))
        self.assertEqual(first["data"]["battle"]["winer"], 1)
        mid = self.index()["index"]["1"]
        self.assertEqual((mid["cur_times"], mid["active_steps"]), (1, {"1": [0]}))
        self.assertEqual(self.stage(1)["data"]["next_step"], 2)
        coin = first["user_status"]["coin"]
        last = self.stage(2)
        self.assertEqual((last["data"]["next_step"], last["data"]["reward"]), (-1, {"coin": 100}))
        self.assertEqual(last["user_status"]["coin"], coin + 100)
        done = self.index()["index"]["1"]
        self.assertEqual((done["cur_times"], done["active_steps"]), (1, {}))

    def test_steps_must_follow_each_other(self):
        self.assertEqual(self.stage(1)["status"], "error_param")
        self.stage(0)
        self.assertEqual(self.stage(2)["status"], "error_param")

    def test_attempts_run_out_but_an_unfinished_run_can_restart_free(self):
        self.stage(0)
        self.stage(0)           # overwrites the run, not charged again
        self.assertEqual(self.index()["index"]["1"]["cur_times"], 1)
        for step in (1, 2):
            self.stage(step)
        self.stage(0)           # second attempt
        for step in (1, 2):
            self.stage(step)
        self.assertEqual(self.stage(0)["status"], "error_times")

    def test_giving_up_keeps_the_attempt_spent(self):
        self.stage(0)
        self.call("clear_fight_log", chapter="1")
        index = self.index()["index"]["1"]
        self.assertEqual((index["cur_times"], index["active_steps"]), (1, {}))

    def test_buying_needs_vip(self):
        self.stage(0)
        self.assertEqual(self.call("buy_fight_times", chapter="1")["status"], "error_times")

    def test_sweep_needs_the_combat_power_and_costs_nothing_when_it_fails(self):
        failed = self.stage(0, active_id=2, is_sweep="1")["data"]
        self.assertEqual((failed["next_step"], failed["sweep_reward"]), (0, {}))
        self.assertEqual(self.index()["index"]["1"]["cur_times"], 0)
        swept = self.stage(0, chapter=80, active_id=3, is_sweep="1")["data"]
        self.assertEqual((swept["next_step"], swept["done_times"], swept["sweep_reward"]),
                         (-1, 0, {"coin": 7}))


class SurvivalTests(ActiveCase):
    def ladder(self, level):
        return self.call("forever_fight", level=str(level))

    def test_climbing_one_level_at_a_time_pays_each_level(self):
        body = self.ladder(1)
        self.assertEqual(body["status"], 0)
        self.assertEqual((body["data"]["reward"], body["data"]["active_forever"]["done"]),
                         ({"coin": 5}, [1]))
        self.assertEqual(self.ladder(1)["status"], "error_param")
        self.assertEqual(self.ladder(3)["status"], "error_param")
        self.assertEqual(self.ladder(2)["data"]["active_forever"]["forever_max_step"], 2)

    def test_the_rush_needs_level_30_or_a_vip(self):
        self.assertEqual(self.call("auto_forever_fight")["status"], "error_level")

    def test_the_window_resets_at_nine_and_twenty_one(self):
        morning, evening = local(2026, 11, 24, 10), local(2026, 11, 24, 22)
        self.assertEqual(survival._window(morning)[0], survival._window(morning + 3600)[0])
        self.assertNotEqual(survival._window(morning)[0], survival._window(evening)[0])
        self.assertEqual(survival._window(local(2026, 11, 24, 8))[0] + 1,
                         survival._window(morning)[0])
        self.assertEqual(survival._window(local(2026, 11, 24, 21))[1], 12 * 3600)


if __name__ == "__main__":
    unittest.main()
