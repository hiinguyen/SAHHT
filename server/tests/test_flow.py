"""End-to-end protocol tests: a real HTTP server, driven the way the game client drives it."""

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode

from sahht_server.app import build_server

ROOT = Path(__file__).resolve().parent.parent
BASE = "/pub_abroad_vr"


def _character(c_id):
    """A character_detail.config entry with the fields the server derives cards from."""
    return {
        "name": f"hero{c_id}", "quality": 3, "skill_num": 3,
        "base_hp": 1000 + c_id, "base_patk": 200, "base_matk": 150, "base_def": 100,
        "base_speed": 250, "growth_hp": 90, "growth_patk": 14, "growth_matk": 10,
        "growth_def": 9, "growth_speed": 16,
        "skill_1_source": [[c_id + 10, 1]], "skill_2_source": [[c_id + 20, 1]],
        "skill_3_source": [[c_id + 30, 1]], "skill_4_source": [[c_id + 40, 1]],
        "character_ID": c_id // 100, "evo_food": 400, "evo_kind": 1, "type": 1, "race": 0,
    }


def _building(fights, ap=4, size=(1, 1), img="b.png"):
    return {"title_img": img, "title_x": size[0], "title_y": size[1], "action_point": ap,
            "fight_list": [[f"step{f}", f] for f in fights], "reward_first_base": []}


def _fight(enemy):
    slots = {f"position{i}": [] for i in range(1, 6)}
    slots["position1"] = [enemy]
    return {**slots, "fight_boss": "0", "formation_id": 1,
            "reward_exp_role": 6, "reward_exp_character": 23}


def _enemy(hp, patk=50, defense=10, speed=100):
    return {"enemy_name": f"enemy{hp}", "animation": "vega", "img": "icon_vega.png",
            "rgb_sort": 0, "lv": 2, "hp": hp, "patk": patk, "matk": 10, "def": defense,
            "speed": speed}


# A small synthetic copy of the configs the server reads. City 100 has a 1x1
# building (one fight), a 2x1 building (two fights) and a 2x2 boss (one fight).
FIXTURE_CONFIGS = {
    "achieve": {"1": {"a": 1}},
    "badge": {"2": {"b": 2}},
    "character_detail": {str(c_id): _character(c_id) for c_id in (5300, 100, 200, 3800)},
    "cityid_cityorderid": {"100": "1"},
    "map_title_detail": {
        "100001": {**_building([100001]), "reward_first_base": [[1, 0, 100], [6, 1018, 1]],
                   "reward_sweep_base": [[15, 0, 5]]},
        "100002": _building([100002, 100003], size=(2, 1)),
        "100003": _building([100004], size=(2, 2)),
        # Placeholder decoration: several buildings sharing one fight are not attackable.
        "100004": _building([100009]),
        "100005": _building([100009]),
    },
    "map_fight": {"100001": _fight(10001), "100002": _fight(20001),
                  "100003": _fight(10001), "100004": _fight(10002)},
    "enemy_detail": {"10001": _enemy(300), "10002": _enemy(100000, patk=5000, defense=900)},
    # Most campaign enemies live in a per-city file, looked up before enemy_detail.
    "enemy_soldier_100": {"20001": _enemy(250)},
    "map_main_story": {"1": {"stage_id": "100", "open_level": 1, "chapter": 1}},
    # Player levels: exp to leave a level, stamina restored on reaching it.
    "role": {str(lv): {"exp": 10 * lv, "recover_point": 5} for lv in range(1, 6)},
    "role_detail": {"1": {"item": [[1018, 2], [27, 1]]}},
    "item": {"1018": {"name": "shard", "stack": 9999, "is_use": 0},
             "27": {"name": "stamina", "stack": 9999, "is_use": 2, "use_effect": [5]},
             "100": {"name": "coin box", "stack": 9999, "is_use": 1, "use_effect": [7]}},
    "character_base": {str(lv): {"exp": 20 * lv, "sell_food": 100, "eaten_skill_exp": 50,
                                 "skill_strengthen_food": 50} for lv in range(1, 11)},
    "character_base_rate": {"1": {"exp_rate": 1, "sell_food_rate": 1, "eaten_skill_exp_rate": 1,
                                  "skill_strengthen_food_rate": 1}},
    "evolution": {str(step): {"step": step, "exp": 10, "need_level": 2 * step, "player_level": 0,
                              "skill": skill, "type0": [10 * step, 0, 0, 0, 100 * step]}
                  for step, skill in enumerate(([1, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]))},
    "combat_base": {"hp": 0.6, "patk": 1, "matk": 1, "def": 0.8, "speed": 0.6},
    "combat_skill": {"1": {str(q): 0.1 for q in range(8)}},
    "skill_detail": {str(c_id + slot): {"skill_quality": 0, "max_lv": 3}
                     for c_id in (5300, 100, 200, 3800) for slot in (10, 20, 30)},
    "skill_levelup": {"1": [50] * 8, "2": [100] * 8, "3": [150] * 8},
    "guide_team": {"1": {"guide_sort": 1, "open_sort": 1, "open_value": 0},
                   "2": {"guide_sort": 1, "open_sort": 4, "open_value": 100}},
    "guide": {"1": {str(i): {"guide_team": 1} for i in range(1, 28)},
              "2": {str(i): {"guide_team": 2} for i in range(28, 41)}},
    # 999 is the one-draw tutorial pool that opens 101; 101 is unlimited.
    "gacha": {
        "999": {"consume_sort": 2, "value": 250, "get_num": 1, "gacha_sort": 2, "gacha_num": 1,
                "gacha_team": 999, "use_gacha": [], "use_level": [1, 300],
                "good_item": [[3800, 3, 1]], "bad_item": [[3800, 3, 1]],
                "add_point": 0, "good_point": 0},
        "101": {"consume_sort": 3, "value": 300, "get_num": 2, "gacha_sort": 0, "gacha_num": 0,
                "gacha_team": 20, "use_gacha": [999, 1], "use_level": [1, 300],
                "good_item": [[200, 5, 1]], "bad_item": [[100, 5, 9], [194]],
                "add_point": 50, "good_point": 100},
    },
    "shop": {
        "500": {"need_sort": 1, "need_value": [10, 20], "sell_max": 3, "sell_sort": 1,
                "sell_time": "", "shop_reward": [[1, 0, 4000]], "show_level": [1, 300], "im_use": 0},
        "501": {"need_sort": 1, "need_value": [5], "sell_max": 0, "sell_sort": 1,
                "sell_time": "", "shop_reward": [[1, 0, 1]], "show_level": [1, 300], "im_use": 0},
        "502": {"need_sort": 1, "need_value": [5], "sell_max": 0, "sell_sort": 0,
                "sell_time": "", "shop_reward": [[1, 0, 1]], "show_level": [1, 300], "im_use": 0},
        "518": {"need_sort": 1, "need_value": [1], "sell_max": 0, "sell_sort": 0,
                "sell_time": "", "shop_reward": [[22, 3, 1]], "show_level": [1, 300], "im_use": 0},
    },
    "box": {"7": [{"num": 1, "reward": [[9, 0, 250, 3]]}, {"num": 0, "reward": []}]},
    # Each layout leaves one of the six cells (a..f) empty.
    "formation": {str(n): {f"position_{cell}": (0 if i == n - 1 else 1 + i - (i > n - 1))
                           for i, cell in enumerate("abcdef")} for n in (1, 5)},
}


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tmp.name) / "config"
        self.config_dir.mkdir()
        for name, content in FIXTURE_CONFIGS.items():
            (self.config_dir / f"{name}.config").write_text(json.dumps(content))
        self.log_path = Path(self.tmp.name) / "requests.jsonl"
        self.server = build_server(
            host="127.0.0.1",
            port=0,
            db_path=":memory:",
            config_dir=self.config_dir,
            version_map_path=ROOT / "data" / "game_config_version.json",
            request_log=self.log_path,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path, form=None, **params):
        """GET with the params in the query; with `form`, POST it as the body like the client."""
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        url = f"{path}?{urlencode(params, doseq=True)}"
        if form is None:
            conn.request("GET", url)
        else:
            conn.request("POST", url, body=urlencode(form, doseq=True),
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, json.loads(raw)

    def login_api(self, method, **params):
        return self.get(f"{BASE}/login/", method=method, **params)

    def api(self, method, rans, uid, form=None, **params):
        return self.get(f"{BASE}/api/", form, method=method, rans=rans, user_token=uid, **params)

    def register(self, account="player_one", passwd="secret12"):
        status, body = self.login_api("register", account=account, passwd=passwd)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], 0, body)
        return body["data"]


class LoginTests(ServerCase):
    def test_register_returns_ticket_uid_and_server_list(self):
        data = self.register()
        self.assertTrue(data["rand_str"])
        self.assertTrue(data["uid"])
        self.assertEqual(len(data["server_list"]), 1)

    def test_server_entries_carry_every_field_the_client_reads(self):
        data = self.register()
        entry = data["server_list"][0]
        for key in ("server", "server_name", "sort_id", "uid", "level", "flag",
                    "master_url", "domain", "lua_url", "lua_ver_url",
                    "dataosha_url", "chat_ip", "chat_port", "open_time"):
            self.assertIn(key, entry)
        self.assertEqual(entry["uid"], data["uid"])
        self.assertTrue(entry["domain"].startswith("http://127.0.0.1:"))

    def test_duplicate_register_is_refused(self):
        self.register()
        _, body = self.login_api("register", account="player_one", passwd="other_pw1")
        self.assertEqual(body["status"], "error_account_exist")

    def test_register_rejects_invalid_account_name(self):
        _, body = self.login_api("register", account="bad name!", passwd="secret12")
        self.assertEqual(body["status"], "error_param")

    def test_login_success_issues_new_ticket_and_current_server(self):
        first = self.register()
        _, body = self.login_api("login", account="player_one", passwd="secret12")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"]["current_server"], "1")
        self.assertNotEqual(body["data"]["rand_str"], first["rand_str"])

    def test_login_wrong_password(self):
        self.register()
        _, body = self.login_api("login", account="player_one", passwd="nope")
        self.assertEqual(body["status"], "error_account")

    def test_login_unknown_account(self):
        _, body = self.login_api("login", account="ghost_user", passwd="secret12")
        self.assertEqual(body["status"], "error_account")

    def test_server_list_requires_valid_ticket(self):
        self.register()
        _, body = self.login_api("get_user_server_list", account="player_one", rans="")
        self.assertEqual(body["status"], "error_need_login")
        _, body = self.login_api("get_user_server_list", account="player_one", rans="forged")
        self.assertEqual(body["status"], "error_need_login")

    def test_server_list_with_ticket(self):
        data = self.register()
        _, body = self.login_api("get_user_server_list", account="player_one",
                                 rans=data["rand_str"])
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"]["current_server"], "1")
        self.assertEqual(body["data"]["server_list"][0]["uid"], data["uid"])

    def test_old_ticket_dies_after_new_login(self):
        old = self.register()["rand_str"]
        self.login_api("login", account="player_one", passwd="secret12")
        _, body = self.login_api("get_user_server_list", account="player_one", rans=old)
        self.assertEqual(body["status"], "error_need_login")

    def test_unsupported_login_method_is_refused(self):
        _, body = self.login_api("get_user_server_list_huawei", account="x")
        self.assertEqual(body["status"], "refused")

    def test_new_account_creates_guest(self):
        _, body = self.login_api("new_account")
        self.assertEqual(body["status"], 0)
        self.assertTrue(body["data"]["fake_account"].startswith("fake_account_"))
        self.assertIn("ks", body["data"])
        self.assertEqual(len(body["data"]["server_list"]), 1)


class BootTests(ServerCase):
    def test_loading_returns_version_map_at_top_level(self):
        status, body = self.get(f"{BASE}/login/", method="loading")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], 0)
        self.assertIn("data", body)
        expected = json.loads((ROOT / "data" / "game_config_version.json").read_text())
        self.assertEqual(body["game_config_version"], expected)
        self.assertTrue(body["all_config_version"])

    def test_all_config_serves_one_named_config(self):
        _, body = self.get(f"{BASE}/config/", method="all_config", config_name="achieve")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"], {"achieve": {"1": {"a": 1}}})

    def test_all_config_without_name_serves_all(self):
        _, body = self.get(f"{BASE}/config/", method="all_config")
        self.assertEqual(set(body["data"]), set(FIXTURE_CONFIGS))

    def test_all_config_rejects_path_traversal(self):
        _, body = self.get(f"{BASE}/config/", method="all_config", config_name="../secret")
        self.assertEqual(body["status"], "error_param")

    def test_lua_version_manifest_has_no_differences(self):
        status, body = self.get(f"{BASE}/lua_ver/nx1.8.5.b150.json")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["different_files"], [])
        self.assertTrue(body["data"]["current_version"])

    def test_unknown_path_is_404_json(self):
        status, body = self.get("/nowhere")
        self.assertEqual(status, 404)
        self.assertIn("error", body)


class GameApiTests(ServerCase):
    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]

    def test_mark_user_login_returns_mk(self):
        _, body = self.get(f"{BASE}/login/", method="mark_user_login",
                           rans=self.rans, user_token=self.uid)
        self.assertEqual(body["status"], 0)
        self.assertTrue(body["data"]["mk"])

    def test_mark_user_login_requires_session(self):
        _, body = self.get(f"{BASE}/login/", method="mark_user_login",
                           rans="forged", user_token=self.uid)
        self.assertEqual(body["status"], "error_need_login")

    def test_ticket_for_other_player_is_refused(self):
        _, body = self.get(f"{BASE}/login/", method="mark_user_login",
                           rans=self.rans, user_token="999999")
        self.assertEqual(body["status"], "error_need_login")

    def test_cards_open_gives_a_new_player_three_starter_heroes_in_formation(self):
        _, body = self.api("cards.open", self.rans, self.uid)
        self.assertEqual(body["status"], 0)
        data = body["data"]
        cards = data["cards"]
        self.assertEqual(len(cards), 3)
        self.assertEqual(sorted(c["c_id"] for c in cards.values()), [100, 200, 5300])
        # setTeamByJsonData reads row 0 (attackers) and row 1 (bench) unguarded,
        # and every id must be a key of `cards`.
        # Rows are positional: "-1" marks an empty attack or bench position.
        attackers, bench = data["alignment"]
        self.assertEqual(sorted(a for a in attackers if a != "-1"), sorted(cards))
        self.assertEqual(len(attackers), 5)
        self.assertEqual(bench, ["-1", "-1", "-1"])
        # The starting bag is role_detail's item list, as id -> stack counts.
        self.assertEqual(data["items"], {"1018": [2], "27": [1]})
        self.assertEqual(data["equip"], {})

    def test_starter_card_carries_every_field_read_unguarded(self):
        _, body = self.api("cards.open", self.rans, self.uid)
        card = next(c for c in body["data"]["cards"].values() if c["c_id"] == 100)
        key = next(k for k, c in body["data"]["cards"].items() if c["c_id"] == 100)
        self.assertEqual(card["id"], key)
        for field in ("lv", "level_max", "step", "evo", "exp", "pre_exp", "quality",
                      "hp", "patk", "matk", "def", "speed"):
            self.assertIsInstance(card[field], int, field)
        # Level 1 stats are the config base stats; the client never derives them.
        self.assertEqual((card["lv"], card["hp"], card["patk"]), (1, 1100, 200))
        # Evolution step 0 unlocks only the first skill; the others show as locked.
        self.assertEqual(card["s_1"], {"s": 110, "lv": 1, "exp": 0, "avail": 2})
        self.assertEqual((card["s_3"]["s"], card["s_3"]["avail"]), (130, 0))
        self.assertNotIn("s_4", card)  # three battle skill slots

    def test_formation_documents_the_formation_screen_requires(self):
        _, body = self.api("cards.open", self.rans, self.uid)
        data = body["data"]
        self.assertEqual(data["equip_pos"], {str(i): ["0", "0", "0", "0"] for i in range(10)})
        self.assertEqual(data["formation"], {"current": 1, "own": [1, 5]})
        # game_util.isInFormationBonus2 runs pairs() on both for every hero card it draws.
        self.assertEqual((data["formation_bonus"], data["formation_bonus_addition"]), ({}, {}))
        # godheroInTeamById iterates lineups "1".."3" whenever a hero card is drawn.
        self.assertEqual(data["god_field_ids"], {str(i): ["-1"] * 5 for i in (1, 2, 3)})
        # getOpenFormationAlertFlag compares these numerically.
        slots = data["battle_card_num"]
        self.assertIsInstance(slots["position_num"], int)
        self.assertIsInstance(slots["alternate_num"], int)

    def test_roster_is_persistent_and_per_player(self):
        _, first = self.api("cards.open", self.rans, self.uid)
        _, again = self.api("cards.open", self.rans, self.uid)
        self.assertEqual(first["data"]["cards"], again["data"]["cards"])
        other = self.register(account="player_two")
        _, theirs = self.api("cards.open", other["rand_str"], other["uid"])
        self.assertFalse(set(first["data"]["cards"]) & set(theirs["data"]["cards"]))

    def test_main_page_has_numbers_client_reads_with_toint(self):
        _, body = self.api("user.main_page", self.rans, self.uid)
        self.assertEqual(body["status"], 0)
        for key in ("arena_rank", "arena_point", "buy_ap_times", "timezone", "combat"):
            self.assertIsInstance(body["data"][key], int)
        # game_data:getIsdoubleValue() calls alerts.is_double:toBool() unguarded.
        self.assertIs(body["data"]["alerts"]["is_double"], False)
        # Anything but 0 makes the main scene demand a re-login with no way to close it.
        self.assertEqual(body["data"]["config_refresh"], 0)

    def test_user_status_has_every_field_the_client_reads_without_a_fallback(self):
        _, body = self.api("cards.open", self.rans, self.uid)
        status = body["user_status"]
        numeric = ("level", "exp", "exp_max", "vip", "vip_exp", "coin", "food", "metal",
                   "energy", "crystal", "silver", "star", "action_point", "action_point_max",
                   "action_point_rate", "action_point_update_left", "server_time",
                   "association_id", "cur_title", "card_max", "equip_max", "role")
        for key in numeric:
            self.assertIsInstance(status.get(key), int, key)
        self.assertEqual(status["association_id"], 0)  # 0 means "no guild" to the client
        self.assertLessEqual(status["action_point"], status["action_point_max"])

    def test_authenticated_responses_carry_top_level_user_status(self):
        _, body = self.api("arena.battle", self.rans, self.uid)
        status = body["user_status"]
        self.assertEqual(status["uid"], self.uid)
        self.assertEqual(status["show_name"], "player_one")
        self.assertEqual(status["level"], 1)
        self.assertIn("coin", status)

    def test_api_requires_session(self):
        _, body = self.api("cards.open", "forged", self.uid)
        self.assertEqual(body["status"], "error_need_login")

    def test_unknown_api_method_gets_empty_success_and_is_logged(self):
        _, body = self.api("arena.battle", self.rans, self.uid, foo="1")
        self.assertEqual(body["status"], 0)
        self.assertEqual(body["data"], {})
        lines = [json.loads(l) for l in self.log_path.read_text().splitlines()]
        hits = [l for l in lines if l.get("method") == "arena.battle"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["stub"])
        self.assertEqual(hits[0]["params"]["foo"], "1")

    def test_request_log_never_stores_passwords_or_tickets(self):
        self.login_api("login", account="player_one", passwd="secret12")
        self.api("arena.battle", self.rans, self.uid)
        text = self.log_path.read_text()
        self.assertNotIn("secret12", text)
        self.assertNotIn(self.rans, text)


if __name__ == "__main__":
    unittest.main()
