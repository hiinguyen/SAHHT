"""Daily tasks, achievements and bounty list (reward.*)."""

import time
import unittest

from sahht_server import quests
from tests.test_gameplay import PlayerCase

CONFIGS = {
    "reward_diary": {
        "1": {"num": 2, "reward_score": 5, "target_sort": 78, "target_data": [1], "story": "a"},
        "2": {"num": 1, "reward_score": 10, "target_sort": 24, "target_data": [1], "story": "b"},
        "3": {"num": 1, "reward_score": 10, "target_sort": 28, "target_data": [1], "story": "c"},
    },
    "diaryscore": {"5": [[9, 0, 7]], "15": [[9, 0, 40]], "20": [[9, 0, 90]], "30": [[9, 0, 1]]},
    "reward_once": {
        "1": {"target_sort": 79, "target_data": [720], "reward": [[9, 0, 1]], "story": ""},
        "1001": {"target_sort": 1, "target_data": [1], "reward": [[9, 0, 25]], "story": ""},
        "1002": {"target_sort": 1, "target_data": [50], "reward": [[9, 0, 1]], "story": ""},
        "1003": {"target_sort": 1, "target_data": [1], "reward": [[117, 100, 1, 3]], "story": ""},
        "2001": {"target_sort": 2, "target_data": [100], "reward": [[9, 0, 60]], "story": ""},
        "3001": {"target_sort": 69, "target_data": [1000], "reward": [[9, 0, 1]], "story": ""},
    },
    "wanted": {
        "1021": {"target_sort": 100, "target_data": [100], "target_data1": [100],
                 "reward": [[9, 0, 33]], "story": ""},
        "1042": {"target_sort": 106, "target_data": [100001], "target_data1": [2],
                 "reward": [[9, 0, 1]], "story": ""},
    },
}


class QuestCase(PlayerCase):
    def extra_configs(self):
        return CONFIGS

    def clear_city(self):
        store = self.server.services.store
        for building in (100001, 100002, 100003, 100004, 100005):
            store.mark_cleared(self.uid, building)

    def record(self, sort, amount=1):
        svc = self.server.services
        with svc.store.transaction():
            quests.record(svc, self.uid, sort, int(time.time()), amount)

    def coin(self):
        return self.call("user.main_page")["user_status"]["coin"]

    def alerts(self):
        return self.call("user.main_page")["data"]["alerts"]

    def diary(self):
        return self.call("reward.diary_index")["data"]


class DiaryTests(QuestCase):
    def test_diary_lists_only_rows_with_a_live_source_and_all_four_slots(self):
        data = self.diary()
        self.assertEqual(set(data["diary"]["result"]), {"1", "2"})
        self.assertTrue(all(data["diary"]["result"].values()))
        self.assertEqual(data["diaryscore"], 0)
        self.assertEqual([b["slot"] for b in data["diary_boxes"]], [1, 2, 3, 4])
        self.assertEqual([b["score"] for b in data["diary_boxes"]], [5, 15, 20, 30])
        self.assertEqual(data["diaryscore_done"], [])

    def test_events_add_points_capped_by_num(self):
        self.record(78, 5)
        self.record(24)
        data = self.diary()
        self.assertEqual(data["diary_done"], {"1": 5, "2": 1})
        self.assertEqual(data["diaryscore"], 2 * 5 + 10)

    def test_a_won_campaign_fight_counts(self):
        self.fight(100001)
        self.assertEqual(self.diary()["diary_done"]["1"], 1)

    def test_box_needs_the_score_and_is_claimed_once_with_its_reward(self):
        self.assertNotEqual(self.call("reward.diary_score_award", score="5", slot="1")["status"], 0)
        self.record(78, 2)
        coin = self.coin()
        body = self.call("reward.diary_score_award", score="5", slot="1")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], coin + 7)
        self.assertEqual(body["data"]["diaryscore_done"], [5])
        self.assertTrue(body["data"]["diary_boxes"][0]["done"])
        self.assertNotEqual(self.call("reward.diary_score_award", score="5", slot="1")["status"], 0)
        self.assertNotEqual(self.call("reward.diary_score_award", score="15", slot="1")["status"], 0)

    def test_red_dot_counts_claimable_boxes(self):
        self.assertEqual(self.alerts()["diary"], 0)
        self.record(78, 2)
        self.assertEqual(self.alerts()["diary"], 1)


class OnceTests(QuestCase):
    def once(self, body):
        return body["data"]["once"]["result"]

    def test_result_has_every_row_as_value_need_state(self):
        result = self.once(self.call("reward.once_index"))
        self.assertEqual(set(result), set(CONFIGS["reward_once"]))
        self.assertEqual(result["1001"], [1, 1, 1])
        self.assertEqual(result["1002"], [1, 50, 0])
        self.assertEqual(result["2001"], [0, 100, 0])
        self.assertEqual(result["3001"][2], 0)
        self.assertEqual(result["1"][2], 0)

    def test_claim_pays_once_and_resends_the_whole_map(self):
        coin = self.coin()
        body = self.call("reward.once_award", award_id="1001")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], coin + 25)
        self.assertEqual(self.once(body)["1001"][2], 2)
        self.assertEqual(len(self.once(body)), len(CONFIGS["reward_once"]))
        for award in ("1001", "1002", "777"):
            self.assertNotEqual(self.call("reward.once_award", award_id=award)["status"], 0)

    def test_recapture_row_follows_the_cleared_city(self):
        self.clear_city()
        self.assertEqual(self.once(self.call("reward.once_index"))["2001"], [100, 100, 1])
        self.assertEqual(self.call("reward.once_award", award_id="2001")["status"], 0)

    def test_hero_reward_arrives_at_its_level(self):
        body = self.call("reward.once_award", award_id="1003")
        self.assertEqual(body["status"], 0)
        cards = body["data"]["_client_cache_update"]["cards"]["cards"]["update"]
        self.assertEqual([c["lv"] for c in cards.values()], [3])

    def test_red_dot_for_claimable_achievements(self):
        self.assertIs(self.alerts()["once"], True)
        for award in ("1001", "1003"):
            self.call("reward.once_award", award_id=award)
        self.assertIs(self.alerts()["once"], False)


class WantedTests(QuestCase):
    def wanted(self):
        return self.call("reward.index")["data"]["wanted_data"]["result"]

    def test_every_unclaimed_bounty_is_listed(self):
        result = self.wanted()
        self.assertEqual(result["1021"], [0, 100, 0])
        self.assertEqual(result["1042"], [0, 2, 0])

    def test_recaptured_city_bounty_is_claimed_once_and_then_absent(self):
        self.clear_city()
        self.assertEqual(self.wanted()["1021"], [100, 100, 1])
        coin = self.coin()
        body = self.call("reward.wanted_award", award_id="1021")
        self.assertEqual(body["user_status"]["coin"], coin + 33)
        self.assertNotIn("1021", body["data"]["wanted"]["result"])
        for award in ("1021", "1042"):
            self.assertNotEqual(self.call("reward.wanted_award", award_id=award)["status"], 0)


if __name__ == "__main__":
    unittest.main()
