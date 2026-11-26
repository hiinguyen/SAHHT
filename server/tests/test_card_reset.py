"""Hero breakthrough ("Chuyển sinh", cards.card_break) and rebirth ("Tái sinh", cards.card_rebirth)."""

from tests.test_gameplay import PlayerCase

HERO = 3800
STONE = 900000


class CardResetCase(PlayerCase):
    def extra_configs(self):
        return {
            "character_break_new": {str(HERO): {
                "high_break": 2,
                "material1": [[6, STONE, 5]],
                "material2": [[6, STONE, 10], [5, HERO, 1]],
            }},
            "break_control": {"1": {"hp_add": 0.5, "need_level": 3},
                              "2": {"hp_add": 1.0, "need_level": 6}},
            "evolution": {str(step): {"step": step, "exp": 10, "need_level": 1, "player_level": 0,
                                      "skill": [1, 0, 0], "type0": [0, 0, 0, 0, 0]}
                          for step in range(6)},
        }

    def setUp(self):
        super().setUp()
        self.store = self.server.services.store
        self.hero = self.store.add_cards(self.uid, [HERO])[0]

    def level(self, card_id, lv, step=0):
        self.store.update_card(self.uid, card_id, lv=lv, exp=0, step=step)

    def stock(self, count):
        self.store.change_items(self.uid, {STONE: count})

    def doc(self, card_id=None):
        return self.call("cards.open")["data"]["cards"][card_id or self.hero]

    def spare_hero(self):
        return self.store.add_cards(self.uid, [HERO])[0]


class BreakthroughTests(CardResetCase):
    def test_a_breakthrough_spends_the_stones_and_raises_bre(self):
        self.level(self.hero, 3)
        self.stock(7)
        body = self.call("cards.card_break", card_id=self.hero)
        self.assertEqual(body["status"], 0, body)
        cache = body["data"]["_client_cache_update"]
        self.assertEqual(cache["cards"]["cards"]["update"][self.hero]["bre"], 1)
        self.assertEqual(cache["item"]["items"]["update"], {str(STONE): [2]})
        self.assertEqual(self.store.items(self.uid)[STONE], 2)
        self.assertEqual(self.doc()["bre"], 1)

    def test_bre_raises_the_hp_by_the_break_control_share_of_the_base(self):
        self.level(self.hero, 3)
        before = self.doc()
        self.stock(5)
        self.call("cards.card_break", card_id=self.hero)
        after = self.doc()
        self.assertEqual(after["hp"], int(before["hp"] * 1.5))
        self.assertEqual(after["patk"], before["patk"])

    def test_a_card_material_is_a_spare_copy_of_the_same_hero(self):
        self.level(self.hero, 6)
        self.stock(5)
        self.call("cards.card_break", card_id=self.hero)
        self.stock(10)
        spare = self.spare_hero()
        body = self.call("cards.card_break", card_id=self.hero)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["_client_cache_update"]["cards"]["cards"]["remove"], [spare])
        self.assertEqual(self.doc()["bre"], 2)

    def test_the_card_itself_and_a_locked_card_are_no_material(self):
        self.level(self.hero, 6)
        self.stock(5)
        self.call("cards.card_break", card_id=self.hero)
        self.stock(10)
        before = self.store.items(self.uid)
        self.assertEqual(self.call("cards.card_break", card_id=self.hero)["status"],
                         "error_not_enough")
        spare = self.spare_hero()
        self.store.set_card_locked(self.uid, spare, True)
        self.assertEqual(self.call("cards.card_break", card_id=self.hero)["status"],
                         "error_not_enough")
        self.assertEqual(self.store.items(self.uid), before)

    def test_a_short_material_changes_nothing(self):
        self.level(self.hero, 3)
        self.stock(4)
        body = self.call("cards.card_break", card_id=self.hero)
        self.assertEqual(body["status"], "error_not_enough")
        self.assertEqual(self.store.items(self.uid)[STONE], 4)
        self.assertEqual(self.doc()["bre"], 0)

    def test_a_low_level_card_is_refused(self):
        self.level(self.hero, 2)
        self.stock(5)
        self.assertEqual(self.call("cards.card_break", card_id=self.hero)["status"],
                         "error_level")
        self.assertEqual(self.store.items(self.uid)[STONE], 5)

    def test_the_top_break_is_refused(self):
        self.level(self.hero, 6)
        self.stock(5)
        self.call("cards.card_break", card_id=self.hero)
        self.stock(10)
        self.spare_hero()
        self.call("cards.card_break", card_id=self.hero)
        self.stock(100)
        self.spare_hero()
        self.assertEqual(self.call("cards.card_break", card_id=self.hero)["status"],
                         "error_max_evo")

    def test_an_unknown_or_unconfigured_card_is_refused(self):
        self.assertEqual(self.call("cards.card_break", card_id="99999")["status"], "error_param")
        plain = self.card_id(100)
        self.assertEqual(self.call("cards.card_break", card_id=plain)["status"], "error_param")


class RebirthTests(CardResetCase):
    def evolved(self, step=5, lv=4):
        self.level(self.hero, lv, step)
        self.store.set_card_skill(self.hero, 1, 3, 20)

    def test_a_rebirth_resets_level_evolution_and_skills(self):
        self.evolved()
        body = self.call("cards.card_rebirth", card_id=self.hero)
        self.assertEqual(body["status"], 0, body)
        card = body["data"]["_client_cache_update"]["cards"]["cards"]["update"][self.hero]
        self.assertEqual((card["lv"], card["exp"], card["step"], card["evo"]), (1, 0, 0, 0))
        self.assertEqual(card["s_1"]["lv"], 1)
        self.assertEqual(self.store.card(self.uid, self.hero)["skills"], {})

    def test_the_evolution_food_and_material_cards_come_back(self):
        self.evolved(step=5)
        food = self.store.wallet(self.uid)["food"]
        before = len(self.store.cards_for_player(self.uid))
        body = self.call("cards.card_rebirth", card_id=self.hero)
        # Five steps, each cost evo_food 400 and exp 10 // 10 = 1 material card.
        self.assertEqual(self.store.wallet(self.uid)["food"], food + 5 * 400)
        self.assertEqual(len(self.store.cards_for_player(self.uid)), before + 5)
        self.assertEqual(body["data"]["reward"]["food"], 2000)
        self.assertEqual(len(body["data"]["reward"]["cards"]), 5)
        update = body["data"]["_client_cache_update"]["cards"]["cards"]["update"]
        self.assertEqual({update[i]["c_id"] for i in body["data"]["reward"]["cards"]}, {HERO})

    def test_the_break_level_survives(self):
        self.evolved()
        self.store.set_card_break(self.uid, self.hero, 2)
        self.call("cards.card_rebirth", card_id=self.hero)
        self.assertEqual(self.doc()["bre"], 2)

    def test_below_four_evolutions_is_refused(self):
        self.evolved(step=3)
        self.assertEqual(self.call("cards.card_rebirth", card_id=self.hero)["status"],
                         "error_param")
        self.assertEqual(self.store.card(self.uid, self.hero)["step"], 3)

    def test_a_team_or_locked_card_is_refused(self):
        self.evolved()
        self.store.set_card_locked(self.uid, self.hero, True)
        self.assertEqual(self.call("cards.card_rebirth", card_id=self.hero)["status"],
                         "error_param")
        self.store.set_card_locked(self.uid, self.hero, False)
        self.assertTrue(self.store.set_alignment(self.uid, [int(self.hero)], []))
        self.assertEqual(self.call("cards.card_rebirth", card_id=self.hero)["status"],
                         "error_param")

    def test_an_unknown_card_is_refused(self):
        self.assertEqual(self.call("cards.card_rebirth", card_id="99999")["status"], "error_param")
