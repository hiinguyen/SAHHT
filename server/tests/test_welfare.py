"""Welfare tabs: free sign-in, recharge sign-in and the VIP reward track."""

import time
import unittest

from sahht_server import welfare
from sahht_server.shop import DAILY, period
from tests.test_gameplay import PlayerCase

CONFIGS = {
    "daily_award": {str(day): {"award": [[9, 0, 10 * day], [1, 0, day]], "icon": "x"}
                    for day in range(1, 4)},
    "month_award_coin": {str(day): {"award": [[9, 0, 5], [1, 0, 1]], "icon": "x", "pay": 200}
                         for day in range(1, 4)},
    "new_vip_reward": {"1": {
        **{f"day{n}": [[9, 0, 100 * n]] for n in range(1, 8)},
        "everyday": [[9, 0, 20], [2, 0, 500]]}},
}


class WelfareCase(PlayerCase):
    def extra_configs(self):
        return CONFIGS

    def coin(self):
        return self.call("user.main_page")["user_status"]["coin"]

    def alerts(self):
        return self.call("user.main_page")["data"]["alerts"]

    def make_vip(self, exp=200):
        self.server.services.store.change_wallet(self.uid, {"vip_exp": exp})

    def next_day(self):
        """Pretend the next calendar day began: expire the daily markers."""
        store = self.server.services.store
        with store.transaction():
            store._db.execute("UPDATE counters SET period = 'old' WHERE period != ''")


class SignInTests(WelfareCase):
    def test_first_visit_opens_day_one_and_lights_the_dot(self):
        self.assertIs(self.alerts()["daily"], True)
        data = self.call("daily_award.all_reward")["data"]
        self.assertEqual((data["score"], data["reward"]), (1, [1]))
        for key in ("coin_days", "coin_status", "coin_pay_rmb"):
            self.assertIsInstance(data[key], int)

    def test_the_day_advances_once_per_calendar_day(self):
        self.call("daily_award.all_reward")
        self.assertEqual(self.call("daily_award.all_reward")["data"]["score"], 1)
        self.call("user.main_page")
        self.assertEqual(self.call("daily_award.all_reward")["data"]["score"], 1)
        self.next_day()
        self.assertEqual(self.call("daily_award.all_reward")["data"]["score"], 2)

    def test_claiming_a_day_pays_once_and_clears_the_dot(self):
        self.call("daily_award.all_reward")
        coin = self.coin()
        body = self.call("daily_award.get_reward", reward="1")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], coin + 10)
        self.assertEqual(self.call("daily_award.all_reward")["data"]["reward"], [])
        self.assertIs(self.alerts()["daily"], False)
        self.assertNotEqual(self.call("daily_award.get_reward", reward="1")["status"], 0)

    def test_missed_days_can_still_be_claimed_in_order(self):
        self.call("daily_award.all_reward")
        self.next_day()
        self.assertEqual(self.call("daily_award.all_reward")["data"]["reward"], [1, 2])
        self.assertEqual(self.call("daily_award.get_reward", reward="2")["status"], 0)
        self.assertEqual(self.call("daily_award.all_reward")["data"]["reward"], [1])

    def test_unreached_unknown_and_multiple_keys_are_refused(self):
        self.call("daily_award.all_reward")
        for key in ("2", "9", "x", "1,2"):
            self.assertEqual(self.call("daily_award.get_reward", reward=key)["status"],
                             "error_param")

    def test_the_cycle_stops_at_the_last_day(self):
        for _ in range(5):
            self.call("daily_award.all_reward")
            self.next_day()
        self.assertEqual(self.call("daily_award.all_reward")["data"]["score"], 3)


class RechargeSignInTests(WelfareCase):
    def pay_today(self, coins):
        svc = self.server.services
        with svc.store.transaction():
            welfare.record_recharge(svc, self.uid, coins, int(time.time()))

    def test_status_follows_todays_recharge(self):
        data = self.call("daily_award.all_reward")["data"]
        self.assertEqual((data["coin_days"], data["coin_status"], data["coin_pay_rmb"]), (0, 0, 0))
        self.assertNotEqual(self.call("daily_award.coin_award")["status"], 0)
        self.pay_today(200)
        data = self.call("daily_award.all_reward")["data"]
        self.assertEqual((data["coin_status"], data["coin_pay_rmb"]), (1, 200))

    def test_claim_then_next_day_starts_the_next_cell(self):
        self.pay_today(300)
        coin = self.coin()
        body = self.call("daily_award.coin_award")
        self.assertEqual((body["data"]["coin_days"], body["data"]["coin_status"]), (0, 2))
        self.assertEqual(body["user_status"]["coin"], coin + 5)
        self.assertNotEqual(self.call("daily_award.coin_award")["status"], 0)
        self.next_day()
        data = self.call("daily_award.all_reward")["data"]
        self.assertEqual((data["coin_days"], data["coin_status"], data["coin_pay_rmb"]), (1, 0, 0))


class VipRewardTests(WelfareCase):
    def index(self):
        return self.call("vip_reward.sign_index")["data"]

    def test_non_vip_sees_an_empty_track(self):
        data = self.index()
        self.assertEqual((data["sign_record"], data["is_every_day"]), ({}, False))

    def test_vip_gets_a_track_entry_per_level_and_a_daily_bonus(self):
        self.make_vip()
        data = self.index()
        self.assertEqual(data["sign_record"], {"1": {"day": 0, "flag": True}})
        self.assertIs(data["is_every_day"], True)

    def test_one_track_day_per_calendar_day_paying_that_days_reward(self):
        self.make_vip()
        coin = self.coin()
        body = self.call("vip_reward.vip_sign")
        self.assertEqual(body["user_status"]["coin"], coin + 100)
        self.assertEqual(body["data"]["sign_record"], {"1": {"day": 1, "flag": False}})
        self.assertNotEqual(self.call("vip_reward.vip_sign")["status"], 0)
        self.next_day()
        self.assertEqual(self.call("vip_reward.vip_sign", vip="1")["user_status"]["coin"],
                         coin + 100 + 200)

    def test_track_ends_after_seven_days_and_other_levels_are_refused(self):
        self.make_vip()
        for _ in range(7):
            self.assertEqual(self.call("vip_reward.vip_sign")["status"], 0)
            self.next_day()
        self.assertEqual(self.index()["sign_record"]["1"], {"day": 7, "flag": False})
        self.assertNotEqual(self.call("vip_reward.vip_sign")["status"], 0)
        self.assertNotEqual(self.call("vip_reward.vip_sign", vip="2")["status"], 0)

    def test_every_day_bonus_pays_all_items_once_and_resends_the_record(self):
        self.make_vip()
        coin, metal = self.coin(), self.call("user.main_page")["user_status"]["metal"]
        body = self.call("vip_reward.every_day")
        self.assertEqual(body["user_status"]["coin"], coin + 20)
        self.assertEqual(body["user_status"]["metal"], metal + 500)
        self.assertIs(body["data"]["is_every_day"], False)
        self.assertIn("sign_record", body["data"])
        self.assertNotEqual(self.call("vip_reward.every_day")["status"], 0)

    def test_non_vip_cannot_claim(self):
        for method in ("vip_reward.vip_sign", "vip_reward.every_day"):
            self.assertNotEqual(self.call(method)["status"], 0)


class PeriodHelperTests(unittest.TestCase):
    def test_daily_period_is_a_date_string(self):
        self.assertRegex(period(DAILY, int(time.time())), r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
