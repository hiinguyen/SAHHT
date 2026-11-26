"""Using bag items: chests that need a key, optional exchanges, crystals, bag expansion."""

import unittest

from sahht_server import equipment
from sahht_server.handlers import Refused
from sahht_server.rewards import Loot, grant
from tests.test_flow import FIXTURE_CONFIGS
from tests.test_gameplay import PlayerCase

ITEMS = {
    "7": {"name": "chest", "stack": 9999, "is_use": 1, "use_effect": [8, 10], "use_num": 1},
    "10": {"name": "key", "stack": 9999, "is_use": 1, "use_effect": [8, 7], "use_num": 1},
    "500": {"name": "crystals", "stack": 9999, "is_use": 4, "use_effect": [100], "use_num": 1},
    "5001": {"name": "equip bag", "stack": 9999, "is_use": 8, "use_effect": [5], "use_num": 1},
    "4001": {"name": "card bag", "stack": 9999, "is_use": 7, "use_effect": [5], "use_num": 1},
    "202": {"name": "pick", "stack": 9999, "is_use": 15, "use_effect": [202], "use_num": 3},
    "203": {"name": "pick two", "stack": 9999, "is_use": 15, "use_effect": [203], "use_num": 1},
    "9100928": {"name": "title", "stack": 9999, "is_use": 17, "use_effect": [1], "use_num": 1},
}
BOXES = {
    "8": [{"num": 1, "reward": [[9, 0, 250, 1]]}],
    "202": [{"num": 1, "reward": [[9, 0, 100], [1, 0, 500], [2, 0, 700]]}],
    "203": [{"num": 1, "reward": [[9, 0, 10], [9, 0, 20]]},
            {"num": 2, "reward": [[1, 0, 1], [1, 0, 2], [1, 0, 4]]}],
}


class ItemUseCase(PlayerCase):
    def extra_configs(self):
        return {"item": FIXTURE_CONFIGS["item"] | ITEMS, "box": FIXTURE_CONFIGS["box"] | BOXES}

    def give(self, **items):
        self.server.services.store.change_items(
            self.uid, {int(key.removeprefix("i")): n for key, n in items.items()})

    def use(self, item_id, num="1", **lists):
        return self.call("item.use", item_id=item_id, num=num, **lists)

    def owned(self, item_id):
        return self.server.services.store.items(self.uid).get(item_id, 0)


class ChestAndKeyTests(ItemUseCase):
    def test_chest_needs_its_key_and_spends_both(self):
        self.give(i7=2)
        self.assertEqual(self.use("7")["status"], "error_item")
        self.give(i10=1)
        body = self.use("7")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["user_status"]["coin"], 1000 + 250)
        self.assertEqual((self.owned(7), self.owned(10)), (1, 0))

    def test_key_alone_opens_nothing(self):
        self.give(i10=1)
        self.assertEqual(self.use("10")["status"], "error_item")


class CrystalAndBagTests(ItemUseCase):
    def test_crystal_pack_adds_crystals(self):
        self.give(i500=2)
        self.assertEqual(self.use("500", "2")["user_status"]["crystal"], 200)

    def test_bag_expansion_raises_the_limits_the_client_shows(self):
        self.give(i5001=2, i4001=1)
        self.assertEqual(self.use("5001", "2")["user_status"]["equip_max"],
                         equipment.EQUIP_MAX + 10)
        self.assertEqual(self.use("4001")["user_status"]["card_max"], 205)
        self.assertEqual(self.call("cards.open")["user_status"]["equip_max"],
                         equipment.EQUIP_MAX + 10)

    def test_expanded_equipment_bag_takes_more_pieces(self):
        svc = self.server.services
        missing = equipment.EQUIP_MAX - svc.store.equipment_count(self.uid)
        svc.store.add_equipment(self.uid, [10101] * missing)
        with self.assertRaises(Refused):
            grant(svc, self.uid, Loot(equips=[10101]), 0)
        self.give(i5001=1)
        self.use("5001")
        grant(svc, self.uid, Loot(equips=[10101] * 5), 0)
        self.assertEqual(svc.store.equipment_count(self.uid), equipment.EQUIP_MAX + 5)


class OptionalExchangeTests(ItemUseCase):
    def test_exchange_spends_use_num_and_grants_the_chosen_reward(self):
        self.give(i202=7)
        body = self.use("202", type_list=["2"])
        self.assertEqual(body["user_status"]["food"], 10000 + 500)
        self.assertEqual(self.owned(202), 4)

    def test_exchange_refuses_a_bad_choice_or_missing_stack(self):
        self.give(i202=2)
        self.assertEqual(self.use("202", type_list=["1"])["status"], "error_item")
        self.give(i202=5)
        for lists in ({}, {"type_list": ["9"]}, {"type_list": ["1", "2"]}):
            self.assertEqual(self.use("202", **lists)["status"], "error_param")
        self.assertEqual(self.owned(202), 7)

    def test_two_pick_groups_grant_both_choices(self):
        self.give(i203=1)
        body = self.use("203", type_list=["2"], type_list_1=["1", "3"])
        self.assertEqual(body["user_status"]["coin"], 1000 + 20)
        self.assertEqual(body["user_status"]["food"], 10000 + 1 + 4)

    def test_batch_use_multiplies_the_exchange(self):
        self.give(i202=6)
        body = self.use("202", "2", type_list=["1"])
        self.assertEqual(body["user_status"]["coin"], 1000 + 200)
        self.assertEqual(self.owned(202), 0)


class UnservedKindsTests(ItemUseCase):
    def test_titles_have_no_system_yet(self):
        self.give(i9100928=1)
        self.assertEqual(self.use("9100928")["status"], "error_item")


if __name__ == "__main__":
    unittest.main()
