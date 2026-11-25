"""Schema migrations and the payments table."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sahht_server.store import MIGRATIONS, Store


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "game.db")

    def tearDown(self):
        self.tmp.cleanup()

    def open_store(self):
        store = Store(self.path)
        self.addCleanup(store.close)
        return store

    def version(self):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()

    def test_new_database_gets_every_migration(self):
        self.open_store()
        self.assertEqual(self.version(), len(MIGRATIONS))
        db = sqlite3.connect(self.path)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        db.close()
        self.assertIn("payments", tables)

    def test_database_from_before_migrations_keeps_its_data(self):
        # Make a database the way the old server left it: schema 1 tables with data,
        # no payments table, user_version still 0.
        self.open_store().create_account("old_player", "secret12")
        db = sqlite3.connect(self.path)
        db.execute("DROP TABLE payments")
        db.execute("ALTER TABLE cards DROP COLUMN locked")   # schema before migration 3
        db.execute("ALTER TABLE equipment DROP COLUMN extra")  # before migration 5
        db.execute("PRAGMA user_version = 0")
        db.commit()
        db.close()
        store = self.open_store()
        self.assertIsNotNone(store.player_for_account("old_player"))
        self.assertEqual(self.version(), len(MIGRATIONS))
        self.assertEqual(store.payment_counts(store.player_for_account("old_player")["uid"]), {})

    def test_database_newer_than_the_server_is_refused(self):
        db = sqlite3.connect(self.path)
        db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
        db.close()
        with self.assertRaises(RuntimeError):
            Store(self.path)

    def test_battle_skill_choice_survives_a_reopen(self):
        store = Store(self.path)
        store.create_account("swap_player", "secret12")
        uid = store.player_for_account("swap_player")["uid"]
        card = store.add_cards(uid, [100])[0]
        store.set_battle_skill_slots(card, [2, 3, 4])
        store.close()
        reopened = Store(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.cards_for_player(uid)[0]["battle_slots"], [2, 3, 4])

    def test_a_new_card_has_no_saved_battle_skill_choice(self):
        store = self.open_store()
        store.create_account("plain_player", "secret12")
        uid = store.player_for_account("plain_player")["uid"]
        store.add_cards(uid, [100])
        self.assertIsNone(store.cards_for_player(uid)[0]["battle_slots"])


class PaymentStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.store.create_account("payer_one", "secret12")
        self.uid = self.store.player_for_account("payer_one")["uid"]

    def test_payments_are_counted_per_pack(self):
        self.assertFalse(self.store.payment_exists("order-a"))
        self.store.record_payment(self.uid, "order-a", "3", 100)
        self.store.record_payment(self.uid, "order-b", "3", 101)
        self.store.record_payment(self.uid, "order-c", "5", 102)
        self.assertTrue(self.store.payment_exists("order-a"))
        self.assertEqual(self.store.payment_counts(self.uid), {"3": 2, "5": 1})

    def test_an_order_id_is_recorded_once(self):
        self.store.record_payment(self.uid, "order-a", "3", 100)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.record_payment(self.uid, "order-a", "3", 101)


if __name__ == "__main__":
    unittest.main()
