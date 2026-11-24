"""Campaign ("Xuất chiến") protocol: world map, city grid, enemy preview, server-side battles."""

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sahht_server import campaign
from sahht_server.battle import simulate
from tests.test_flow import (BASE, FIXTURE_CONFIGS, ROOT, ServerCase, _building, _enemy,
                              _fight)


class CampaignCase(ServerCase):
    def setUp(self):
        super().setUp()
        data = self.register()
        self.rans, self.uid = data["rand_str"], data["uid"]
        self.api("cards.open", self.rans, self.uid)  # grants the starter heroes

    def call(self, method, **params):
        _, body = self.api(f"private_city.{method}", self.rans, self.uid, **params)
        return body

    def cells(self, land, building):
        return [cell for row in land for cell in row if cell[1] == building]


class WorldMapTests(CampaignCase):
    def test_world_map_marks_the_first_city_and_its_progress(self):
        body = self.call("world_map")
        self.assertEqual(body["status"], 0)
        data = body["data"]
        self.assertEqual(data["hard_last_attack"]["chapter"], 1)  # read unguarded
        self.assertEqual((data["last_chapter"], data["last_city"]), ("1", "100"))
        self.assertEqual(data["all_city_regain_percent"], {"100": 0})

    def test_cities_past_the_scope_are_left_out(self):
        svc = self.server.services
        narrow = dataclasses.replace(svc, scope=dataclasses.replace(svc.scope, city_order_max=0))
        self.assertEqual(campaign._cities_in_order(svc), ["100"])
        self.assertEqual(campaign._cities_in_order(narrow), [])


class CityTests(CampaignCase):
    def test_open_lays_out_every_building_on_the_whole_7x7_grid(self):
        data = self.call("open", city="100", chapter="1")["data"]
        land = data["land"]
        # Cells left out are drawn as fog, so the grid is always complete.
        self.assertEqual(len(land), 7)
        self.assertTrue(all(len(row) == 7 for row in land))
        self.assertTrue(all(len(cell) == 4 for row in land for cell in row))
        self.assertEqual((data["city"], data["curt_regain"], data["recapture_log"]),
                         ("100", 0, {}))
        # One anchor cell per building plus covered cells for the larger ones.
        self.assertEqual(len(self.cells(land, 100000)), 1)
        self.assertEqual([c[3] for c in self.cells(land, 100002)], [0, 1])
        self.assertEqual(sorted(c[3] for c in self.cells(land, 100003)), [0, 1, 1, 1])

    def test_buildings_sharing_one_fight_are_decoration(self):
        land = self.call("open", city="100", chapter="1")["data"]["land"]
        self.assertEqual(self.cells(land, 100004) + self.cells(land, 100005), [])

    def test_only_the_next_building_is_attackable(self):
        land = self.call("open", city="100", chapter="1")["data"]["land"]
        self.assertEqual(self.cells(land, 100001)[0][0], 2)
        self.assertEqual(self.cells(land, 100002)[0][0], 0)
        self.assertEqual(self.cells(land, 100001)[0][2], "b.png")

    def test_unknown_city_is_rejected(self):
        self.assertEqual(self.call("open", city="999", chapter="1")["status"], "error_param")

    def test_enemy_preview_lists_every_fight_of_the_building(self):
        data = self.call("map_fight_and_enemy", city="100", building="100002")["data"]
        self.assertEqual(set(data["map_fight"]), {"100002", "100003"})
        self.assertEqual(set(data["enemy_detail"]), {"20001", "10001"})
        self.assertEqual(data["enemy_detail"]["20001"]["animation"], "vega")


class BattleTests(CampaignCase):
    def fight(self, building, step=0):
        return self.call("recapture", city="100", building=str(building), step_n=str(step))

    def test_winning_the_last_step_clears_the_building_and_unlocks_the_next(self):
        body = self.fight(100001)
        data = body["data"]
        self.assertEqual(body["status"], 0)
        self.assertEqual(data["has_battled"], 1)
        self.assertEqual((data["city"], data["building"], data["next_step"]), ("100", "100001", -1))
        self.assertEqual(data["battle"]["winer"], 1)
        self.assertEqual(body["user_status"]["action_point"], 116)  # 120, building costs 4

        city = self.call("open", city="100", chapter="1")["data"]
        self.assertEqual(self.cells(city["land"], 100001)[0][0], 1)
        self.assertEqual(self.cells(city["land"], 100002)[0][0], 2)
        self.assertEqual(city["curt_regain"], 33)
        world = self.call("world_map")["data"]
        self.assertEqual(world["all_city_regain_percent"], {"100": 33})

    def test_battle_record_has_the_shape_the_battle_scene_plays_back(self):
        battle = self.fight(100001)["data"]["battle"]
        init = battle["init"]
        self.assertEqual(len(init["atk"]), 10)
        self.assertEqual(len(init["dfd"]), 10)
        attackers = [u for u in init["atk"] if u]
        self.assertEqual(len(attackers), 3)
        self.assertTrue(all(u["id"].startswith("x_") for u in attackers))
        self.assertEqual(init["dfd"][0]["animation"], "vega")  # defenders have no config lookup
        self.assertEqual(init["dfd"][1:], [0] * 9)
        self.assertEqual((init["atk_skill"], init["dfd_skill"]), ([0, 0, 0], [0, 0, 0]))
        self.assertEqual((init["card_att"], init["card_def"]), ({}, {}))
        frames = battle["battle"]
        self.assertEqual(sorted(frames, key=int), [str(i) for i in range(1, len(frames) + 1)])
        self.assertEqual(frames[str(len(frames))], {"flag": "winer", "param": 1})
        self.assertEqual(frames["1"]["flag"], "sort")

    def test_multi_step_building_needs_every_step(self):
        self.fight(100001)
        self.assertEqual(self.fight(100002, 0)["data"]["next_step"], 1)
        land = self.call("open", city="100", chapter="1")["data"]["land"]
        self.assertEqual(self.cells(land, 100002)[0][0], 2)  # still the target
        self.assertEqual(self.fight(100002, 1)["data"]["next_step"], -1)
        land = self.call("open", city="100", chapter="1")["data"]["land"]
        self.assertEqual(self.cells(land, 100002)[0][0], 1)

    def test_a_lost_battle_does_not_clear_the_building(self):
        self.fight(100001)
        self.fight(100002, 0)
        self.fight(100002, 1)
        data = self.fight(100003)["data"]
        self.assertGreater(data["battle"]["winer"], 5)
        land = self.call("open", city="100", chapter="1")["data"]["land"]
        self.assertEqual(self.cells(land, 100003)[0][0], 2)

    def test_locked_building_and_bad_step_are_refused(self):
        self.assertEqual(self.fight(100002)["status"], "error_building_locked")
        self.assertEqual(self.fight(100001, 5)["status"], "error_param")
        self.assertEqual(self.fight(999999)["status"], "error_param")

    def test_stamina_runs_out_and_experience_levels_the_player_up(self):
        statuses = [self.fight(100001) for _ in range(35)]
        # 120 stamina + 5 restored by each of the 4 level-ups = 140 = 35 fights of 4.
        self.assertTrue(all(s["status"] == 0 for s in statuses))
        self.assertEqual(self.fight(100001)["status"], "error_action_point")
        # Levels cost 10, 20, 30, 40 exp (role.config); 5 is the top level, where exp stops.
        mid = statuses[5]["user_status"]   # 6 fights x 6 exp = 36 = 10 + 20 + 6
        self.assertEqual((mid["level"], mid["exp"], mid["exp_max"]), (3, 6, 30))
        last = statuses[34]["user_status"]
        self.assertEqual((last["action_point"], last["level"], last["exp"]), (0, 5, 0))


class LandSizeTests(unittest.TestCase):
    def test_grid_follows_the_city_tmx_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            maps = root / "iphonehd" / "building_img"
            maps.mkdir(parents=True)
            (maps / "small.tmx").write_text(
                '<?xml version="1.0"?>\n<map version="1.0" orientation="isometric" '
                'width="24" height="20" tilewidth="80" tileheight="40">\n</map>')
            configs = {"cityid_cityorderid": {"101": "2"},
                       "map_main_story": {"2": {"stage_id": "101", "tmx": "small.tmx"}}}
            svc = SimpleNamespace(config_dir=root / "config",
                                  configs=SimpleNamespace(get=lambda name: configs.get(name, {})))
            # 4x4 tiles per land cell: 24 tiles wide = 6 columns, 20 tall = 5 rows.
            self.assertEqual(campaign._land_size(svc, "101"), (6, 5))
            self.assertEqual(campaign._land_size(svc, "999"), campaign.DEFAULT_GRID)


class SimulatorTests(unittest.TestCase):
    def unit(self, pos, hp, patk, defense, speed):
        return {"pos": pos, "hp": hp, "patk": patk, "def": defense, "speed": speed}

    def test_stronger_team_wins_and_frames_end_with_the_result(self):
        winer, frames = simulate([self.unit(0, 1000, 300, 50, 200)],
                                 [self.unit(100, 500, 100, 20, 100)])
        self.assertEqual(winer, 1)
        self.assertEqual(frames[-1], {"flag": "winer", "param": 1})
        self.assertIn({"flag": "death", "param": 100}, frames)
        hits = [f for f in frames if f["flag"] == "attack"]
        self.assertEqual(hits[0]["param"], {"src": 0, "des": 100, "hurt": 281})  # 300 * 300 / (300 + 20)

    def test_hp_bar_updates_carry_max_hp(self):
        _, frames = simulate([self.unit(0, 1000, 300, 50, 200)],
                             [self.unit(100, 500, 100, 20, 100)])
        update = next(f for f in frames if f["flag"] == "cur_data")
        self.assertEqual(update["param"], {"100": {"maxHp": 500, "tempHp": 219}})

    def test_stalemate_after_30_rounds_is_a_loss(self):
        winer, frames = simulate([self.unit(0, 10**9, 1, 10**6, 200)],
                                 [self.unit(100, 10**9, 1, 10**6, 100)])
        self.assertGreater(winer, 5)
        self.assertEqual(sum(f["flag"] == "sort" for f in frames), 30)


if __name__ == "__main__":
    unittest.main()


class NormalCampaignUnlockTests(CampaignCase):
    """Every normal chapter and city opens at level 1; elite (is_hard) ones keep their level."""

    def extra_configs(self):
        return {
            # The APK's key order is by string ("1", "10", "101", ...), not by number.
            "chapter": {"101": {"is_hard": 1, "open_level": 5}, "2": {"is_hard": 0, "open_level": 40},
                        "1": {"is_hard": 0, "open_level": 1}},
            "map_main_story": {
                "1": {"stage_id": "100", "open_level": 1, "chapter": 1},
                "2": {"stage_id": "101", "open_level": 40, "chapter": 2},
                "1001": {"stage_id": "401", "open_level": 5, "chapter": 101}},
            "cityid_cityorderid": {"100": "1", "101": "2", "401": "1001"},
            "map_title_detail": {**FIXTURE_CONFIGS["map_title_detail"],
                                 "101001": _building([101001]), "401001": _building([100001])},
            # Building 101001 borrows a fight of city 102, whose enemies live in its own file.
            "map_fight": {**FIXTURE_CONFIGS["map_fight"], "101001": _fight(102001)},
            "enemy_soldier_102": {"102001": _enemy(250)},
        }

    def test_loading_reports_new_versions_for_the_edited_configs(self):
        _, body = self.get(f"{BASE}/login/", method="loading")
        apk = json.loads((ROOT / "data" / "game_config_version.json").read_text())
        versions = body["game_config_version"]
        self.assertNotEqual(versions["chapter"], apk["chapter"])
        self.assertNotEqual(versions["map_main_story"], apk["map_main_story"])
        self.assertEqual({k: v for k, v in versions.items()
                          if k not in ("chapter", "map_main_story")},
                         {k: v for k, v in apk.items() if k not in ("chapter", "map_main_story")})

    def test_the_client_downloads_the_opened_configs(self):
        _, body = self.get(f"{BASE}/config/", method="all_config", config_name="chapter")
        chapters = body["data"]["chapter"]
        self.assertEqual({k: v["open_level"] for k, v in chapters.items()},
                         {"1": 1, "2": 1, "101": 5})
        # The chapter picker taps getNodeAt(i) of the file: normal chapters first, by number.
        self.assertEqual(list(chapters), ["1", "2", "101"])
        _, body = self.get(f"{BASE}/config/", method="all_config", config_name="map_main_story")
        self.assertEqual({v["stage_id"]: v["open_level"]
                          for v in body["data"]["map_main_story"].values()},
                         {"100": 1, "101": 1, "401": 5})

    def test_a_level_1_player_reaches_every_normal_city(self):
        data = self.call("world_map")["data"]
        self.assertEqual(data["all_city_regain_percent"], {"100": 0, "101": 0})
        body = self.call("recapture", city="101", building="101001", step_n="0")
        self.assertEqual(body["status"], 0, body)
        self.assertEqual(body["data"]["battle"]["winer"], 1)

    def test_the_map_opens_on_the_first_normal_city_not_recovered(self):
        store = self.server.services.store
        store.set_level(self.uid, 5, 0, 0)   # reaches elite city 401 too
        for building in (100001, 100002, 100003):
            store.mark_cleared(self.uid, building)
        data = self.call("world_map")["data"]
        self.assertIn("401", data["all_city_regain_percent"])
        self.assertEqual((data["last_chapter"], data["last_city"]), ("2", "101"))
        store.mark_cleared(self.uid, 101001)
        data = self.call("world_map")["data"]
        self.assertEqual((data["last_chapter"], data["last_city"]), ("2", "101"))
