"""Arena and ranking: the ladder, battles, points, shop, log and the rank screens."""

import time

from sahht_server.shop import DAILY, period
from tests.test_flow import BASE, FIXTURE_CONFIGS, ServerCase


class ArenaCase(ServerCase):
    def extra_configs(self):
        return {
            "arena_award": {
                "1": {"start_rank": 1, "end_rank": 1, "per_point": 50},
                "2": {"start_rank": 2, "end_rank": 200, "per_point": 6},
            },
            "arena_shop": {
                "10": {"need_point": 500, "refresh": 1, "times": 4,
                       "show_level": [0, 300], "shop_reward": [[4, 0, 100]]},
                "13": {"need_point": 100, "refresh": 0, "times": 1,
                       "show_level": [0, 300], "shop_reward": [[7, 10101, 1]]},
            },
            "vip": {"0": {"need_exp": 200, "buy_arena": 1},
                    "1": {"need_exp": 1200, "buy_arena": 5}},
            "pay": {"3": {"coin": [10, 20]}},
            "guide": {**FIXTURE_CONFIGS["guide"],
                      "4": {str(i): {"guide_team": 4} for i in range(401, 408)}},
            "guide_team": {**FIXTURE_CONFIGS["guide_team"],
                           "4": {"guide_sort": 3, "open_sort": 4, "open_value": 103}},
        }

    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]
        self.api("cards.open", self.rans, self.uid)
        self.get(f"{BASE}/login/", method="mark_user_login",
                 rans=self.rans, user_token=self.uid)

    def call(self, method, **params):
        _, body = self.api(f"arena.{method}", self.rans, self.uid, **params)
        return body

    def rank_call(self, method, **params):
        _, body = self.get(f"{BASE}/api/", method=method, rans=self.rans,
                           user_token=self.uid, **params)
        return body

    def boost(self, uid=None, level=50):
        store = self.server.services.store
        for card in store.cards_for_player(uid or self.uid):
            store.update_card(uid or self.uid, card["id"], lv=level, exp=0,
                              step=card["step"])

    def other_player(self, account="player_two"):
        data = self.register(account=account)
        self.api("cards.open", data["rand_str"], data["uid"])
        return data


class IndexTests(ArenaCase):
    def test_a_first_visit_joins_the_bottom_with_four_opponents(self):
        body = self.call("index")
        self.assertEqual(body["status"], 0)
        data = body["data"]
        self.assertEqual(data["rank"], 100)
        self.assertEqual((data["can_battle_times"], data["buy_count"]), (10, 0))
        self.assertEqual((data["point"], data["award_expire"]), (0, 600))
        self.assertEqual((data["exchange_log"], data["log"]), ({}, []))
        self.assertEqual(len(data["front_user"]), 4)
        self.assertEqual([row["rank"] for row in data["front_user"]], [99, 98, 97, 96])
        self.assertTrue(all(row["uid"].startswith("bot:") for row in data["front_user"]))
        self.assertIsInstance(data["combat"], int)

    def test_the_arena_tutorial_is_skipped_so_the_button_opens(self):
        self.assertEqual(self.server.services.store.guide(self.uid)["4"], 407)

    def test_points_accrue_for_every_whole_period(self):
        self.call("index")
        store = self.server.services.store
        store.set_arena_award_at(self.uid, int(time.time()) - 1200)
        data = self.call("index")["data"]
        self.assertEqual(data["point"], 12)
        self.assertIn(data["award_expire"], (599, 600))

    def test_the_ladder_fills_rank_gaps_with_bots(self):
        self.call("index")
        data = self.call("top", page="4")["data"]
        self.assertEqual([row["rank"] for row in data["top"]], list(range(81, 101)))
        me = next(row for row in data["top"] if row["uid"] == self.uid)
        self.assertEqual((me["rank"], me["guild_name"]), (100, ""))


class BattleTests(ArenaCase):
    def test_a_battle_answers_the_replay_document_and_spends_one_attempt(self):
        target = self.call("index")["data"]["front_user"][0]
        body = self.call("battle", target=target["uid"])
        self.assertEqual(body["status"], 0)
        data = body["data"]
        self.assertEqual(data["has_battled"], 1)
        self.assertIsInstance(data["battle"]["winer"], int)
        self.assertIn(data["cur_rank"], (100, 99))
        self.assertEqual(body["user_status"]["level"], 1)
        self.assertEqual(self.call("index")["data"]["can_battle_times"], 9)
        log = self.call("index")["data"]["log"]
        self.assertEqual((len(log), log[0]["tp"], log[0]["is_win"]),
                         (1, "attack", data["battle"]["winer"] < 5))
        replay = self.call("replay", key=log[0]["battle_log"])
        self.assertEqual(replay["data"]["battle"], data["battle"])

    def test_winning_against_a_bot_takes_its_rank(self):
        self.call("index")
        self.boost()
        body = self.call("battle", target="bot:99")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"]["battle"]["winer"] < 5, True)
        self.assertEqual(body["data"]["cur_rank"], 99)
        ladder = self.call("top", page="4")["data"]["top"]
        self.assertEqual(next(row for row in ladder if row["rank"] == 99)["uid"], self.uid)
        self.assertTrue(next(row for row in ladder if row["rank"] == 100)["uid"].startswith("bot:"))

    def test_beating_a_real_player_swaps_ranks_and_writes_both_logs(self):
        self.call("index")
        self.boost()
        other = self.other_player()
        store = self.server.services.store
        store.create_arena_row(other["uid"], 99, int(time.time()))
        body = self.call("battle", target=other["uid"])
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"]["battle"]["winer"] < 5, True)
        self.assertEqual(store.arena_row(self.uid)[0], 99)
        self.assertEqual(store.arena_row(other["uid"])[0], 100)
        defense = store.arena_log(other["uid"])
        self.assertEqual((len(defense), defense[0]["tp"]), (1, "defense"))

    def test_a_battle_needs_an_attempt(self):
        store = self.server.services.store
        self.call("index")
        store.set_counter(self.uid, "arena:battles", 10, period(DAILY, int(time.time())))
        self.assertEqual(self.call("battle", target="bot:99")["status"], "error_times")


class BuyTests(ArenaCase):
    def test_buying_one_attempt_costs_coin_once_a_day(self):
        body = self.call("buy_count")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], 990)
        data = self.call("index")["data"]
        self.assertEqual((data["can_battle_times"], data["buy_count"]), (11, 1))
        self.assertEqual(self.call("buy_count")["status"], "error_times")


class ExchangeTests(ArenaCase):
    def test_exchanging_spends_points_and_reports_the_log(self):
        store = self.server.services.store
        store.change_wallet(self.uid, {"arena_point": 1000})
        body = self.call("exchange", shop_id="10", count="1")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"]["point"], 500)
        self.assertEqual(body["data"]["reward"], {"crystal": 100})
        self.assertEqual(body["data"]["exchange_log"], {"10": {"times": 1}})
        self.assertEqual(body["user_status"]["crystal"], 100)
        self.assertEqual(self.call("exchange", shop_id="10", count="1")["data"]["point"], 0)
        self.assertEqual(self.call("exchange", shop_id="10", count="1")["status"],
                         "error_not_enough")

    def test_a_once_only_item_stays_sold_out(self):
        store = self.server.services.store
        store.change_wallet(self.uid, {"arena_point": 1000})
        self.assertEqual(self.call("exchange", shop_id="13", count="1")["status"], 0)
        self.assertEqual(self.call("exchange", shop_id="13", count="1")["status"], "error_times")


class RankingTests(ArenaCase):
    def test_the_combat_and_level_tabs_list_the_player(self):
        for method in ("user.top_combat", "user.top_level"):
            body = self.rank_call(method)
            self.assertEqual(body["status"], 0)
            me = next(row for row in body["data"]["top"] if row["uid"] == self.uid)
            self.assertEqual((me["name"], me["level"], me["role"], me["title"]),
                             ("player_one", 1, 1, 0))

    def test_the_arena_tab_is_the_same_ladder(self):
        body = self.rank_call("arena.top", page="0")
        self.assertEqual(body["status"], 0)
        self.assertEqual([row["rank"] for row in body["data"]["top"]], list(range(1, 21)))
        self.assertEqual(body["data"]["top"][0]["guild_name"], "")

    def test_unserved_tabs_answer_empty_lists(self):
        self.assertEqual(self.rank_call("user.top_world_boss_hurt")["data"]["top"], [])
        self.assertEqual(self.rank_call("association.guild_all")["data"]["guild_list"], [])
        self.assertEqual(self.rank_call("user.top_rank", sort="like")["data"]["top"], [])

    def test_world_recovery_counts_cleared_buildings(self):
        body = self.rank_call("user.top_rank", sort="world_regain")
        me = next(row for row in body["data"]["top"] if row["uid"] == self.uid)
        self.assertEqual(me["score"], 0)

    def test_user_info_answers_a_player_and_a_bot(self):
        body = self.rank_call("user.info", uid=self.uid)
        self.assertEqual(body["status"], 0)
        new_data = body["data"]["new_data"]
        self.assertEqual(new_data["user"]["name"], "player_one")
        self.assertIn("cards", new_data)
        self.assertIn("formation", new_data)

        bot = self.rank_call("user.info", uid="bot:99")
        self.assertEqual(bot["status"], 0)
        self.assertEqual(bot["data"]["new_data"]["user"]["uid"], "bot:99")
        self.assertTrue(bot["data"]["new_data"]["cards"])
