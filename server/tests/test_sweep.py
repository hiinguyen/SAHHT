"""Auto battle ("càn quét"): private_city.auto_recapture and clear_sweep_log."""

import unittest

from tests.test_flow import FIXTURE_CONFIGS
from tests.test_gameplay import PlayerCase

CITY = "100"
BUILDING = 100001
MAX_SWEEP = 2


class SweepCase(PlayerCase):
    def extra_configs(self):
        fixture = FIXTURE_CONFIGS["map_title_detail"]
        return {
            "map_title_detail": {**fixture, str(BUILDING): {
                **fixture[str(BUILDING)], "max_sweep": MAX_SWEEP,
                "reward_sweep_base": [[1, 0, 7], [6, 1018, 1]]}},
            "vip": {"0": {"need_exp": 200, "sweep_times": 0},
                    "1": {"need_exp": 1200, "sweep_times": 1}},
            "pay": {"11": {"coin": [100]}},
        }

    def sweep(self, building=BUILDING):
        return self.call("private_city.auto_recapture", city=CITY, building=str(building))

    def log(self):
        return self.call("private_city.open", city=CITY)["data"]["sweep_log"]

    def status(self):
        return self.call("user.main_page")["user_status"]


class AutoRecaptureTests(SweepCase):
    def test_a_building_not_yet_recaptured_cannot_be_swept(self):
        self.assertEqual(self.sweep()["status"], "error_building_locked")
        self.assertEqual(self.log(), {})

    def test_unknown_building_is_a_parameter_error(self):
        self.assertEqual(self.sweep(999999)["status"], "error_param")

    def test_sweep_pays_exp_and_the_sweep_loot_and_costs_stamina(self):
        self.fight(BUILDING)
        before = self.status()
        body = self.sweep()
        self.assertEqual(body["status"], 0, body)
        data = body["data"]
        self.assertEqual(data["reward"], {"food": 7, "item": [1018]})
        rewards = data["battle_rewards"]
        self.assertEqual(rewards["reward_item"], {"1018": 1})
        self.assertEqual(len(rewards["reward_exp_player"]), 3)
        self.assertEqual(rewards["reward_character"], [])
        after = self.status()
        self.assertEqual(after["food"] - before["food"], 7)
        # The fixture's level-ups refill 5 stamina each (role.recover_point).
        refill = 5 * (after["level"] - before["level"])
        self.assertEqual(after["action_point"], before["action_point"] - 4 + refill)

    def test_sweeps_are_counted_per_building_and_capped_per_day(self):
        self.fight(BUILDING)
        for used in range(1, MAX_SWEEP + 1):
            self.assertEqual(self.sweep()["status"], 0)
            self.assertEqual(self.log(), {str(BUILDING): used})
        self.assertEqual(self.sweep()["status"], "error_sweep_limit")
        self.assertEqual(self.log(), {str(BUILDING): MAX_SWEEP})

    def test_a_sweep_without_stamina_is_refused_and_not_counted(self):
        self.fight(BUILDING)
        stamina = self.status()["action_point"]
        self.server.services.store.change_action_point(self.uid, -stamina, 0)
        self.assertEqual(self.sweep()["status"], "error_action_point")
        self.assertEqual(self.log(), {})


class ClearSweepLogTests(SweepCase):
    def clear(self):
        return self.call("private_city.clear_sweep_log", city=CITY, building=str(BUILDING))

    def exhaust(self):
        self.fight(BUILDING)
        for _ in range(MAX_SWEEP):
            self.sweep()

    def test_a_vip_player_buys_a_fresh_allowance_for_coin(self):
        self.exhaust()
        self.server.services.store.change_wallet(self.uid, {"vip_exp": 200})
        coin = self.status()["coin"]
        self.assertEqual(self.clear()["status"], 0)
        self.assertEqual(self.status()["coin"], coin - 100)
        self.assertEqual(self.log(), {})
        self.assertEqual(self.sweep()["status"], 0)

    def test_a_non_vip_player_cannot_reset(self):
        self.exhaust()
        self.assertEqual(self.clear()["status"], "error_vip")
        self.assertEqual(self.log(), {str(BUILDING): MAX_SWEEP})

    def test_a_reset_needs_the_coin(self):
        self.exhaust()
        self.server.services.store.change_wallet(self.uid, {"vip_exp": 200})
        self.server.services.store.change_wallet(self.uid, {"coin": -self.status()["coin"]})
        self.assertEqual(self.clear()["status"], "error_coin")
        self.assertEqual(self.log(), {str(BUILDING): MAX_SWEEP})


if __name__ == "__main__":
    unittest.main()
