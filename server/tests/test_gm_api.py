"""The `admin` HTTP service the phone app calls: token, CORS, search, create, give."""

import json
from http.client import HTTPConnection
from urllib.parse import urlencode

from tests.test_flow import BASE, ServerCase

TOKEN = "s3cret-token"


class AdminApiCase(ServerCase):
    def extra_configs(self):
        return {"item": {"1018": {"name": "Thẻ Vàng"}, "7": {"name": "Rương"}},
                "gem": {"502": {"name": "Đá đỏ"}}}

    def setUp(self):
        super().setUp()
        self.server.admin_token = TOKEN
        self.player = self.register()

    def admin(self, method, token=TOKEN, **params):
        status, body = self.get(f"{BASE}/admin/", method=method, token=token, **params)
        self.assertEqual(status, 200)
        return body

    def holdings(self):
        svc = self.server.services
        uid = self.player["uid"]
        return svc.store.items(uid), [c["c_id"] for c in svc.store.cards_for_player(uid)]


class AuthTests(AdminApiCase):
    def test_a_wrong_or_missing_token_is_refused(self):
        self.assertEqual(self.admin("admin.ping", token="nope")["status"], "error_token")
        self.assertEqual(self.admin("admin.ping", token="")["status"], "error_token")
        self.assertEqual(self.admin("admin.ping")["data"], {"ok": True})

    def test_the_service_is_off_without_a_token(self):
        self.server.admin_token = None
        self.assertEqual(self.admin("admin.ping")["status"], "error_not_open")

    def test_answers_allow_the_apps_local_page(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", f"{BASE}/admin/?" + urlencode({"method": "admin.ping", "token": TOKEN}))
        response = conn.getresponse()
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "*")
        json.loads(response.read())
        conn.close()

    def test_the_token_is_kept_out_of_the_request_log(self):
        self.admin("admin.ping")
        self.assertNotIn(TOKEN, self.log_path.read_text(encoding="utf-8"))


class OperationTests(AdminApiCase):
    def test_search_finds_items_by_part_of_the_name(self):
        groups = self.admin("admin.search", q="vàng")["data"]
        self.assertEqual([g["kind"] for g in groups], ["item"])
        self.assertEqual(groups[0]["rows"], [{"id": "1018", "name": "Thẻ Vàng"}])

    def test_accounts_lists_the_players(self):
        names = [a["account"] for a in self.admin("admin.accounts")["data"]]
        self.assertEqual(names, ["player_one"])

    def test_give_adds_items_and_heroes_chosen_by_the_caller(self):
        before_items, _ = self.holdings()
        body = self.admin("admin.give", account="player_one", item="1018:50,7", card="3800",
                          cur="silver=5")
        self.assertEqual(body["status"], 0, body)
        items, cards = self.holdings()
        self.assertEqual((items[1018] - before_items.get(1018, 0), items[7]), (50, 1))
        self.assertIn(3800, cards)

    def test_give_refuses_unknown_ids_and_unknown_accounts(self):
        self.assertEqual(self.admin("admin.give", account="player_one",
                                    item="424242")["status"], "error_param")
        self.assertEqual(self.admin("admin.give", account="nobody", item="7")["status"],
                         "error_param")

    def test_create_makes_a_game_master_account(self):
        body = self.admin("admin.create", account="gm", passwd="gm123456")
        self.assertEqual((body["status"], body["data"]["created"]), (0, True))
        status, login = self.login_api("login", account="gm", passwd="gm123456")
        self.assertEqual((status, login["status"]), (200, 0))
        self.assertEqual(self.admin("admin.show", account="gm")["data"]["level"], 120)
