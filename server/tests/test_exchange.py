"""Hero and equipment exchange: item.view and item.exchange (views 21 and 26)."""

from tests.test_gameplay import PlayerCase

SHARD = 1001
EQUIP_SHARD = 1002
HERO = 3800
EQUIP = 10101


class ExchangeCase(PlayerCase):
    def extra_configs(self):
        return {
            "item": {
                str(SHARD): {"name": "mảnh tướng", "stack": 10},
                str(EQUIP_SHARD): {"name": "mảnh trang bị", "stack": 10},
            },
            "exchange": {
                # Hero row: 5 shards + 100 food, at most twice.
                "1": {"change_id": [[5, HERO, 1]], "change_sort": 1, "change_time": 2,
                      "need_item": SHARD, "need_num": [5], "need_food": 100,
                      "need_metal": 0, "refesh": 1},
                # Equipment row: 3 shards + 200 metal, unlimited.
                "2": {"change_id": [[7, EQUIP, 1]], "change_sort": 2, "change_time": 9999,
                      "need_item": EQUIP_SHARD, "need_num": [3], "need_food": 0,
                      "need_metal": 200, "refesh": 1},
                # Pet / talisman rows are outside this server.
                "3": {"change_id": [[6, 1, 1]], "change_sort": 3, "change_time": 9999,
                      "need_item": SHARD, "need_num": [1], "need_food": 0,
                      "need_metal": 0, "refesh": 1},
            },
        }

    def setUp(self):
        super().setUp()
        self.store = self.server.services.store

    def give(self, amounts, food=10000, metal=1000):
        self.store.change_items(self.uid, amounts)
        current = self.store.wallet(self.uid)
        self.store.change_wallet(self.uid, {
            "food": food - current.get("food", 0),
            "metal": metal - current.get("metal", 0),
        })

    def view(self):
        return self.call("item.view")["data"]

    def test_item_view_sends_the_bag_and_an_exchange_log_even_when_empty(self):
        self.give({SHARD: 12, EQUIP_SHARD: 7})
        data = self.view()
        self.assertEqual(data["items"][str(SHARD)], [10, 2])
        self.assertEqual(data["items"][str(EQUIP_SHARD)], [7])
        self.assertEqual(data["exchange_log"], {})

    def test_a_hero_exchange_spends_shards_and_food_and_adds_the_hero(self):
        self.give({SHARD: 12})
        before = len(self.store.cards_for_player(self.uid))
        body = self.call("item.exchange", change_id="1")
        self.assertEqual(body["status"], 0, body)
        data = body["data"]
        self.assertEqual(data["exchange_log"], {"1": 1})
        self.assertEqual(data["items"][str(SHARD)], [7])
        self.assertEqual(self.store.items(self.uid)[SHARD], 7)
        self.assertEqual(self.store.wallet(self.uid)["food"], 9900)
        self.assertEqual(len(self.store.cards_for_player(self.uid)), before + 1)
        new = [c for c in data["_client_cache_update"]["cards"]["cards"]["update"].values()
               if c["c_id"] == HERO]
        self.assertEqual(len(new), 1)
        self.assertEqual(data["_client_cache_update"]["item"]["items"]["update"],
                         {str(SHARD): [7]})

    def test_an_equipment_exchange_spends_metal_and_adds_the_equipment(self):
        self.give({EQUIP_SHARD: 6})
        before = len(self.store.equipment_rows(self.uid))
        body = self.call("item.exchange", change_id="2")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(self.store.items(self.uid)[EQUIP_SHARD], 3)
        self.assertEqual(self.store.wallet(self.uid)["metal"], 800)
        equips = self.store.equipment_rows(self.uid)
        self.assertEqual(len(equips), before + 1)
        self.assertEqual(equips[-1]["c_id"], EQUIP)
        self.assertEqual(body["data"]["exchange_log"], {"2": 1})

    def test_the_second_exchange_uses_the_log_as_the_need_num_index(self):
        self.give({SHARD: 12})
        self.call("item.exchange", change_id="1")
        # `need_num` has one entry, so the cost stays 5; the log still advances.
        body = self.call("item.exchange", change_id="1")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["exchange_log"], {"1": 2})

    def test_a_row_stops_at_change_time(self):
        self.give({SHARD: 12})
        self.call("item.exchange", change_id="1")
        self.call("item.exchange", change_id="1")
        body = self.call("item.exchange", change_id="1")
        self.assertEqual(body["status"], "error_limit")
        self.assertEqual(self.store.items(self.uid)[SHARD], 2)

    def test_unserved_sorts_answer_feature_closed(self):
        self.give({SHARD: 5})
        self.assertEqual(self.call("item.exchange", change_id="3")["status"],
                         "error_not_open")
        self.assertEqual(self.store.items(self.uid)[SHARD], 5)

    def test_short_shards_change_nothing(self):
        self.give({SHARD: 4})
        body = self.call("item.exchange", change_id="1")
        self.assertEqual(body["status"], "error_item")
        self.assertEqual(self.store.items(self.uid)[SHARD], 4)
        self.assertEqual(self.store.wallet(self.uid)["food"], 10000)

    def test_short_currency_changes_nothing(self):
        self.give({SHARD: 5}, food=0)
        body = self.call("item.exchange", change_id="1")
        self.assertEqual(body["status"], "error_not_enough")
        self.assertEqual(self.store.items(self.uid)[SHARD], 5)

    def test_an_unknown_row_is_refused(self):
        self.assertEqual(self.call("item.exchange", change_id="999")["status"], "error_param")
        self.assertEqual(self.call("item.exchange", change_id="x")["status"], "error_param")
