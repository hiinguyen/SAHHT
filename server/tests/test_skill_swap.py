"""5-skill heroes: the three-slot battle skill choice (cards.select/set_battle_skill)."""

import unittest

from sahht_server import campaign
from sahht_server.handlers import ConfigCache
from sahht_server.progression import ACTIVE, LOCKED, UNLOCKED, Rules
from tests.test_flow import FIXTURE_CONFIGS, ServerCase, _character
from tests.test_gameplay import PlayerCase

HERO = 3900


class SkillSwapConfigs:
    """The fixture plus a five-skill hero (its own skill_detail rows)."""

    def extra_configs(self):
        character = dict(_character(HERO), skill_num=5, skill_5_source=[[HERO + 50, 1]])
        details = {**FIXTURE_CONFIGS["skill_detail"]}
        for slot in (10, 20, 30, 40, 50):
            details[str(HERO + slot)] = {"skill_quality": 0, "max_lv": 3}
        return {"character_detail": {**FIXTURE_CONFIGS["character_detail"],
                                     str(HERO): character},
                "skill_detail": details}


class SkillSwapTests(SkillSwapConfigs, PlayerCase):
    def setUp(self):
        super().setUp()
        self.store = self.server.services.store
        self.hero_card = self.store.add_cards(self.uid, [HERO])[0]
        self.store.update_card(self.uid, self.hero_card, lv=1, exp=0, step=3)
        self.doc = self.call("cards.open")["data"]["cards"][self.hero_card]

    def skills(self):
        return self.call("cards.open")["data"]["cards"][self.hero_card]

    def set_skills(self, value, card=None):
        return self.call("cards.set_battle_skill", card_id=card or self.hero_card,
                         skill_ids=value)

    def test_a_five_skill_hero_shows_all_five_slots(self):
        self.assertEqual([self.doc[f"s_{i}"]["s"] for i in range(1, 6)],
                         [HERO + 10, HERO + 20, HERO + 30, HERO + 40, HERO + 50])
        # The first three are the default battle set; slots 4-5 are unlocked but benched.
        self.assertEqual([self.doc[f"s_{i}"]["avail"] for i in range(1, 6)],
                         [ACTIVE, ACTIVE, ACTIVE, UNLOCKED, UNLOCKED])

    def test_select_skill_index_returns_the_five_skill_documents(self):
        body = self.call("cards.select_skill_index", card_id=self.hero_card)
        self.assertEqual(body["status"], 0, body)
        self.assertEqual([entry["s"] for entry in body["data"]["skill"]],
                         [HERO + 10, HERO + 20, HERO + 30, HERO + 40, HERO + 50])

    def test_choosing_three_slots_moves_the_active_flag(self):
        # The client always leaves one trailing underscore.
        body = self.set_skills("1_4_5_")
        self.assertEqual(body["status"], 0, body)
        skills = self.skills()
        self.assertEqual([skills[f"s_{i}"]["avail"] for i in range(1, 6)],
                         [ACTIVE, UNLOCKED, UNLOCKED, ACTIVE, ACTIVE])

    def test_the_choice_survives_a_reopen(self):
        self.set_skills("2_3_4")
        store = self.store
        self.assertEqual(store.cards_for_player(self.uid)[-1]["battle_slots"], [2, 3, 4])

    def test_a_choice_needs_exactly_three_distinct_unlocked_slots(self):
        for value in ("1_2", "1_2_3_4", "1_1_2", "1_2_9", "1_2_x", ""):
            with self.subTest(value=value):
                self.assertEqual(self.set_skills(value)["status"], "error_param")

    def test_a_locked_slot_cannot_be_chosen(self):
        # Level 0 has no evolution, so only slot 1 is unlocked; 2 and 3 stay LOCKED.
        self.store.update_card(self.uid, self.hero_card, lv=1, exp=0, step=0)
        self.assertEqual(self.set_skills("1_2_3")["status"], "error_param")

    def test_another_players_card_is_refused(self):
        self.assertEqual(self.set_skills("1_2_3", card="999999")["status"], "error_param")

    def test_unlock_skill_answers_with_the_same_documents(self):
        body = self.call("cards.unlock_skill", card_id=self.hero_card, skill_id="4")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(len(body["data"]["skill"]), 5)

    def test_combat_power_counts_only_the_three_chosen_skills(self):
        rules = Rules.load(self.server.services.configs)
        before = self.call("user.main_page")["data"]["combat"]
        # Swapping to slots 2-4 keeps three active skills, so combat power is unchanged.
        self.set_skills("2_3_4")
        self.assertEqual(self.call("user.main_page")["data"]["combat"], before)


class BattleSkillSelectionTests(SkillSwapConfigs, ServerCase):
    def test_the_engine_runs_exactly_the_chosen_slots(self):
        rules = Rules.load(self.server.services.configs)
        character = rules.characters[str(HERO)]
        card = {"id": "1", "c_id": HERO, "lv": 1, "step": 3, "exp": 0,
                "skills": {}, "battle_slots": [1, 4, 5]}
        doc = rules.card_document(card, 1)

        class Book:
            @staticmethod
            def skill(skill_id, level):
                return skill_id

        self.assertEqual([slot for slot, _ in campaign._card_skills(Book(), doc)], [1, 4, 5])
        self.assertEqual([doc[f"s_{i}"]["avail"] for i in range(1, 6)],
                         [ACTIVE, UNLOCKED, UNLOCKED, ACTIVE, ACTIVE])
        # A default choice is the first three slots.
        default = rules.card_document({**card, "battle_slots": None}, 1)
        self.assertEqual([slot for slot, _ in campaign._card_skills(Book(), default)],
                         [1, 2, 3])


class ThreeSkillHeroTests(SkillSwapConfigs, ServerCase):
    def test_a_three_skill_hero_has_no_fourth_or_fifth_slot(self):
        rules = Rules.load(self.server.services.configs)
        doc = rules.card_document({"id": "1", "c_id": 5300, "lv": 1, "step": 3,
                                   "exp": 0, "skills": {}}, 1)
        self.assertNotIn("s_4", doc)
        self.assertNotIn("s_5", doc)


if __name__ == "__main__":
    unittest.main()
