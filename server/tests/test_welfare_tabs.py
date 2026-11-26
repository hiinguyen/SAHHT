"""Welfare tabs: online reward, survival supplies, growth plan and the arena achievement rows."""

import time
import unittest
from unittest import mock

from sahht_server import online, supply
from sahht_server.handlers import TIMEZONE
from tests.test_active import ActiveCase
from tests.test_gameplay import PlayerCase

CONFIGS = {
    "reward_once": {
        "1": {"target_sort": 79, "target_data": [720], "reward": [[9, 0, 7]], "story": ""},
        "2": {"target_sort": 79, "target_data": [1440], "reward": [[9, 0, 11]], "story": ""},
        "3001": {"target_sort": 69, "target_data": [1000], "reward": [[9, 0, 1]], "story": ""},
        "3028": {"target_sort": 1, "target_data": [1], "reward": [[9, 0, 5]], "story": ""},
    },
    "grow_gift": {"1": {"reward": [[9, 0, 100]]}, "2": {"reward": [[9, 0, 200], [1, 0, 5]]},
                  "50": {"reward": [[9, 0, 400]]}},
    "charge": {"12": {"buy_times": 3, "coin": 0, "gift_coin": 0, "is_double": 0, "is_show": 0,
                      "open_gift": 3, "vip_exp": 1300, "price": 130000, "name": "Grow plan"},
               "3": {"buy_times": 0, "coin": 220, "gift_coin": 0, "is_double": 0, "is_show": 1,
                     "open_gift": 0, "vip_exp": 220, "price": 20000, "name": "Pack"}},
}


def at_hour(hour: int, day: int = 0) -> int:
    """A timestamp that is `hour`:30 local time on a fixed day (plus `day` days)."""
    base = 1_700_000_000 - (1_700_000_000 + TIMEZONE * 3600) % 86400
    return base + day * 86400 + hour * 3600 + 1800


class TabCase(PlayerCase):
    def extra_configs(self):
        return CONFIGS

    def alerts(self):
        return self.call("user.main_page")["data"]["alerts"]

    def coin(self):
        return self.call("user.main_page")["user_status"]["coin"]

    def at(self, ts):
        """Run the server clock at `ts` for the supply and online code."""
        return mock.patch("time.time", return_value=ts)


class OnlineTimeTests(TabCase):
    def once(self):
        return self.call("reward.once_index")["data"]["once"]["result"]

    def set_seconds(self, seconds):
        svc = self.server.services
        svc.store.set_counter(self.uid, online.SECONDS, seconds)
        svc.store.set_counter(self.uid, online.MARK, int(time.time()))

    def test_online_rows_report_seconds_online_against_the_need(self):
        self.set_seconds(100)
        row = self.once()["1"]
        self.assertEqual((row[1], row[2]), (720, 0))
        self.assertGreaterEqual(row[0], 100)

    def test_a_row_is_claimable_once_the_need_is_reached_and_pays_once(self):
        self.set_seconds(720)
        self.assertEqual(self.once()["1"][2], 1)
        self.assertIs(self.alerts()["once"], True)
        coin = self.coin()
        body = self.call("reward.once_award", award_id="1")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(self.coin(), coin + 7)
        self.assertEqual(body["data"]["once"]["result"]["1"][2], 2)
        self.assertEqual(self.call("reward.once_award", award_id="1")["status"], "error_param")

    def test_requests_add_the_gap_between_them_but_not_a_long_absence(self):
        svc, now = self.server.services, int(time.time())
        svc.store.set_counter(self.uid, online.SECONDS, 0)
        svc.store.set_counter(self.uid, online.MARK, now - 300)
        with self.at(now):
            self.assertEqual(self.once()["1"][0], 300)
        svc.store.set_counter(self.uid, online.MARK, now - online.IDLE_LIMIT - 1)
        before = svc.store.counter(self.uid, online.SECONDS)
        with self.at(now):
            self.once()
        self.assertEqual(svc.store.counter(self.uid, online.SECONDS), before)


class ArenaRowTests(TabCase):
    def test_arena_rank_rows_stay_pending_until_an_arena_exists(self):
        row = self.call("reward.once_index")["data"]["once"]["result"]["3001"]
        self.assertEqual(row[2], 0)
        self.assertEqual(self.call("reward.once_award", award_id="3001")["status"], "error_param")

    def test_the_final_arena_row_follows_the_player_level(self):
        row = self.call("reward.once_index")["data"]["once"]["result"]["3028"]
        self.assertEqual(row[2], 1)


class SupplyTests(TabCase):
    def extra_configs(self):
        # active.index also builds the hall, which reads these fixture configs.
        return {**CONFIGS, **ActiveCase.extra_configs(self)}

    def index(self, ts):
        with self.at(ts):
            return self.call("active.index")["data"]

    def award(self, ts, award_id):
        with self.at(ts):
            return self.call("reward.gift_award", award_id=award_id)

    def test_windows_are_noon_and_evening_local_time(self):
        self.assertEqual(supply.WINDOWS, {"1": (12, 14), "2": (19, 21)})

    def test_inside_a_window_the_index_offers_it_with_the_seconds_left(self):
        data = self.index(at_hour(12))
        self.assertEqual(list(data["gift_reward"]), ["1"])
        self.assertEqual(data["gift_reward"]["1"], 90 * 60)

    def test_outside_every_window_nothing_is_offered(self):
        for hour in (3, 11, 14, 15, 18, 22):
            self.assertEqual(self.index(at_hour(hour))["gift_reward"], {}, hour)

    def test_claiming_gives_stamina_once_per_window_per_day(self):
        ts = at_hour(19)
        body = self.award(ts, "2")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["reward"]["action_point"], supply.SUPPLY_STAMINA)
        self.assertEqual(self.index(ts)["gift_reward"], {})
        self.assertEqual(self.award(ts, "2")["status"], "error_param")
        self.assertEqual(self.award(at_hour(19, 1), "2")["status"], 0)

    def test_a_window_cannot_be_claimed_outside_its_hours(self):
        self.assertEqual(self.award(at_hour(12), "2")["status"], "error_param")
        self.assertEqual(self.award(at_hour(16), "1")["status"], "error_param")
        self.assertEqual(self.award(at_hour(12), "9")["status"], "error_param")

    def test_the_dot_is_the_integer_one_the_client_compares_against(self):
        with self.at(at_hour(13)):
            self.assertEqual(self.alerts()["active"], 1)
        with self.at(at_hour(16)):
            self.assertEqual(self.alerts()["active"], 0)


class GrowPlanTests(TabCase):
    def order(self, n=0):
        return f"{self.uid}_1_12_{int(time.time())}_0_{n}"

    def buy(self, n=0):
        return self.call("payment.use_ticket", cpOrderId=self.order(n))

    def index(self):
        return self.call("active.grow_gift_index")["data"]

    def set_level(self, level):
        svc = self.server.services
        with svc.store.transaction():
            svc.store._db.execute("UPDATE players SET level = ? WHERE id = ?",
                                  (level, int(self.uid) - 10000))

    def test_a_new_player_has_not_bought_the_plan(self):
        self.assertEqual(self.index(), {"status": 0, "info": []})

    def test_buying_marks_the_plan_bought_and_adds_vip_exp_but_no_coin(self):
        coin = self.coin()
        body = self.buy()
        self.assertEqual(body["status"], 0, body)
        self.assertEqual((body["user_status"]["coin"], body["user_status"]["vip_exp"]),
                         (coin, 1300))
        self.assertEqual(self.index()["status"], 1)

    def test_the_plan_can_be_bought_only_once(self):
        self.buy(1)
        body = self.buy(2)
        self.assertEqual(body["status"], "error_buy_times")
        self.assertEqual(self.call("user.main_page")["user_status"]["vip_exp"], 1300)

    def test_a_reward_needs_the_plan_and_the_level(self):
        self.set_level(2)
        body = self.call("active.grow_gift_receive", lv="2")
        self.assertEqual(body["status"], "error_param")
        self.buy()
        self.assertEqual(self.call("active.grow_gift_receive", lv="50")["status"], "error_level")
        self.assertEqual(self.call("active.grow_gift_receive", lv="7")["status"], "error_param")

    def test_claiming_a_level_pays_once_and_lists_it(self):
        self.set_level(2)
        self.buy()
        coin = self.coin()
        body = self.call("active.grow_gift_receive", lv="2")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(self.coin(), coin + 200)
        self.assertEqual((body["data"]["status"], body["data"]["info"]), (1, [2]))
        self.assertEqual(self.call("active.grow_gift_receive", lv="2")["status"], "error_param")

    def test_the_dot_lights_when_a_bought_level_is_unclaimed(self):
        self.set_level(2)
        self.assertIs(self.alerts()["grow_gift"], False)
        self.buy()
        self.assertIs(self.alerts()["grow_gift"], True)
        self.call("active.grow_gift_receive", lv="1")
        self.call("active.grow_gift_receive", lv="2")
        self.assertIs(self.alerts()["grow_gift"], False)

    def test_other_packs_still_pay_their_coin(self):
        coin = self.coin()
        self.call("payment.use_ticket", cpOrderId=f"{self.uid}_1_3_{int(time.time())}_0_1")
        self.assertEqual(self.coin(), coin + 220)


if __name__ == "__main__":
    unittest.main()
