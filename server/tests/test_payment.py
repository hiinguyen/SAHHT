"""Free recharge with gold tickets: payment.use_ticket and shop.vip_buy_step."""

import time
import unittest

from sahht_server.payment import parse_order
from sahht_server.player import FREE_TICKETS, vip_level
from tests.test_gameplay import PlayerCase


class ParseOrderTests(unittest.TestCase):
    def test_order_id_is_uid_server_pack_then_anything(self):
        self.assertEqual(parse_order("10001_1_3_1700000000_0_42"), ("10001", "3"))
        self.assertEqual(parse_order("10001_1_3_1700000000_ch_with_parts_42"), ("10001", "3"))

    def test_malformed_order_ids_are_rejected(self):
        for bad in ("", "10001_1_3", "abc_1_3_1_0_1", "10001_1_x_1_0_1", "10001__3_1_0_1"):
            self.assertIsNone(parse_order(bad), bad)


class VipLevelTests(unittest.TestCase):
    def test_level_counts_thresholds_reached_and_stops_at_the_top_row(self):
        class Configs:
            @staticmethod
            def get(name):
                return {"0": {"need_exp": 200}, "1": {"need_exp": 1200}, "2": {"need_exp": 3200}}
        self.assertEqual([vip_level(Configs, e) for e in (0, 199, 200, 1199, 1200, 10 ** 9)],
                         [0, 0, 1, 1, 2, 2])


class RechargeTests(PlayerCase):
    def order(self, pack, n=0):
        return f"{self.uid}_1_{pack}_{int(time.time())}_0_{n}"

    def buy(self, pack, n=0):
        return self.call("payment.use_ticket", cpOrderId=self.order(pack, n))

    def test_tickets_are_free_and_never_run_out(self):
        status = self.call("user.main_page")["user_status"]
        self.assertEqual(status["ticket"], FREE_TICKETS)
        self.buy("3")
        self.assertEqual(self.call("user.main_page")["user_status"]["ticket"], FREE_TICKETS)

    def test_a_coin_bag_gives_coin_and_vip_exp(self):
        body = self.buy("3")
        self.assertEqual(body["status"], 0, body)
        status = body["user_status"]
        self.assertEqual((status["coin"], status["vip_exp"], status["vip"]), (1000 + 220, 220, 1))

    def test_first_purchase_of_a_double_pack_doubles_its_coin(self):
        self.assertEqual(self.buy("4", 1)["user_status"]["coin"], 1000 + 550 + 50 + 550)
        self.assertEqual(self.buy("4", 2)["user_status"]["coin"], 1000 + 1150 + 600)

    def test_a_resent_order_is_paid_once(self):
        order = self.order("3")
        self.call("payment.use_ticket", cpOrderId=order)
        body = self.call("payment.use_ticket", cpOrderId=order)
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], 1000 + 220)

    def test_buy_times_caps_a_pack(self):
        self.assertEqual(self.buy("5", 1)["status"], 0)
        body = self.buy("5", 2)
        self.assertEqual(body["status"], "error_buy_times")
        self.assertEqual(body["user_status"]["coin"], 1000 + 10)

    def test_packs_with_their_own_rewards_are_not_open_yet(self):
        for pack in ("1", "22"):
            body = self.buy(pack)
            self.assertEqual((body["status"], body["msg"]), ("error_not_open", "Gói này chưa mở."))
            self.assertEqual(body["user_status"]["coin"], 1000)

    def test_bad_orders_are_refused(self):
        for order in ("junk", "99999_1_3_1_0_1", f"{self.uid}_1_77_1_0_1"):
            body = self.call("payment.use_ticket", cpOrderId=order)
            self.assertEqual(body["status"], "error_param", order)
        self.assertEqual(self.call("user.main_page")["user_status"]["coin"], 1000)

    def test_vip_buy_step_lists_packs_already_bought(self):
        self.assertEqual(self.call("shop.vip_buy_step")["data"],
                         {"step": [], "double_pay": [], "month_award": 2, "week_award": 2})
        self.buy("4", 1)
        self.buy("3", 2)
        self.buy("3", 3)
        self.assertEqual(self.call("shop.vip_buy_step")["data"]["double_pay"], [3, 4])


if __name__ == "__main__":
    unittest.main()
