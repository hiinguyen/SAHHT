"""The game-master tool: account creation and free grants against a throw-away database."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from sahht_server.store import Store
from sahht_server import gm
from tools import admin


class AdminToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "gm.db")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            admin.main(["--db", self.db, *argv])
        return out.getvalue()

    def player(self):
        store = Store(self.db)
        try:
            player = store.player_for_account("gm")
            return (player["level"], store.wallet(player["uid"]), store.items(player["uid"]),
                    [c["c_id"] for c in store.cards_for_player(player["uid"])])
        finally:
            store.close()

    def test_a_gm_account_has_a_high_level_and_a_full_wallet(self):
        self.run_tool("account", "gm", "gm123456")
        level, wallet, _, cards = self.player()
        self.assertEqual(level, gm.GM_LEVEL)
        self.assertGreater(wallet["coin"], 10**8)
        self.assertEqual(len(cards), 3)   # the starter heroes

    def test_give_adds_the_chosen_heroes_and_items(self):
        self.run_tool("account", "gm", "gm123456")
        before = self.player()[2].get(1018, 0)
        self.run_tool("give", "gm", "--card", "6500", "--card", "7900:2", "--item", "1018:9",
                      "--cur", "silver=5")
        _, wallet, items, cards = self.player()
        self.assertEqual((cards.count(6500), cards.count(7900), items[1018] - before), (1, 2, 9))
        self.assertGreaterEqual(wallet["silver"], 5)

    def test_heroes_after_the_2018_cut_need_the_flag(self):
        self.run_tool("account", "gm", "gm123456")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_tool("give", "gm", "--card", "38800")
        self.run_tool("give", "gm", "--card", "38800", "--allow-late")
        self.assertIn(38800, self.player()[3])

    def test_unknown_ids_and_accounts_are_refused(self):
        self.run_tool("account", "gm", "gm123456")
        for argv in (("give", "gm", "--item", "999999999"), ("give", "nobody", "--coin", "1")):
            with self.assertRaises(SystemExit):
                self.run_tool(*argv)


if __name__ == "__main__":
    unittest.main()
