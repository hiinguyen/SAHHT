"""Gems: stacks, formation grid, synthesis, resolve, evolution and the stats they add."""

from unittest import mock

from sahht_server import campaign, gem_actions, gems
from sahht_server.rewards import Loot, grant
from tests.test_gameplay import PlayerCase

PLAIN_FIRE, SYNTH_FIRE, DEFENCE = "101", "201", "111"


def gem_row(**fields):
    base = {"ability": 201, "ability2": 0, "career": 1, "evo_max": 3, "exchange": [7, 12],
            "gem_num": 0, "iron": 0, "need_gem": 0, "need_item": [], "quality": 1, "team": 1,
            "value": 1250, "value2": 0, "first_name": "Lửa", "last_name": "Lv1", "icon": "x"}
    return {**base, **fields}


GEM_CONFIGS = {
    "gem": {
        PLAIN_FIRE: gem_row(),
        # three plain fire gems, 100 metal and one item 303 make one of these
        SYNTH_FIRE: gem_row(value=2000, gem_num=3, iron=100, need_gem=101,
                            need_item=[[6, 303, 1]], exchange=[10, 20]),
        DEFENCE: gem_row(ability=301, ability2=5, career=2, value=800, value2=500, team=5),
    },
    "gem_evolution": {
        "1": {"ability": [[201, 50], [301, 40, 60]], "false_back": 0, "metal": 1000,
              "gem_material": [[6, 304, 5]], "gem_material_return": [[6, 304, 4]],
              "rate": 100, "super_multiple": 1},
        "2": {"ability": [[201, 90], [301, 70, 100]], "false_back": 1, "metal": 1000,
              "gem_material": [[6, 304, 8]], "gem_material_return": [[6, 304, 6]],
              "rate": 50, "super_multiple": 2},
        "3": {"ability": [[201, 130], [301, 100, 150]], "false_back": 1, "metal": 2000,
              "gem_material": [[6, 304, 10]], "gem_material_return": [[6, 304, 8]],
              "rate": 40, "super_multiple": 3},
    },
}


class GemCase(PlayerCase):
    def extra_configs(self):
        return GEM_CONFIGS

    def setUp(self):
        super().setUp()
        self.store = self.server.services.store

    def stock(self, owned=None, metal=0, items=None):
        self.store.change_gems(self.uid, owned or {})
        self.store.change_wallet(self.uid, {"metal": metal} if metal else {})
        self.store.change_items(self.uid, items or {})

    def item(self, item_id):
        return self.store.items(self.uid).get(item_id, 0)

    def place(self, **slots):
        """Set the gem grid: gem_11 is position 0 (slots s0..s3); the rest stay empty."""
        form = {f"gem_{g}{o}": "0_0_0_0" for g in (1, 2) for o in range(1, 6)}
        form["gem_11"] = "_".join(slots.get(f"s{i}", "0") for i in range(4))
        attack = [self.card_id(c) for c in (5300, 100, 200)] + ["-1", "-1"]
        return self.call("cards.set_alignment", form={
            "align_1": "_".join(attack), "align_2": "-1_-1_-1", "formation": "1", **form})


class GemStorageTests(GemCase):
    def test_cards_open_sends_an_empty_stock_and_a_complete_grid(self):
        data = self.call("cards.open")["data"]
        self.assertEqual(data["gem"], {})
        self.assertEqual(data["gem_pos"], {str(i): ["0"] * 4 for i in range(10)})

    def test_type_19_rewards_become_gems_with_a_cache_update(self):
        granted = grant(self.server.services, self.uid,
                        Loot.of([[19, 101, 2], [19, 101, 1]]), 0)
        self.assertEqual(self.store.gems(self.uid), {"101": 3})
        self.assertEqual(granted.reward["gem"], ["101", "101", "101"])
        self.assertEqual(granted.cache["gem"], {"_gem": {"update": {"101": 3}, "remove": []}})
        self.assertEqual(self.call("cards.open")["data"]["gem"], {"101": 3})

    def test_a_stack_cannot_go_negative_and_a_spent_stack_is_deleted(self):
        self.store.change_gems(self.uid, {"101": 2})
        self.assertFalse(self.store.change_gems(self.uid, {"101": -3}))
        self.assertTrue(self.store.change_gems(self.uid, {"101": -2}))
        self.assertEqual(self.store.gems(self.uid), {})


class GemPlacementTests(GemCase):
    def test_gems_are_placed_by_slot_and_come_back_in_the_grid(self):
        self.stock({PLAIN_FIRE: 1, DEFENCE: 2})
        body = self.place(s0=PLAIN_FIRE, s1=DEFENCE, s2=DEFENCE)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["gem_pos"]["0"], [PLAIN_FIRE, DEFENCE, DEFENCE, "0"])
        self.assertEqual(self.call("cards.open")["data"]["gem_pos"]["0"],
                         [PLAIN_FIRE, DEFENCE, DEFENCE, "0"])

    def test_a_gem_in_the_wrong_slot_or_beyond_the_stack_is_refused(self):
        self.stock({PLAIN_FIRE: 1, DEFENCE: 1})
        self.assertEqual(self.place(s1=PLAIN_FIRE)["status"], "error_param")   # attack gem
        self.assertEqual(self.place(s0=DEFENCE)["status"], "error_param")       # defence gem
        self.assertEqual(self.place(s1=DEFENCE, s2=DEFENCE)["status"], "error_param")
        self.assertEqual(self.place(s0="999")["status"], "error_param")          # unknown
        self.assertEqual(self.store.gem_positions(self.uid), [])

    def test_a_request_without_gem_fields_keeps_the_grid(self):
        self.stock({PLAIN_FIRE: 1})
        self.place(s0=PLAIN_FIRE)
        attack = [self.card_id(c) for c in (5300, 100, 200)] + ["-1", "-1"]
        body = self.call("cards.set_alignment", form={
            "align_1": "_".join(attack), "align_2": "-1_-1_-1", "formation": "1"})
        self.assertEqual(body["data"]["gem_pos"]["0"][0], PLAIN_FIRE)


class GemSynthesisTests(GemCase):
    def test_synthesis_spends_materials_metal_and_items(self):
        self.stock({PLAIN_FIRE: 7}, metal=1000, items={303: 3})
        body = self.call("gem.synthesis", gem_id=SYNTH_FIRE, gem_num="2")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(self.store.gems(self.uid), {PLAIN_FIRE: 1, SYNTH_FIRE: 2})
        self.assertEqual(body["data"]["reward"], {"gem": [SYNTH_FIRE, SYNTH_FIRE]})
        self.assertEqual(body["user_status"]["metal"], 800)
        self.assertEqual(self.item(303), 1)
        update = body["data"]["_client_cache_update"]["gem"]["_gem"]
        self.assertEqual(update["update"], {PLAIN_FIRE: 1, SYNTH_FIRE: 2})

    def test_evolved_copies_of_the_material_count_after_the_plain_ones(self):
        self.stock({PLAIN_FIRE: 1, "1-101": 3}, metal=100, items={303: 1})
        body = self.call("gem.synthesis", gem_id=SYNTH_FIRE, gem_num="1")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(self.store.gems(self.uid), {"1-101": 1, SYNTH_FIRE: 1})
        self.assertEqual(body["data"]["_client_cache_update"]["gem"]["_gem"]["remove"],
                         [PLAIN_FIRE])

    def test_a_shortage_changes_nothing(self):
        self.stock({PLAIN_FIRE: 2}, metal=1000, items={303: 1})       # one gem short
        self.assertEqual(self.call("gem.synthesis", gem_id=SYNTH_FIRE)["status"],
                         "error_not_enough")
        self.store.change_gems(self.uid, {PLAIN_FIRE: 1})              # gems now, item gone
        self.store.change_items(self.uid, {303: -1})
        self.assertEqual(self.call("gem.synthesis", gem_id=SYNTH_FIRE)["status"],
                         "error_not_enough")
        self.assertEqual(self.store.gems(self.uid), {PLAIN_FIRE: 3})
        self.assertEqual(self.store.wallet(self.uid).get("metal"), 1000)

    def test_a_base_gem_and_unknown_gem_cannot_be_synthesised(self):
        self.stock({PLAIN_FIRE: 9}, metal=1000, items={303: 9})
        for gem_id in (PLAIN_FIRE, "999", "abc"):
            self.assertEqual(self.call("gem.synthesis", gem_id=gem_id)["status"], "error_param")

    def test_placed_gems_are_not_spent(self):
        self.stock({PLAIN_FIRE: 3}, metal=100, items={303: 1})
        self.place(s0=PLAIN_FIRE)
        self.assertEqual(self.call("gem.synthesis", gem_id=SYNTH_FIRE)["status"],
                         "error_not_enough")


class GemResolveTests(GemCase):
    def test_resolving_pays_one_draw_per_gem_in_metalcore(self):
        self.stock({PLAIN_FIRE: 3, "1-101": 1})
        with mock.patch.object(gem_actions.random, "randrange", side_effect=[8, 9, 10, 11]):
            body = self.call("gem.resolve", gems=["101_3", "1-101_1"])
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["reward"], {"metalcore": 38})
        self.assertEqual(body["user_status"]["metalcore"], 38)
        self.assertEqual(self.store.gems(self.uid), {})
        self.assertEqual(sorted(body["data"]["_client_cache_update"]["gem"]["_gem"]["remove"]),
                         ["1-101", "101"])

    def test_resolving_more_than_owned_unknown_or_placed_gems_is_refused(self):
        self.stock({PLAIN_FIRE: 2})
        self.assertEqual(self.call("gem.resolve", gems="101_3")["status"], "error_param")
        self.assertEqual(self.call("gem.resolve", gems="999_1")["status"], "error_param")
        self.assertEqual(self.call("gem.resolve")["status"], "error_param")
        self.place(s0=PLAIN_FIRE)
        self.assertEqual(self.call("gem.resolve", gems="101_2")["status"], "error_param")
        self.assertEqual(self.store.gems(self.uid), {PLAIN_FIRE: 2})


class GemEvolutionTests(GemCase):
    def test_a_successful_evolution_moves_one_gem_up_a_level(self):
        self.stock({PLAIN_FIRE: 2}, metal=1000, items={304: 5})
        body = self.call("gem.evolution", gem_id=PLAIN_FIRE, super_evo="0")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual((body["data"]["success"], body["data"]["got_gem"]), ("true", "1-101"))
        self.assertEqual(self.store.gems(self.uid), {PLAIN_FIRE: 1, "1-101": 1})
        self.assertEqual(body["user_status"]["metal"], 0)
        self.assertEqual(self.item(304), 0)

    def test_a_failure_that_keeps_the_level_refunds_part_of_the_material(self):
        self.stock({"1-101": 1}, metal=1000, items={304: 8})
        with mock.patch.object(gem_actions.random, "randrange", return_value=99):
            body = self.call("gem.evolution", gem_id="1-101", super_evo="0")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual((body["data"]["success"], body["data"]["got_gem"]), ("false", "1-101"))
        self.assertEqual(self.store.gems(self.uid), {"1-101": 1})
        self.assertEqual(self.item(304), 6)      # 8 - 8 + 6
        self.assertEqual(self.store.wallet(self.uid).get("metal", 0), 0)

    def test_a_failure_can_cost_a_level(self):
        self.stock({"2-101": 1}, metal=2000, items={304: 10})   # 2 -> 3 falls back to 1
        with mock.patch.object(gem_actions.random, "randrange", return_value=99):
            body = self.call("gem.evolution", gem_id="2-101")
        self.assertEqual((body["data"]["success"], body["data"]["got_gem"]), ("false", "1-101"))
        self.assertEqual(self.store.gems(self.uid), {"1-101": 1})

    def test_the_super_attempt_costs_the_multiple_and_cannot_fail(self):
        self.stock({"1-101": 1}, metal=2000, items={304: 16})
        with mock.patch.object(gem_actions.random, "randrange", return_value=99):
            body = self.call("gem.evolution", gem_id="1-101", super_evo="1")
        self.assertEqual((body["data"]["success"], body["data"]["got_gem"]), ("true", "2-101"))
        self.assertEqual(self.item(304), 0)
        self.assertEqual(self.store.wallet(self.uid).get("metal", 0), 0)

    def test_a_full_unknown_poor_or_placed_gem_is_refused(self):
        self.stock({"3-101": 1, PLAIN_FIRE: 1}, metal=500, items={304: 5})
        self.assertEqual(self.call("gem.evolution", gem_id="3-101")["status"], "error_param")
        self.assertEqual(self.call("gem.evolution", gem_id="999")["status"], "error_param")
        self.assertEqual(self.call("gem.evolution", gem_id=PLAIN_FIRE)["status"],
                         "error_not_enough")            # metal short
        self.assertEqual(self.store.gems(self.uid), {"3-101": 1, PLAIN_FIRE: 1})
        self.store.change_wallet(self.uid, {"metal": 500})
        self.place(s0=PLAIN_FIRE)
        self.assertEqual(self.call("gem.evolution", gem_id=PLAIN_FIRE)["status"], "error_param")

    def test_gem_upgrade_is_not_served(self):
        self.stock({PLAIN_FIRE: 2})
        self.assertEqual(self.call("gem.upgrade", gem_id=PLAIN_FIRE, element_id="101")["status"],
                         "error_not_open")


class GemStatTests(GemCase):
    def configs(self):
        return self.server.services.configs

    def test_stats_follow_value_plus_the_evolution_bonus(self):
        self.assertEqual(gems.key_stats(self.configs(), PLAIN_FIRE), {"fire": 1250})
        self.assertEqual(gems.key_stats(self.configs(), "1-101"), {"fire": 1300})
        # defence gem: ability 301 and a second ability (5 = hp) with its own bonus
        self.assertEqual(gems.key_stats(self.configs(), "2-111"),
                         {"fire_dfs": 870, "hp": 600})

    def test_a_positions_gems_add_up(self):
        total = gems.bonus(self.configs(), [PLAIN_FIRE, DEFENCE, "0", DEFENCE])
        self.assertEqual((total["fire"], total["fire_dfs"], total["hp"]), (1250, 1600, 1000))

    def test_placed_gems_enter_combat_power_and_the_battle_unit(self):
        before = self.call("user.main_page")["data"]["combat"]
        self.stock({PLAIN_FIRE: 1})
        self.place(s0=PLAIN_FIRE)
        # elemental stats count at face value in the combat power
        self.assertEqual(self.call("user.main_page")["data"]["combat"] - before, 1250)
        units = campaign._attackers(self.server.services, self.uid, 1)
        self.assertEqual(units[0]["elements"]["fire"], 1250)
