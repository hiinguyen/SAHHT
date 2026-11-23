"""The 2018 scope file: structure checks, queries, and the real file against the client."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from sahht_server.scope import DEFAULT_PATH, UNCLASSIFIED, Scope, ScopeError
from sahht_server.skills import LAST_HERO_ID
from tools import audit_scope

VALID = {
    "card_id_max": 38700,
    "city_order_max": 3,
    "modules": {
        "cards": {"phase": 0, "open": True},
        "arena": {"phase": 6, "open": False},
        "god_field": {"phase": None, "open": False, "reason": "liên server"},
    },
    "quiet": {"notify.poll": {"body": {"list": []}, "evidence": "lua/game_ui/x.lua:10"}},
    "views": {
        "37": {"module": "arena"},
        "38": {"module": "cards"},
        "10": {"open": False, "reason": "nút sự kiện"},
        "11": {"open": True, "reason": "nút giao diện"},
    },
}


def with_change(change):
    raw = copy.deepcopy(VALID)
    change(raw)
    return raw


class ScopeQueryTests(unittest.TestCase):
    def setUp(self):
        self.scope = Scope.from_dict(VALID)

    def test_heroes_up_to_the_cutoff_are_in_scope(self):
        self.assertTrue(self.scope.card_in_scope(38700))
        self.assertTrue(self.scope.card_in_scope("100"))
        self.assertFalse(self.scope.card_in_scope(38800))

    def test_cities_up_to_the_cutoff_order_are_in_scope(self):
        self.assertTrue(self.scope.city_order_in_scope("3"))
        self.assertFalse(self.scope.city_order_in_scope(4))
        unlimited = Scope.from_dict(with_change(lambda r: r.update(city_order_max=None)))
        self.assertTrue(unlimited.city_order_in_scope(160))

    def test_closed_views_follow_their_module_or_their_own_flag(self):
        self.assertEqual(self.scope.closed_views(), [10, 37])

    def test_quiet_body_is_a_copy(self):
        body = self.scope.quiet_body("notify.poll")
        body["list"].append(1)
        self.assertEqual(self.scope.quiet_body("notify.poll"), {"list": []})
        self.assertIsNone(self.scope.quiet_body("arena.index"))

    def test_module_open(self):
        self.assertTrue(self.scope.module_open("cards"))
        self.assertFalse(self.scope.module_open("arena"))
        self.assertFalse(self.scope.module_open("no_such_module"))

    def test_load_reads_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scope.json"
            path.write_text(json.dumps(VALID), encoding="utf-8")
            self.assertEqual(Scope.load(path).closed_views(), [10, 37])


class ScopeValidationTests(unittest.TestCase):
    def assertRejected(self, change):
        with self.assertRaises(ScopeError):
            Scope.from_dict(with_change(change))

    def test_out_of_scope_module_cannot_be_open(self):
        self.assertRejected(lambda r: r["modules"]["god_field"].update(open=True))

    def test_module_needs_phase_and_open(self):
        self.assertRejected(lambda r: r["modules"]["arena"].pop("open"))
        self.assertRejected(lambda r: r["modules"]["arena"].update(phase="6"))

    def test_quiet_needs_body_and_evidence(self):
        self.assertRejected(lambda r: r["quiet"]["notify.poll"].pop("evidence"))
        self.assertRejected(lambda r: r["quiet"]["notify.poll"].update(body=[]))

    def test_view_needs_exactly_one_of_module_and_open(self):
        self.assertRejected(lambda r: r["views"]["37"].update(open=True))
        self.assertRejected(lambda r: r["views"].update({"39": {}}))

    def test_view_module_must_exist(self):
        self.assertRejected(lambda r: r["views"].update({"39": {"module": "nowhere"}}))

    def test_explicit_view_needs_a_reason(self):
        self.assertRejected(lambda r: r["views"]["10"].pop("reason"))

    def test_view_ids_are_numbers(self):
        self.assertRejected(lambda r: r["views"].update({"x": {"module": "cards"}}))

    def test_cutoffs_are_integers(self):
        self.assertRejected(lambda r: r.update(card_id_max="38700"))
        self.assertRejected(lambda r: r.update(card_id_max=True))
        self.assertRejected(lambda r: r.update(city_order_max=1.5))

    def test_missing_or_broken_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ScopeError):
                Scope.load(Path(tmp) / "missing.json")
            broken = Path(tmp) / "broken.json"
            broken.write_text("{", encoding="utf-8")
            with self.assertRaises(ScopeError):
                Scope.load(broken)


class ScopeFileTests(unittest.TestCase):
    """The real data/scope_2018.json against the real client."""

    @classmethod
    def setUpClass(cls):
        cls.scope = Scope.load(DEFAULT_PATH)
        cls.raw = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        cls.modules = audit_scope.api_modules(audit_scope.url_keys())

    def test_every_client_module_is_classified(self):
        self.assertEqual(sorted(set(self.modules) - set(self.scope.modules)), [])

    def test_every_view_id_is_classified(self):
        self.assertEqual(sorted(audit_scope.client_views() - set(self.scope.views)), [])

    def test_a_view_said_to_be_unused_is_not_referenced_by_the_client(self):
        refs = audit_scope.view_refs()
        stale = [view for view, entry in self.scope.views.items()
                 if entry.get("reason") == audit_scope.UNUSED_REASON and view in refs]
        self.assertEqual(stale, [])

    def test_nothing_is_left_unreviewed(self):
        entries = [*self.raw["modules"].items(), *self.raw["views"].items(), *self.raw["quiet"].items()]
        left = [key for key, entry in entries if UNCLASSIFIED in json.dumps(entry, ensure_ascii=False)]
        self.assertEqual(left, [])

    def test_every_module_with_a_handler_is_open(self):
        from sahht_server.app import SESSION_HANDLERS
        handled = {method.split(".", 1)[0] for service, method in SESSION_HANDLERS if service == "api"}
        self.assertEqual(sorted(m for m in handled if not self.scope.module_open(m)), [])

    def test_hero_cut_matches_the_skill_specs(self):
        self.assertEqual(self.scope.card_id_max, LAST_HERO_ID)


class RewardReachTests(unittest.TestCase):
    """No reward the server hands out can lead to a hero past the cut, through any boxes."""

    def test_no_reward_source_reaches_a_hero_after_2018(self):
        config = audit_scope.load_config
        cards = audit_scope.reachable_cards(audit_scope.server_reward_sources(config),
                                            config("item"), config("box"))
        scope = Scope.load(DEFAULT_PATH)
        self.assertTrue(cards, "the walk found no heroes at all: the config paths are wrong")
        self.assertEqual(sorted(c for c in cards if not scope.card_in_scope(c)), [])

    def test_the_walk_follows_boxes_inside_boxes(self):
        items = {"1": {"is_use": 1, "use_effect": [10]}, "2": {"is_use": 1, "use_effect": [20]}}
        boxes = {"10": [{"num": 1, "reward": [[6, 2, 1, 5]]}],
                 "20": [{"num": 1, "reward": [[5, 38800, 1, 5]]}]}
        self.assertEqual(audit_scope.reachable_cards([[6, 1, 1]], items, boxes), {38800})


if __name__ == "__main__":
    unittest.main()


class ViewRefTests(unittest.TestCase):
    def test_menu_tables_and_review_keys_count_as_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "menu.lua").write_text(
                '{name="Shop",btnId = 402, InReviewId = 30,openFlag = true},\n'
                'if game_data:isViewOpenByID( 49 ) then\n'
                'x = m.in_review_801\n'
                '-- {name="old",btnId = 1, InReviewId = 999},\n', encoding="utf-8")
            self.assertEqual(sorted(audit_scope.view_refs(tmp)), [30, 49, 801])
