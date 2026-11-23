"""Gameplay over the real protocol: campaign rewards, tutorial, heroes, recruiting, shop, bag."""

import unittest

from sahht_server.handlers import Refused
from sahht_server.rewards import Loot, grant
from tests.test_flow import ServerCase


class PlayerCase(ServerCase):
    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]
        self.cards = self.call("cards.open")["data"]["cards"]

    def call(self, method, form=None, **params):
        _, body = self.api(method, self.rans, self.uid, form, **params)
        return body

    def fight(self, building, step=0):
        return self.call("private_city.recapture", city="100", building=str(building),
                         step_n=str(step))

    def card_id(self, c_id):
        return next(k for k, c in self.cards.items() if c["c_id"] == c_id)


class StarterTests(PlayerCase):
    def test_new_player_starts_the_tutorial_with_money_and_a_bag(self):
        status = self.call("user.main_page")["user_status"]
        self.assertEqual(status["guide"], {"1": 1})
        self.assertEqual((status["coin"], status["silver"], status["food"]), (1000, 2000, 10000))

    def test_combat_power_follows_the_client_formula(self):
        body = self.call("user.main_page")["data"]
        # hp*0.6 + patk + matk + def*0.8 + speed*0.6 at level 1, times 1 + 0.1 per active skill.
        expected = sum((int((1000 + c) * 0.6) + 200 + 150 + 80 + 150) * 1.1
                       for c in (5300, 100, 200))
        self.assertEqual(body["combat"], int(expected))


class RobustnessTests(PlayerCase):
    def test_a_failed_transaction_leaves_nothing_behind(self):
        store = self.server.services.store
        with self.assertRaises(RuntimeError):
            with store.transaction():
                store.change_wallet(self.uid, {"coin": 500})
                raise RuntimeError("crash in the middle of a handler")
        self.assertEqual(store.wallet(self.uid)["coin"], 1000)

    def test_unicode_digits_are_refused_not_crashed_on(self):
        self.assertEqual(self.call("shop.buy", shop_id="500", count="²")["status"], "error_param")
        self.assertEqual(self.api("cards.open", self.rans, "²")[1]["status"], "error_need_login")
        self.assertEqual(self.call("user.guide", guide_team="1", guide_id="５")["status"],
                         "error_param")

    def test_guide_steps_are_limited_to_known_teams_and_steps(self):
        self.assertEqual(self.call("user.guide", guide_team="9", guide_id="1")["status"],
                         "error_param")
        self.call("user.guide", guide_team="1", guide_id="999")
        self.assertEqual(self.call("user.main_page")["user_status"]["guide"]["1"], 27)

    def test_inherit_into_a_capped_card_keeps_the_giver(self):
        giver, taker = self.card_id(100), self.card_id(5300)
        self.fight(100001)   # level 1: every card is capped at 19 exp
        body = self.call("cards.inherit", master=giver, student=taker, use_exp_ball="0")
        self.assertEqual(body["status"], "error_max_level")
        cards = self.call("cards.open")["data"]["cards"]
        self.assertEqual((cards[giver]["lv"], cards[giver]["exp"]), (1, 19))


class LegacyAccountTests(ServerCase):
    def test_exp_stored_under_the_old_curve_is_settled_into_levels(self):
        data = self.register()
        uid = data["uid"]
        self.server.services.store.set_level(uid, 1, 36, 0)   # 100-exp levels of old
        _, body = self.api("cards.open", data["rand_str"], uid)
        status = body["user_status"]
        # role fixture: 10 to leave level 1, 20 to leave level 2 -> level 3 with 6 left.
        self.assertEqual((status["level"], status["exp"], status["exp_max"]), (3, 6, 30))


class TutorialTests(PlayerCase):
    def test_guide_progress_only_moves_forward(self):
        self.assertEqual(self.call("user.guide", guide_team="1", guide_id="5")["status"], 0)
        self.call("user.guide", guide_team="1", guide_id="3")
        self.assertEqual(self.call("user.main_page")["user_status"]["guide"], {"1": 5})
        self.assertEqual(self.call("user.guide", guide_team="x")["status"], "error_param")

    def test_the_next_team_starts_only_after_the_first_is_done(self):
        # Team 2's condition (city 100 reached) already holds, but the client switches to
        # team 2 as soon as it sees guide["2"] = 28, so it must wait for team 1's last step.
        self.fight(100001)
        self.assertEqual(self.call("user.guide", guide_team="1", guide_id="26")["user_status"]["guide"],
                         {"1": 26})
        done = self.call("user.guide", guide_team="1", guide_id="27")["user_status"]["guide"]
        self.assertEqual(done, {"1": 27, "2": 28})

    def test_rename_changes_the_show_name(self):
        self.assertEqual(self.call("user.rename", show_name="Ten%20Moi")["status"], 0)
        self.assertEqual(self.call("user.main_page")["user_status"]["show_name"], "Ten Moi")
        self.assertEqual(self.call("user.rename", show_name="")["status"], "error_param")


class CampaignRewardTests(PlayerCase):
    def test_victory_reports_player_and_card_experience(self):
        data = self.fight(100001)["data"]
        rewards = data["battle_rewards"]
        # 6 exp from 0 toward level 2 (10 needed): [added, old, [[lv, need]]].
        self.assertEqual(rewards["reward_exp_player"], [6, 0, [[1, 10]]])
        # Every attacker gets an entry; the player is level 1, so cards stop one point
        # short of level 2 (20 needed) and only 19 of the 23 exp count.
        self.assertEqual(set(rewards["reward_exp_character"]), set(self.cards))
        for entry in rewards["reward_exp_character"].values():
            self.assertEqual(entry, [19, 0, [[1, 20]]])
        updated = data["_client_cache_update"]["cards"]["cards"]
        self.assertEqual(updated["remove"], [])
        self.assertEqual({(c["lv"], c["exp"]) for c in updated["update"].values()}, {(1, 19)})

    def test_first_clear_gives_the_first_reward_then_sweeps_give_less(self):
        first = self.fight(100001)["data"]
        self.assertEqual(first["reward"], {"food": 100, "item": [1018]})
        self.assertEqual(first["_client_cache_update"]["item"]["items"]["update"], {"1018": [3]})
        again = self.fight(100001)["data"]
        self.assertEqual(again["reward"], {"silver": 5})
        status = self.call("user.main_page")["user_status"]
        self.assertEqual((status["food"], status["silver"]), (10100, 2005))

    def test_half_done_building_resumes_where_it_stopped(self):
        self.fight(100001)
        won = self.fight(100002, 0)["data"]
        self.assertEqual((won["next_step"], won["reward"]), (1, {}))
        log = self.call("private_city.open", city="100")["data"]["recapture_log"]
        self.assertEqual(log, {"100002": [0]})
        # The next building stays locked; the next step finishes this one and clears the log.
        self.assertEqual(self.fight(100003)["status"], "error_building_locked")
        self.assertEqual(self.fight(100002, 1)["data"]["next_step"], -1)
        self.assertEqual(self.call("private_city.open", city="100")["data"]["recapture_log"], {})

    def test_a_later_step_cannot_be_fought_first(self):
        self.fight(100001)
        self.assertEqual(self.fight(100002, 1)["status"], "error_param")


class FormationTests(PlayerCase):
    def test_formation_is_saved_from_a_post_body(self):
        a, b, c = (self.card_id(i) for i in (5300, 100, 200))
        body = self.call("cards.set_alignment", form={"align_1": f"{b}_-1_{a}_-1_-1",
                                                      "align_2": f"{c}_-1_-1_-1_-1"},
                         kqg_cjxy="1")
        self.assertEqual(body["status"], 0)
        expected = [[b, "-1", a, "-1", "-1"], [c, "-1", "-1"]]
        self.assertEqual(body["data"]["alignment"], expected)
        self.assertEqual(self.call("cards.open")["data"]["alignment"], expected)

    def test_chosen_layout_is_kept_and_used_in_battle(self):
        a = self.card_id(5300)
        body = self.call("cards.set_alignment", form={"align_1": f"{a}", "align_2": "",
                                                      "formation": "5"})
        self.assertEqual(body["data"]["formation"], {"current": 5, "own": [1, 5]})
        self.assertEqual(self.call("cards.open")["data"]["formation"]["current"], 5)
        self.assertEqual(self.fight(100001)["data"]["battle"]["init"]["aform"], 5)
        bad = self.call("cards.set_alignment", form={"align_1": f"{a}", "formation": "9"})
        self.assertEqual(bad["status"], "error_param")

    def test_formation_refuses_foreign_or_repeated_cards(self):
        a = self.card_id(5300)
        bad = self.call("cards.set_alignment", form={"align_1": f"{a}_{a}", "align_2": ""})
        self.assertEqual(bad["status"], "error_param")
        self.assertEqual(self.call("cards.set_alignment", align_1="99999")["status"], "error_param")


class HeroTests(PlayerCase):
    def recruit(self, times=1):
        if self.call("gacha.get_all_gacha")["data"]["gacha_all"].get("999"):
            self.call("gacha.get_gacha", gacha_type="999")
        bodies = [self.call("gacha.get_gacha", gacha_type="101") for _ in range(times)]
        return [cid for b in bodies for cid in b["data"]["new_card"]]

    def test_a_hero_after_2018_is_never_granted(self):
        svc = self.server.services
        with self.assertRaises(Refused) as caught:
            with svc.store.transaction():
                grant(svc, self.uid, Loot(cards=[100, 38800]), 0)
        self.assertEqual(caught.exception.body["status"], "error_scope")
        self.assertEqual(len(svc.store.cards_for_player(self.uid)), 3)

    def test_inherit_moves_seventy_percent_and_resets_the_giver(self):
        self.fight(100001)   # level 1 caps cards at 19 exp; the player reaches level 2
        self.fight(100001)   # cards: level 2 with 22 exp
        giver, taker = self.card_id(100), self.card_id(5300)
        body = self.call("cards.inherit", master=giver, student=taker, use_exp_ball="0")
        update = body["data"]["_client_cache_update"]["cards"]["cards"]["update"]
        self.assertEqual((update[giver]["lv"], update[giver]["exp"]), (1, 0))
        # The giver had 20 + 22 = 42 exp; 70% = 29 lands on the taker's 22, still level 2
        # (40 needed), and level 2 is the cap at player level 2: 39 is one short.
        self.assertEqual((update[taker]["lv"], update[taker]["exp"]), (2, 39))

    def test_skill_levelup_eats_cards_and_costs_food(self):
        material = self.recruit()[0]
        major = self.card_id(5300)
        body = self.call("cards.card_skill_levelup", major=major, pos="1", metal=[material])
        cache = body["data"]["_client_cache_update"]["cards"]["cards"]
        self.assertEqual(cache["remove"], [material])
        self.assertEqual(cache["update"][major]["s_1"]["lv"], 2)  # 50 exp; level 1 needs 50
        self.assertEqual(body["user_status"]["food"], 10000 - 50)
        locked = self.call("cards.card_skill_levelup", major=major, pos="2",
                           metal=[self.recruit()[0]])
        self.assertEqual(locked["status"], "error_param")

    def test_evolution_needs_level_and_a_same_line_material(self):
        major = self.card_id(100)
        new = self.recruit(3)
        cards = self.call("cards.open")["data"]["cards"]
        twin = next(i for i in new if cards[i]["c_id"] == 100)
        self.assertEqual(self.call("cards.card_evolution", major=major, metal=[twin])["status"],
                         "error_level")  # evolution step 1 needs card level 2
        self.fight(100001)
        self.fight(100001)
        body = self.call("cards.card_evolution", major=major, metal=[twin])
        self.assertEqual(body["status"], 0)
        card = body["data"]["_client_cache_update"]["cards"]["cards"]["update"][major]
        self.assertEqual((card["evo"], card["step"]), (1, 1))
        self.assertEqual(card["patk"] - 200 - 14 * (card["lv"] - 1), 10)  # evolution type0 bonus
        self.assertEqual(body["user_status"]["food"], 10000 + 100 - 400)

    def test_selling_gives_food_and_refuses_team_cards(self):
        spare = self.recruit()[0]
        body = self.call("cards.butcher", form={"card_id": [spare]})
        self.assertEqual(body["data"]["get_food"], 100)
        self.assertEqual(body["data"]["_client_cache_update"]["cards"]["cards"]["remove"], [spare])
        team = self.call("cards.butcher", form={"card_id": [self.card_id(5300)]})
        self.assertEqual(team["status"], "error_param")


class GachaTests(PlayerCase):
    def test_tutorial_pool_comes_first_and_opens_the_rest(self):
        pools = self.call("gacha.get_all_gacha")["data"]
        self.assertEqual(pools["gacha_all"], {"999": 1})
        self.assertIsInstance(pools["energy_slot"], int)
        body = self.call("gacha.get_gacha", gacha_type="999")["data"]
        [new_id] = body["new_card"]
        card = body["_client_cache_update"]["cards"]["cards"]["update"][new_id]
        self.assertEqual(card["c_id"], 3800)
        self.assertEqual(body["gacha_all"], {"101": -1})
        self.assertEqual(self.call("user.main_page")["user_status"]["silver"], 2000 - 250)

    def test_draws_cost_coin_and_the_pity_score_forces_a_good_hero(self):
        self.call("gacha.get_gacha", gacha_type="999")
        body = self.call("gacha.get_gacha", gacha_type="101")["data"]
        heroes = [body["_client_cache_update"]["cards"]["cards"]["update"][i]["c_id"]
                  for i in body["new_card"]]
        # Two heroes per draw at 50 pity points each: unless the first is already the good
        # hero (which resets the score), the second reaches 100 and is forced to be it.
        self.assertIn(200, heroes)
        self.assertEqual(len(heroes), 2)
        self.assertEqual(self.call("user.main_page")["user_status"]["coin"], 700)

    def test_locked_pool_and_empty_wallet_are_refused(self):
        self.assertEqual(self.call("gacha.get_gacha", gacha_type="101")["status"], "error_gacha")
        self.call("gacha.get_gacha", gacha_type="999")
        for _ in range(3):
            self.call("gacha.get_gacha", gacha_type="101")
        broke = self.call("gacha.get_gacha", gacha_type="101")
        self.assertEqual(broke["status"], "error_not_enough")
        self.assertEqual(broke["user_status"]["coin"], 100)
        self.assertEqual(len(self.call("cards.open")["data"]["cards"]), 3 + 1 + 6)


class ShopTests(PlayerCase):
    def test_shop_lists_only_supported_entries_and_prices_escalate(self):
        items = self.call("shop.open")["data"]["items"]
        self.assertEqual(set(items), {"500", "501", "502"})
        self.assertEqual(items["500"]["bought"], 0)
        body = self.call("shop.buy", shop_id="500", count="2")
        self.assertEqual(body["data"]["bought"], 2)
        self.assertEqual(body["user_status"]["coin"], 1000 - 10 - 20)
        self.assertEqual(body["user_status"]["food"], 10000 + 8000)
        self.assertEqual(self.call("shop.buy", shop_id="500", count="2")["status"], "error_sell_max")
        # Daily with sell_max 0 shows as sold out in the client; only sell_sort 0 is uncapped.
        self.assertEqual(self.call("shop.buy", shop_id="501")["status"], "error_sell_max")
        self.assertEqual(self.call("shop.buy", shop_id="502", count="3")["data"]["bought"], 3)

    def test_items_open_boxes_and_restore_stamina(self):
        body = self.call("item.use", item_id="27", num="1")
        self.assertEqual(body["data"]["effect"], {"action_point": 5})
        self.assertEqual(body["user_status"]["action_point"], 125)
        self.assertEqual(body["data"]["_client_cache_update"]["item"]["items"]["remove"], ["27"])
        self.assertEqual(self.call("item.use", item_id="27", num="1")["status"], "error_item")
        self.assertEqual(self.call("item.use", item_id="1018", num="1")["status"], "error_item")


if __name__ == "__main__":
    unittest.main()
