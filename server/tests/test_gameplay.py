"""Gameplay over the real protocol: campaign rewards, tutorial, heroes, recruiting, shop, bag."""

import unittest
from unittest import mock

from sahht_server import (cards, equipment, equipment_actions, equipment_enchant, equipment_fate,
                          equipment_forge, equipment_refine, equipment_split)
from sahht_server.handlers import Refused
from sahht_server.rewards import Loot, grant
from tests.test_flow import FIXTURE_CONFIGS, ServerCase


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

    def recruit(self, times=1):
        if self.call("gacha.get_all_gacha")["data"]["gacha_all"].get("999"):
            self.call("gacha.get_gacha", gacha_type="999")
        bodies = [self.call("gacha.get_gacha", gacha_type="101") for _ in range(times)]
        return [cid for b in bodies for cid in b["data"]["new_card"]]


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
    def extra_configs(self):
        return {"guide": {**FIXTURE_CONFIGS["guide"],
                          "5": {str(i): {"guide_team": 5} for i in range(501, 504)}},
                "guide_team": {**FIXTURE_CONFIGS["guide_team"],
                               "5": {"guide_sort": 1, "open_sort": 3, "open_value": 103001}}}

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
        self.assertEqual(done, {"1": 27, "2": 28, "5": 503})   # 5: hero evolution, see below

    def test_hero_evolution_opens_with_stage_1_1_and_the_first_tutorial(self):
        # Button 502 reads guide team 5 >= 501; the team is finished outright.
        self.fight(100001)
        self.assertNotIn("5", self.call("user.main_page")["user_status"]["guide"])
        self.call("user.guide", guide_team="1", guide_id="27")
        guide = self.call("user.main_page")["user_status"]["guide"]
        self.assertEqual(guide["5"], 503)
        self.assertEqual(guide["2"], 28)   # the tutorial chain is untouched

    def test_hero_evolution_stays_closed_before_stage_1_1_is_cleared(self):
        self.call("user.guide", guide_team="1", guide_id="27")
        self.assertNotIn("5", self.call("user.main_page")["user_status"]["guide"])

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


class EquipmentCase(PlayerCase):
    """A player with one piece of each slot, plus the grid helper the gear tests share."""

    def setUp(self):
        super().setUp()
        self.weapon, self.armor, self.boots, self.ring = (
            self.server.services.store.add_equipment(self.uid, [10101, 20101, 30101, 40101]))

    def alignment(self, **slots):
        attack = [self.card_id(c) for c in (5300, 100, 200)] + ["-1", "-1"]
        equip = {f"equip_1{i}": "0_0_0_0" for i in range(1, 6)}
        equip.update({f"equip_2{i}": "0_0_0_0" for i in range(1, 6)})
        equip["equip_11"] = "_".join([slots.get("weapon", "0"), slots.get("armor", "0"),
                                      slots.get("boots", "0"), slots.get("ring", "0")])
        return self.call("cards.set_alignment", form={
            "align_1": "_".join(attack), "align_2": "-1_-1_-1", "formation": "1", **equip})

    def stats(self, equip_ids):
        svc = self.server.services
        by_id = {e["id"]: e for e in svc.store.equipment_rows(self.uid)}
        return equipment.bonus(svc.configs, equip_ids, by_id)


class EquipmentTests(EquipmentCase):
    def test_equipment_documents_and_slots_round_trip(self):
        data = self.call("cards.open")["data"]
        self.assertEqual(len(data["equip"]), 5)   # starter weapon + the four added
        self.assertLessEqual({self.weapon, self.armor, self.boots, self.ring},
                             set(data["equip"]))
        self.assertEqual(data["equip"][self.weapon],
                         {"id": self.weapon, "c_id": 10101, "lv": 1, "st_lv": 0})
        self.assertEqual(data["equip_pos"]["0"], ["0", "0", "0", "0"])
        # game_data.godequipInEquipPos indexes the god-field grids unguarded whenever an
        # equipment icon is drawn (the evolution screen crashed without them).
        for key in ("equip_pos_1", "equip_pos_2", "equip_pos_3"):
            self.assertEqual(data[key], {str(i): ["0"] * 4 for i in range(10)})
        # equipInBonus (cheer-formation gear) indexes keys "200".."209" for every icon too.
        self.assertEqual(data["bonus_equip_pos"], {str(i): [0] * 4 for i in range(200, 210)})

        body = self.alignment(weapon=self.weapon, armor=self.armor)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["equip_pos"]["0"],
                         [self.weapon, self.armor, "0", "0"])
        data = self.call("cards.open")["data"]
        self.assertEqual(data["equip_pos"]["0"], [self.weapon, self.armor, "0", "0"])
        self.assertEqual(data["equip_pos"]["1"], ["0", "0", "0", "0"])

    def test_equipment_adds_its_two_attributes_to_combat(self):
        before = self.call("user.main_page")["data"]["combat"]
        self.alignment(weapon=self.weapon, armor=self.armor)
        after = self.call("user.main_page")["data"]["combat"]
        # weapon: patk 100, hp 200; armor: def 50, hp 100. getCombatValue uses
        # patk*1 + def*0.8 + hp*0.6, times the card's skill factor (1 + 0.1).
        self.assertEqual(after - before, int((100 + 40 + 180) * 1.1))

    def level_up(self):
        self.server.services.store.set_level(self.uid, 5, 0, 0)
        self.server.services.store.change_wallet(self.uid, {"metal": 10000})

    def test_single_enhance_charges_the_config_cost_and_raises_the_level(self):
        self.level_up()
        body = self.call("factory.equip_levelup", magor=self.weapon, lvs="2")
        self.assertEqual(body["status"], 0, body)
        doc = body["data"]["_client_cache_update"]["equip"]["_equip"]["update"][self.weapon]
        self.assertEqual(doc["lv"], 3)
        self.assertEqual(body["user_status"]["metal"], 10000 - 100 - 200)
        self.assertEqual(self.call("factory.equip_levelup", magor=self.weapon, lvs="99")
                         ["status"], 0)
        self.assertEqual(self.server.services.store.equipment_row(self.uid, self.weapon)["lv"], 5)

    def stock_for_evolution(self, metal=1000, items=20):
        store = self.server.services.store
        store.change_wallet(self.uid, {"metal": metal})
        store.change_items(self.uid, {100001: items})
        return store

    def test_evolution_swaps_the_config_and_spends_metal_item_and_a_spare_copy(self):
        store = self.stock_for_evolution()
        store.set_equipment_level(self.uid, self.weapon, 3)
        spare = next(e["id"] for e in store.equipment_rows(self.uid)
                     if e["c_id"] == 10101 and e["id"] != self.weapon)
        body = self.call("equip.evolution", equip_id=self.weapon)
        self.assertEqual(body["status"], 0, body)
        cache = body["data"]["_client_cache_update"]
        self.assertEqual(cache["equip"]["_equip"]["update"][self.weapon],
                         {"id": self.weapon, "c_id": 10102, "lv": 3, "st_lv": 0})
        self.assertEqual(cache["equip"]["_equip"]["remove"], [spare])
        self.assertEqual(body["user_status"]["metal"], 0)
        self.assertEqual(store.items(self.uid).get(100001, 0), 0)
        self.assertIsNone(store.equipment_row(self.uid, spare))
        self.assertEqual(store.equipment_row(self.uid, self.weapon)["c_id"], 10102)

    def test_evolution_is_refused_and_changes_nothing_when_a_material_is_short(self):
        store = self.stock_for_evolution(items=19)
        before = store.equipment_rows(self.uid)
        body = self.call("equip.evolution", equip_id=self.weapon)
        self.assertEqual(body["status"], "error_not_enough")
        self.assertEqual(store.equipment_rows(self.uid), before)
        self.assertEqual(store.wallet(self.uid)["metal"], 1000)
        self.assertEqual(store.items(self.uid)[100001], 19)

    def test_an_equipped_copy_is_not_a_material(self):
        store = self.stock_for_evolution()
        spare = next(e["id"] for e in store.equipment_rows(self.uid)
                     if e["c_id"] == 10101 and e["id"] != self.weapon)
        self.assertEqual(self.alignment(weapon=spare)["status"], 0)
        self.assertEqual(self.call("equip.evolution", equip_id=self.weapon)["status"],
                         "error_not_enough")

    def test_evolution_refuses_unknown_pieces_a_fully_evolved_one_and_the_paid_shortcut(self):
        store = self.stock_for_evolution()
        self.assertEqual(self.call("equip.evolution", equip_id="999999")["status"], "error_param")
        self.assertEqual(self.call("equip.evolution", equip_id=self.weapon, is_buy="1")["status"],
                         "error_not_open")
        [top] = store.add_equipment(self.uid, [self.top_evolution()])
        self.assertEqual(self.call("equip.evolution", equip_id=top)["status"], "error_param")

    def refine(self, equip_id, roll):
        """Call equip.st_levelup with the dice fixed to `roll` (0-99, success when < rate)."""
        with mock.patch.object(equipment_actions.random, "randrange", return_value=roll):
            return self.call("equip.st_levelup", equip_id=equip_id)

    def stock_for_refine(self, st_lv=0):
        store = self.server.services.store
        store.change_wallet(self.uid, {"metal": 10000, "metalcore": 1000})
        store.set_equipment_st_level(self.uid, self.weapon, st_lv)
        return store

    def test_a_successful_refine_raises_the_level_and_spends_metal_and_metalcore(self):
        store = self.stock_for_refine(st_lv=2)
        body = self.refine(self.weapon, roll=0)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["success"], "true")
        update = body["data"]["_client_cache_update"]["equip"]["_equip"]["update"]
        self.assertEqual(update[self.weapon]["st_lv"], 3)
        self.assertEqual(body["user_status"]["metal"], 10000 - 1000)
        self.assertEqual(body["user_status"]["metalcore"], 1000 - 30)   # row 3
        self.assertEqual(store.equipment_row(self.uid, self.weapon)["st_lv"], 3)

    def test_a_failed_refine_still_costs_and_falls_back_per_the_current_row(self):
        store = self.stock_for_refine(st_lv=8)
        body = self.refine(self.weapon, roll=99)          # 99 >= 20 (row 9 rate)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["success"], "false")
        self.assertEqual(store.equipment_row(self.uid, self.weapon)["st_lv"], 7)
        self.assertEqual(body["user_status"]["metalcore"], 1000 - 90)
        self.assertEqual(self.refine(self.weapon, roll=99)["data"]["success"], "false")
        self.assertEqual(store.equipment_row(self.uid, self.weapon)["st_lv"], 7)   # row 7 holds

    def test_refine_is_refused_when_short_at_the_maximum_or_for_an_unknown_piece(self):
        store = self.stock_for_refine(st_lv=3)
        store.change_wallet(self.uid, {"metalcore": -1000 + 10})   # 10 left, row 4 needs 40
        self.assertEqual(self.refine(self.weapon, roll=0)["status"], "error_not_enough")
        self.assertEqual(store.equipment_row(self.uid, self.weapon)["st_lv"], 3)
        self.assertEqual(store.wallet(self.uid)["metal"], 10000)
        store.change_wallet(self.uid, {"metalcore": 1000})
        store.set_equipment_st_level(self.uid, self.weapon, 10)
        self.assertEqual(self.refine(self.weapon, roll=0)["status"], "error_max_level")
        self.assertEqual(self.refine("999999", roll=0)["status"], "error_param")

    def top_evolution(self):
        equip = self.server.services.configs.get("equip")
        return next(int(k) for k, v in equip.items() if not v.get("evolution"))

    def test_one_key_enhance_raises_every_piece_until_the_metal_runs_out(self):
        self.level_up()
        body = self.call("equip.all_equip_levelup_auto")
        self.assertEqual(body["status"], 0, body)
        levels = {e["id"]: e["lv"] for e in self.server.services.store.equipment_rows(self.uid)}
        self.assertEqual(set(levels.values()), {5})
        update = body["data"]["_client_cache_update"]["equip"]["_equip"]["update"]
        self.assertLessEqual({self.weapon, self.armor, self.boots, self.ring}, set(update))

    def test_selling_unequipped_gear_gives_metal_but_equipped_gear_is_refused(self):
        body = self.call("equip.sell", form={"equip": [self.ring]})
        self.assertEqual(body["data"]["sell_metal"], 100)
        self.assertEqual(body["user_status"]["metal"], 100)
        self.assertNotIn(self.ring, {e["id"] for e in
                                    self.server.services.store.equipment_rows(self.uid)})
        self.alignment(weapon=self.weapon)
        body = self.call("equip.sell", form={"equip": [self.weapon]})
        self.assertEqual(body["status"], "error_param")

    def test_a_wrong_slot_or_a_duplicate_is_refused(self):
        wrong = self.alignment(armor=self.weapon)   # weapon in the armor slot
        self.assertEqual(wrong["status"], "error_param")
        self.assertEqual(self.alignment(weapon=self.weapon)["status"], 0)
        form = {"align_1": "_".join([self.card_id(c) for c in (5300, 100, 200)] + ["-1", "-1"]),
                "align_2": "-1_-1_-1", "formation": "1"}
        form.update({f"equip_1{i}": "0_0_0_0" for i in range(1, 6)})
        form.update({f"equip_2{i}": "0_0_0_0" for i in range(1, 6)})
        form["equip_11"] = f"{self.weapon}_0_0_0"
        form["equip_12"] = f"{self.weapon}_0_0_0"
        self.assertEqual(self.call("cards.set_alignment", form=form)["status"], "error_param")

    def base_stats(self, equip_ids):
        stats = self.stats(equip_ids)
        return {key: stats[key] for key in equipment.STAT_KEYS}

    def test_a_two_piece_suit_adds_its_second_effect_only(self):
        ids = self.server.services.store.add_equipment(self.uid, [11101, 21101])
        self.assertEqual(self.base_stats(ids), {"hp": 40, "patk": 110, "matk": 75,
                                               "def": 10, "speed": 0})

    def test_four_pieces_add_the_second_third_and_fourth_effects(self):
        ids = self.server.services.store.add_equipment(
            self.uid, [11101, 21101, 31101, 41101])
        self.assertEqual(self.base_stats(ids), {"hp": 1080, "patk": 210, "matk": 160,
                                               "def": 60, "speed": 160})

    def test_a_full_suit_reaches_the_main_page_combat_number(self):
        store = self.server.services.store
        ids = store.add_equipment(self.uid, [11101, 21101, 31101, 41101])
        before = self.call("user.main_page")["data"]["combat"]
        body = self.alignment(weapon=ids[0], armor=ids[1], boots=ids[2], ring=ids[3])
        self.assertEqual(body["status"], 0, body)
        # 210 patk + 160 matk + 60 def * 0.8 + 160 speed * 0.6 + 1080 hp * 0.6 = 1162
        # on one card, times its 1.1 skill factor.
        self.assertEqual(self.call("user.main_page")["data"]["combat"] - before, int(1162 * 1.1))

    def test_a_full_bag_refuses_a_draw_and_a_gear_reward(self):
        store = self.server.services.store
        store.change_wallet(self.uid, {"silver": 100000})
        store.add_equipment(self.uid, [10101] * (equipment.EQUIP_MAX - store.equipment_count(self.uid)))
        self.assertEqual(store.equipment_count(self.uid), equipment.EQUIP_MAX)
        body = self.call("equip_gacha.get_gacha", gacha_type="1")
        self.assertEqual(body["status"], "error_equip_full")
        self.assertEqual(store.wallet(self.uid)["silver"], 102000)
        with self.assertRaises(Refused):
            with store.transaction():
                grant(self.server.services, self.uid, Loot(equips=[10101]), 0)


class EquipmentSplitTests(EquipmentCase):
    def split(self, *ids, **extra):
        return self.call("equip.exchange", form={"equip_id": list(ids), **extra})

    def test_splitting_pays_the_exchange_row_and_both_refunds(self):
        store = self.server.services.store
        store.set_equipment_level(self.uid, self.weapon, 3)
        store.set_equipment_st_level(self.uid, self.weapon, 2)
        with mock.patch.object(equipment_split.random, "randrange", side_effect=[600, 3]):
            body = self.split(self.weapon)
        self.assertEqual(body["status"], 0, body)
        # 600 drawn metal + 100 + 200 enhance + 1000 + 1000 refine; 3 + 10 + 20 metalcore.
        self.assertEqual(body["data"]["reward"], {"metal": 2900, "metalcore": 33})
        self.assertEqual(body["user_status"]["metal"], 2900)
        self.assertEqual(body["user_status"]["metalcore"], 33)
        self.assertEqual(body["data"]["_client_cache_update"]["equip"]["_equip"]["remove"],
                         [self.weapon])
        self.assertIsNone(store.equipment_row(self.uid, self.weapon))

    def test_a_worn_bound_repeated_or_foreign_piece_refuses_the_whole_batch(self):
        store = self.server.services.store
        self.alignment(weapon=self.weapon)
        self.assertEqual(self.split(self.weapon)["status"], "error_param")
        store.set_equipment_extra(self.uid, self.ring, {"bind_card": "1"})
        self.assertEqual(self.split(self.ring)["status"], "error_param")
        self.assertEqual(self.split(self.boots, self.boots)["status"], "error_param")
        self.assertEqual(self.split("999999")["status"], "error_param")
        self.assertEqual(len(store.equipment_rows(self.uid)), 5)


class EquipmentRefineTests(EquipmentCase):
    def setUp(self):
        super().setUp()
        self.store = self.server.services.store
        self.store.change_wallet(self.uid, {"refine_stone": 100, "metal": 10000, "coin": 100})

    def refine(self, sort, mode, is_save, rolls):
        with mock.patch.object(equipment_refine.random, "uniform", return_value=0), \
                mock.patch.object(equipment_refine.random, "randrange", side_effect=rolls):
            return self.call("equip.equip_refine", equip_id=self.weapon, sort=str(sort),
                             type=str(mode), is_save=str(is_save))

    def test_a_preview_rolls_and_charges_but_stores_nothing(self):
        body = self.refine(1, 1, 0, [1, 2])
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["equip_refine"], {"patk": 1, "hp": 2})
        self.assertEqual(body["user_status"]["refine_stone"], 97)
        self.assertNotIn("equip_refine", self.store.equipment_extra(self.uid, self.weapon))
        self.assertNotIn("_client_cache_update", body["data"])

    def test_saving_rolls_again_and_stores_both_attributes_with_hp(self):
        body = self.refine(1, 1, 1, [1, 2])
        self.assertEqual(body["status"], 0, body)
        stored = self.store.equipment_extra(self.uid, self.weapon)["equip_refine"]
        self.assertEqual((stored["patk"], stored["hp"]), (1, 2))
        doc = body["data"]["_client_cache_update"]["equip"]["_equip"]["update"][self.weapon]
        self.assertEqual(doc["equip_refine"]["hp"], 2)
        self.assertEqual(body["user_status"]["refine_stone"], 97)

    def test_the_running_total_is_clamped_to_the_control_range(self):
        self.store.set_equipment_extra(self.uid, self.weapon,
                                       {"equip_refine": {"patk": 39, "hp": 29}})
        self.refine(1, 3, 1, [9, 8])
        stored = self.store.equipment_extra(self.uid, self.weapon)["equip_refine"]
        self.assertEqual((stored["patk"], stored["hp"]), (40, 30))

    def test_five_rolls_cost_five_times_the_row_and_a_short_wallet_refuses(self):
        body = self.refine(5, 2, 0, [1, 1] * 5)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["user_status"]["refine_stone"], 90)     # 2 per roll
        self.assertEqual(body["user_status"]["metal"], 7000)          # 600 per roll
        self.store.change_wallet(self.uid, {"refine_stone": -80})     # 10 left
        self.assertEqual(self.refine(5, 1, 1, [1, 1] * 5)["status"], "error_not_enough")
        self.assertEqual(self.refine(1, 4, 1, [1, 1])["status"], "error_param")

    def test_auto_refine_reports_the_caps_and_then_rolls_what_is_affordable(self):
        info = self.call("equip.auto_refine", equip_id=self.weapon, type="1", handle_sort="1",
                         is_buy="0")["data"]
        # patk needs ceil(40 / 5) = 8 best-band rolls, hp ceil(30 / 4) = 8; 3 stones
        # each, so 24 of the 100 held.
        self.assertEqual(info["max_refine_info"]["need_times"], 8)
        self.assertEqual(info["can_refine_info"]["need_times"], 8)
        self.assertEqual(info["max_refine_info"]["refine_stone_need"], 24)
        self.store.change_wallet(self.uid, {"refine_stone": -94})     # 6 left -> 2 rolls
        body = self.call("equip.auto_refine", equip_id=self.weapon, type="1", handle_sort="2",
                         is_buy="1")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["user_status"]["refine_stone"], 0)
        self.assertIn("equip_refine", self.store.equipment_extra(self.uid, self.weapon))

    def test_refine_adds_its_two_attributes_to_the_bonus(self):
        self.store.set_equipment_extra(self.uid, self.weapon,
                                       {"equip_refine": {"patk": 10, "hp": 20}})
        stats = equipment.bonus(self.server.services.configs, [self.weapon],
                                {e["id"]: e for e in self.store.equipment_rows(self.uid)})
        # weapon base: patk 100, hp 200.
        self.assertEqual((stats["patk"], stats["hp"]), (110, 220))


class EquipmentEnchantTests(EquipmentCase):
    def setUp(self):
        super().setUp()
        self.store = self.server.services.store
        self.store.change_wallet(self.uid, {"enchant": 1000})

    def enchant(self, equip_id=None):
        with mock.patch.object(equipment_enchant.random, "choice", return_value="fire"), \
                mock.patch.object(equipment_enchant.random, "randrange", return_value=50):
            return self.call("equip.enchant", equip_id=equip_id or self.weapon)

    def save(self, is_save, equip_id=None):
        return self.call("equip.save_init_enchant", equip_id=equip_id or self.weapon,
                         is_save=str(is_save))

    def test_the_first_enchant_waits_for_save_and_costs_pieces(self):
        body = self.enchant()
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["enchant_attrs"], {"fire": 50})
        self.assertEqual(body["user_status"]["enchant"], 920)
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        self.assertNotIn("is_enchant", doc)
        self.assertNotIn("enchant_pending", doc)

    def test_saving_keeps_the_roll_cancelling_drops_it(self):
        self.enchant()
        saved = self.save(1)
        self.assertEqual(saved["data"]["cur_atts"], {"fire": 50})
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        self.assertTrue(doc["is_enchant"])
        self.assertEqual(doc["atts"], {"fire": 50})
        self.enchant(self.armor)
        self.assertEqual(self.save(0, self.armor)["status"], 0)
        doc = self.call("cards.open")["data"]["equip"][self.armor]
        self.assertNotIn("is_enchant", doc)

    def test_each_later_enchant_adds_a_step_and_stops_at_the_cap(self):
        self.enchant()
        self.save(1)
        body = self.enchant()
        self.assertEqual(body["data"]["cur_atts"], {"fire": 100})
        self.assertEqual(body["data"]["enchant_attrs"], {"fire": 50})
        self.store.set_equipment_extra(self.uid, self.weapon,
                                       {"is_enchant": True, "atts": {"fire": 2980}})
        self.assertEqual(self.enchant()["data"]["cur_atts"], {"fire": 3000})

    def test_armour_uses_two_defence_keys(self):
        with mock.patch.object(equipment_enchant.random, "sample",
                               return_value=["fire_dfs", "water_dfs"]), \
                mock.patch.object(equipment_enchant.random, "randrange", return_value=10):
            body = self.call("equip.enchant", equip_id=self.boots)
        self.assertEqual(body["data"]["enchant_attrs"], {"fire_dfs": 10, "water_dfs": 10})

    def test_removing_returns_the_pieces_spent_and_clears_the_state(self):
        self.enchant()
        self.save(1)
        self.enchant()
        body = self.call("equip.remove_enchant", equip_id=self.weapon)
        self.assertEqual(body["data"]["enchant"], 160)
        self.assertEqual(body["user_status"]["enchant"], 1000)
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        self.assertNotIn("is_enchant", doc)

    def test_the_quick_enchant_prompt_gets_every_field_it_reads(self):
        self.enchant()
        self.save(1)
        data = self.call("equip.auto_enchant", equip_id=self.weapon, sort="-1")["data"]
        self.assertEqual(data["need_times"], 50)          # (3000 - 50) / 60 -> 50
        self.assertEqual(data["can_times"], 11)           # 920 pieces / 80
        self.assertEqual(data["enchant_cost"], 80)
        self.assertEqual(data["need_enchant"], 80)
        self.assertEqual(data["cur_atts"], {"fire": 50})


class EquipmentForgeTests(EquipmentCase):
    def setUp(self):
        super().setUp()
        self.store = self.server.services.store
        self.store.change_wallet(self.uid, {"small_forge_stone": 1000,
                                            "middle_forge_stone": 100,
                                            "high_forge_stone": 100, "metal": 100000})

    def level(self, stones):
        return self.call("equip.equip_forge_level", equip_id=self.weapon, forge_stone=stones)

    def refresh(self, sort=0, is_save=0):
        with mock.patch.object(equipment_forge.random, "uniform", return_value=0):
            return self.call("equip.equip_forge_refresh", equip_id=self.weapon,
                             sort=str(sort), is_save=str(is_save))

    def test_forge_index_returns_the_whole_document(self):
        data = self.call("equip.equip_forge_index", equip_id=self.weapon)["data"]
        self.assertEqual((data["id"], data["lv"]), (self.weapon, 1))

    def test_stones_carry_experience_into_the_next_level(self):
        body = self.level("3_0_1")        # 530 experience, level 1 needs 4000
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(self.store.equipment_extra(self.uid, self.weapon)["equip_forge_level"],
                         {"lv": 0, "exp": 530})
        body = self.level("397_0_0")      # 3970 more: level 1 with 500 left
        self.assertEqual(body["status"], 0, body)
        stored = self.store.equipment_extra(self.uid, self.weapon)
        self.assertEqual(stored["equip_forge_level"], {"lv": 1, "exp": 500})
        # The refresh popup reads next(equip_forge) unguarded, so it exists from level 1.
        self.assertEqual(stored["equip_forge"], {})
        self.assertEqual(body["user_status"]["small_forge_stone"], 600)

    def test_a_refresh_previews_three_distinct_properties_then_saves_them(self):
        self.level("400_0_0")
        preview = self.refresh(0, 0)
        doc = preview["data"]["_client_cache_update"]["equip"]["_equip"]["update"][self.weapon]
        self.assertEqual(doc["equip_forge_temp"],
                         {"1": {"patk": 324}, "2": {"matk": 221}, "3": {"def": 114}})
        self.assertEqual(preview["user_status"]["small_forge_stone"], 590)
        self.assertEqual(preview["user_status"]["metal"], 98000)
        saved = self.refresh(0, 1)
        doc = saved["data"]["_client_cache_update"]["equip"]["_equip"]["update"][self.weapon]
        self.assertEqual(doc["equip_forge"]["1"], {"patk": 324})
        self.assertTrue(doc["is_equip_forge"])

    def test_a_level_up_recomputes_the_stored_values(self):
        self.level("400_0_0")
        self.refresh(0, 0)
        self.refresh(0, 1)
        self.level("0_0_16")      # 8000 more: level 2 with 0 left
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        self.assertEqual(doc["equip_forge"], {"1": {"patk": 348}, "2": {"matk": 243},
                                              "3": {"def": 128}})

    def test_forge_attributes_enter_the_bonus_and_stones_are_required(self):
        self.level("400_0_0")
        self.refresh(0, 0)
        self.refresh(0, 1)
        stats = equipment.bonus(self.server.services.configs, [self.weapon],
                                {e["id"]: e for e in self.store.equipment_rows(self.uid)})
        self.assertEqual((stats["patk"], stats["matk"], stats["def"]), (424, 221, 114))
        self.store.change_wallet(self.uid, {"small_forge_stone": -590})
        self.assertEqual(self.refresh(0, 0)["status"], "error_not_enough")


class EquipmentFateTests(EquipmentCase):
    def setUp(self):
        super().setUp()
        self.store = self.server.services.store
        self.store.change_wallet(self.uid, {"min_fate_stone": 100, "mid_fate_stone": 100,
                                            "max_fate_stone": 100})
        self.card = self.card_id(5300)

    def bind(self):
        return self.call("equip.fate_equip_bind", equip_id=self.weapon, card_id=self.card)

    def refresh(self, sort=1, amounts=(0, 0.03, 0, 0.02)):
        with mock.patch.object(equipment_fate.random, "uniform",
                               side_effect=list(amounts)):
            return self.call("equip.fate_equip_levelup", equip_id=self.weapon, sort=str(sort))

    def test_binding_costs_ten_stones_and_starts_both_percentages(self):
        body = self.bind()
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["user_status"]["min_fate_stone"], 90)
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        self.assertEqual(doc["bind_card"], self.card)
        self.assertEqual(doc["bind_data"], {"1": 0, "5": 0})
        self.assertEqual(doc["gem_fate"], [0, 0, 0, 0])
        cards = self.call("cards.open")["data"]["cards"]
        self.assertEqual(cards[self.card]["bind_equip"], {"1": self.weapon})

    def test_a_refresh_pays_both_rows_and_reports_the_change_and_range(self):
        self.bind()
        body = self.refresh()
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["bind_data_temp"], {"1": 3.0, "5": 2.0})
        self.assertEqual(body["data"]["fate_range"], {"1": [-2.0, 9.0], "5": [-2.0, 9.0]})
        self.assertEqual(body["user_status"]["min_fate_stone"], 80)
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        self.assertEqual(doc["bind_data"], {"1": 3.0, "5": 2.0})

    def test_bound_gear_scales_its_card_combat(self):
        self.bind()
        before = self.call("user.main_page")["data"]["combat"]
        self.refresh()
        # patk floor(200 * 1.03) = 206 (+6) and hp floor(6300 * 1.02) = 6426 (+75.6 of
        # combat before the 1.1 skill factor): 81.6 * 1.1 = 89.76, truncated to 89.
        after = self.call("user.main_page")["data"]["combat"]
        self.assertEqual(after - before, 89)

    def test_unbinding_refunds_the_bind_cost_and_clears_the_fields(self):
        self.bind()
        body = self.call("equip.fate_equip_unbind", equip_id=self.weapon)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["min_fate_stone"], 10)
        self.assertEqual(body["user_status"]["min_fate_stone"], 100)
        doc = self.call("cards.open")["data"]["equip"][self.weapon]
        for key in ("bind_card", "bind_data", "gem_fate"):
            self.assertNotIn(key, doc)
        self.assertEqual(self.call("equip.fate_equip_levelup", equip_id=self.weapon, sort="1")
                         ["status"], "error_param")

    def test_quick_refresh_rolls_until_the_threshold_is_crossed(self):
        self.bind()
        with mock.patch.object(equipment_fate.random, "uniform",
                               side_effect=[0, 0.09] * 20):
            body = self.call("equip.auto_fate_equip_levelup", equip_id=self.weapon, sort="1")
        self.assertEqual(body["status"], 0, body)
        self.assertGreaterEqual(body["data"]["leveup_times"], 1)
        self.assertEqual(body["user_status"]["min_fate_stone"], 0)




class EquipGachaTests(PlayerCase):
    def test_a_draw_costs_silver_and_creates_an_equipment_instance(self):
        available = self.call("equip_gacha.get_all_gacha")["data"]
        self.assertEqual(available["gacha_all"], {"1": -1})
        body = self.call("equip_gacha.get_gacha", gacha_type="1")
        self.assertEqual(body["status"], 0, body)
        [entry] = body["data"]["new_card"]
        self.assertEqual(entry[0], 7)
        self.assertEqual(entry[2], 10101)
        equip_id = entry[1]
        self.assertEqual(body["user_status"]["silver"], 2000 - 75)
        cached = body["data"]["_client_cache_update"]["equip"]["_equip"]["update"]
        self.assertEqual(cached[equip_id]["c_id"], 10101)
        self.assertEqual(self.call("cards.open")["data"]["equip"][equip_id]["lv"], 1)

    def test_a_broken_pool_id_is_refused(self):
        self.assertEqual(self.call("equip_gacha.get_gacha", gacha_type="404")["status"],
                         "error_gacha")


class HeroTests(PlayerCase):
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

    def test_evolution_accepts_universal_cards_with_string_character_ids(self):
        # character_detail.config stores character_ID as a string ("1001" is the orange card).
        characters = {"100": {"character_ID": "7"}, "200": {"character_ID": "8"},
                      "51": {"character_ID": "1001"}, "53": {"character_ID": "1003"}}
        rules = mock.Mock(characters=characters)
        major = {"c_id": 100}
        self.assertTrue(cards._evolution_material(rules, major, {"c_id": 51}))
        self.assertTrue(cards._evolution_material(rules, major, {"c_id": 53}))
        self.assertFalse(cards._evolution_material(rules, major, {"c_id": 200}))

    def twins_of_hero_100(self, count):
        """Recruit until the player owns `count` spare copies of hero 100; returns their ids."""
        for _ in range(40):
            cards = self.call("cards.open")["data"]["cards"]
            twins = [i for i, c in cards.items()
                     if c["c_id"] == 100 and i != self.card_id(100)]
            if len(twins) >= count:
                return twins
            self.recruit(3)
        self.fail("gacha never gave enough copies of hero 100")

    def raise_hero_100_to_level(self, level):
        svc = self.server.services
        svc.store.update_card(self.uid, self.card_id(100), lv=level, exp=0, step=0)

    def test_quick_evolution_previews_then_climbs_to_the_chosen_step(self):
        self.raise_hero_100_to_level(6)
        major, twins = self.card_id(100), self.twins_of_hero_100(2)
        preview = self.call("cards.auto_evolution", major=major, is_save="0", sort="0", step="2")
        self.assertEqual((preview["status"], preview["data"]["sort"]), (0, 0))
        self.assertGreaterEqual(preview["data"]["max_step"], 2)   # at least two spares
        body = self.call("cards.auto_evolution", major=major, is_save="1", sort="0", step="2")
        self.assertEqual(body["status"], 0)
        cache = body["data"]["_client_cache_update"]["cards"]["cards"]
        self.assertEqual(cache["update"][major]["step"], 2)
        self.assertEqual(sorted(cache["remove"]), sorted(twins[:2]))
        self.assertEqual(body["user_status"]["food"], 10000 - 2 * 400)

    def test_quick_evolution_defaults_to_one_step(self):
        self.raise_hero_100_to_level(6)
        major, twins = self.card_id(100), self.twins_of_hero_100(1)
        body = self.call("cards.auto_evolution", major=major, is_save="1", sort="0")
        self.assertEqual(body["data"]["_client_cache_update"]["cards"]["cards"]["update"][major]["step"], 1)
        self.assertEqual(len(body["data"]["_client_cache_update"]["cards"]["cards"]["remove"]), 1)

    def test_quick_evolution_changes_nothing_when_a_step_is_out_of_reach(self):
        self.twins_of_hero_100(3)
        major = self.card_id(100)   # level 1: step 1 already needs level 2
        before = self.call("cards.open")["data"]["cards"]
        body = self.call("cards.auto_evolution", major=major, is_save="1", sort="0", step="3")
        self.assertEqual(body["status"], "error_level")
        self.assertEqual(self.call("cards.open")["data"]["cards"], before)

    def test_quick_evolution_refuses_when_materials_run_short(self):
        self.raise_hero_100_to_level(6)
        major = self.card_id(100)
        twins = self.twins_of_hero_100(1)
        for extra in twins[1:]:   # keep exactly one spare copy
            self.call("cards.butcher", form={"card_id": [extra]})
        body = self.call("cards.auto_evolution", major=major, is_save="1", sort="0", step="3")
        self.assertEqual(body["status"], "error_not_enough")
        self.assertEqual(self.call("cards.open")["data"]["cards"][major]["step"], 0)

    def test_quick_evolution_refuses_a_step_that_is_not_ahead(self):
        major = self.card_id(100)
        for step in ("0", "-1", "x"):
            body = self.call("cards.auto_evolution", major=major, is_save="0", sort="0", step=step)
            self.assertEqual(body["status"], "error_param")

    def test_selling_gives_food_and_refuses_team_cards(self):
        spare = self.recruit()[0]
        body = self.call("cards.butcher", form={"card_id": [spare]})
        self.assertEqual(body["data"]["get_food"], 100)
        self.assertEqual(body["data"]["_client_cache_update"]["cards"]["cards"]["remove"], [spare])
        team = self.call("cards.butcher", form={"card_id": [self.card_id(5300)]})
        self.assertEqual(team["status"], "error_param")


class HeroLockTests(PlayerCase):
    def test_lock_marks_the_card_and_blocks_selling_until_released(self):
        spare = self.recruit()[0]
        body = self.call("cards.lock_card", card_id=spare)
        cache = body["data"]["_client_cache_update"]["cards"]["cards"]
        self.assertEqual(cache["update"][spare]["remove_avail"], ["user"])
        self.assertEqual(self.call("cards.open")["data"]["cards"][spare]["remove_avail"], ["user"])
        self.assertEqual(self.call("cards.butcher", form={"card_id": [spare]})["status"],
                         "error_param")

        body = self.call("cards.release_card", card_id=spare)
        cache = body["data"]["_client_cache_update"]["cards"]["cards"]
        self.assertEqual(cache["update"][spare]["remove_avail"], [])
        self.assertEqual(self.call("cards.butcher", form={"card_id": [spare]})["status"], 0)

    def test_a_card_that_is_not_the_players_cannot_be_locked(self):
        self.assertEqual(self.call("cards.lock_card", card_id="999999")["status"], "error_param")
        self.assertEqual(self.call("cards.release_card", card_id="nope")["status"], "error_param")


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


class VipShopTests(PlayerCase):
    def extra_configs(self):
        return {"vip_store": {
            "1": {"need_value": [[9, 0, 100]], "shop_item": [[6, 1018, 1]],
                  "sell_max": 2, "show_vip": 1},
            "2": {"need_value": [[9, 0, 200]], "shop_item": [[6, 27, 1]],
                  "sell_max": 1, "show_vip": 2},
        }}

    def setUp(self):
        super().setUp()
        self.server.services.store.change_wallet(self.uid, {"vip_exp": 200})  # VIP 1

    def test_the_shop_lists_nothing_bought_and_charges_coin_per_item(self):
        self.assertEqual(self.call("shop.vip_store_index")["data"]["date"], {})
        body = self.call("shop.vip_store_buy", shop_id="1", count="1")
        self.assertEqual(body["data"]["reward"], {"item": [1018]})
        self.assertEqual(body["data"]["date"], {"1": 1})
        self.assertEqual(body["user_status"]["coin"], 900)
        self.assertEqual(self.server.services.store.items(self.uid)[1018], 3)

        body = self.call("shop.vip_store_buy", shop_id="1", count="1")
        self.assertEqual(body["data"]["date"], {"1": 2})
        self.assertEqual(body["user_status"]["coin"], 800)
        self.assertEqual(self.call("shop.vip_store_buy", shop_id="1")["status"],
                         "error_sell_max")

    def test_the_vip_level_and_the_shop_id_are_checked(self):
        self.assertEqual(self.call("shop.vip_store_buy", shop_id="2")["status"], "error_vip")
        self.assertEqual(self.call("shop.vip_store_buy", shop_id="404")["status"], "error_param")
        self.assertEqual(self.call("shop.vip_store_buy", shop_id="1", count="0")["status"],
                         "error_param")


if __name__ == "__main__":
    unittest.main()
