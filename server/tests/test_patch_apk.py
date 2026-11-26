"""Tests for the client patcher: cocos2d-x XXTEA and APK entry replacement."""

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import patch_apk

APK = Path(__file__).resolve().parents[2] / "sahht-sl-1.5.0.apk"
CONFIG_ENTRY = "assets/lua/game_version_config.lua"
NEW_URL = "http://10.0.2.2:8080/pub_abroad_vr"

SAMPLE_LUA = (
    'CLIENT_VERSION = "1.5.0"\n'
    '-- SERVER_LIST_URL_NET = "http://old.example/pub_abroad_vn";\n'
    'SERVER_LIST_URL_NET = "https://api-game.tool-sah.pro.vn/pub_abroad_vr";\n'
    'SERVER_LIST_URL_CN = "https://api-game.tool-sah.pro.vn/pub_abroad_vr";\n'
)


class XxteaTests(unittest.TestCase):
    def test_round_trip_for_many_lengths(self):
        for length in range(1, 70):
            data = os.urandom(length)
            blob = patch_apk.encrypt(data, b"aaa")
            self.assertTrue(blob.startswith(b"XXTEA"))
            self.assertEqual(patch_apk.decrypt(blob, b"aaa"), data, length)

    def test_wrong_key_is_detected(self):
        blob = patch_apk.encrypt(b"print('hello world')", b"aaa")
        with self.assertRaises(ValueError):
            patch_apk.decrypt(blob, b"bbb")

    def test_missing_signature_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_apk.decrypt(b"not encrypted at all", b"aaa")

    @unittest.skipUnless(APK.is_file(), "original APK not present")
    def test_matches_the_shipped_client_byte_for_byte(self):
        original = zipfile.ZipFile(APK).read(CONFIG_ENTRY)
        plain = patch_apk.decrypt(original, b"aaa")
        self.assertIn(b"SERVER_LIST_URL_NET", plain)
        self.assertEqual(patch_apk.encrypt(plain, b"aaa"), original)


class LuaPatchTests(unittest.TestCase):
    def test_replaces_both_active_urls_and_leaves_comments(self):
        out = patch_apk.patch_server_url(SAMPLE_LUA, NEW_URL)
        self.assertIn(f'SERVER_LIST_URL_NET = "{NEW_URL}";', out)
        self.assertIn(f'SERVER_LIST_URL_CN = "{NEW_URL}";', out)
        self.assertIn('-- SERVER_LIST_URL_NET = "http://old.example/pub_abroad_vn";', out)
        self.assertNotIn("tool-sah", out)

    def test_rejects_urls_that_could_break_out_of_the_lua_string(self):
        for bad in ('http://x/"; os.exit()--', "http://x/\nevil()", "ftp://x/y",
                    "http://x/a\\b", "not a url"):
            with self.assertRaises(ValueError, msg=bad):
                patch_apk.patch_server_url(SAMPLE_LUA, bad)

    def test_fails_when_the_lines_are_not_found(self):
        with self.assertRaises(ValueError):
            patch_apk.patch_server_url('CLIENT_VERSION = "1.5.0"\n', NEW_URL)


MAP_ENTRY = "assets/lua/game_ui/game_small_map_scene.lua"
MAP_LUA = (
    "function game_small_map_scene.init(self,t_params)\n"
    "    t_params = t_params or {};\n"
    "    self.m_buildingTable = {};\n"
    "    self.m_touchRef = 0;\n"
    "end\n"
)


class ClientFixTests(unittest.TestCase):
    def test_city_map_forgets_the_guide_building_of_the_previous_visit(self):
        out = patch_apk.apply_client_fixes(MAP_ENTRY, MAP_LUA)
        init_body = out.split("function game_small_map_scene.init", 1)[1]
        self.assertIn("self.m_guideBuilding = nil;", init_body)

    def test_other_entries_are_untouched(self):
        self.assertEqual(patch_apk.apply_client_fixes("assets/lua/other.lua", MAP_LUA), MAP_LUA)

    def test_fails_when_the_shipped_code_has_changed(self):
        with self.assertRaises(ValueError):
            patch_apk.apply_client_fixes(MAP_ENTRY, "-- different source\n")

    @unittest.skipUnless(APK.is_file(), "original APK not present")
    def test_applies_to_the_shipped_client(self):
        shipped = patch_apk.decrypt(zipfile.ZipFile(APK).read(MAP_ENTRY), b"aaa").decode()
        out = patch_apk.apply_client_fixes(MAP_ENTRY, shipped)
        self.assertEqual(out.count("self.m_guideBuilding = nil;"),
                         shipped.count("self.m_guideBuilding = nil;") + 1)


BATTLE_ENTRY = "assets/lua/game_ui/game_battle_scene.lua"
BATTLE_LUA = (
    'function game_battle_scene:start()\n'
    '        self:objectDead(tempid)\n'
    '        --[[--if(tempAnim ~= nil) then\n'
    '        elseif(tempFlag == "reenter")then\n'
    '            local tempAnim = game_util:createEffectAnimCallBack("buff_huisu",1.0,false,function ()\n'
    '                self:setCanGo(true,"reenter");\n'
    '            end);\n'
    '            else\n'
    '                self:setCanGo(true,"dengchang anim")\n'
    '            end\n'
)


class ReenterUnlockTests(unittest.TestCase):
    def test_a_revive_frame_unlocks_playback_once(self):
        out = patch_apk.apply_client_fixes(BATTLE_ENTRY, BATTLE_LUA)
        self.assertIn('"buff_huisu",1.0,false,shhhtUnlock)', out)
        self.assertEqual(out.count('self:setCanGo(true,"reenter")'), 1)
        self.assertIn("self.m_shhhtReenterUnlock()", out)

    def test_a_unit_that_revives_keeps_its_sprite_when_it_dies(self):
        out = patch_apk.apply_client_fixes(BATTLE_ENTRY, BATTLE_LUA)
        self.assertIn("self:shhhtReviveAhead(frameId,tempid)", out)
        self.assertIn("function game_battle_scene.shhhtReviveAhead", out)

    def test_a_revive_frame_without_a_sprite_unlocks_playback_instead_of_failing(self):
        out = patch_apk.apply_client_fixes(BATTLE_ENTRY, BATTLE_LUA)
        self.assertIn('elseif(tempFlag == "reenter" and self:shhhtAnimTab(tempFrameData.param.src) ~= nil)then', out)

    def test_fails_when_the_shipped_battle_scene_has_changed(self):
        with self.assertRaises(ValueError):
            patch_apk.apply_client_fixes(BATTLE_ENTRY, "-- different source\n")

    @unittest.skipUnless(APK.is_file(), "original APK not present")
    def test_applies_to_the_shipped_client(self):
        shipped = patch_apk.decrypt(zipfile.ZipFile(APK).read(BATTLE_ENTRY), b"aaa").decode()
        out = patch_apk.apply_client_fixes(BATTLE_ENTRY, shipped)
        self.assertIn("m_shhhtReenterUnlock", out)


class ApkRewriteTests(unittest.TestCase):
    def _source_apk(self, path):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(zipfile.ZipInfo("AndroidManifest.xml"), b"<manifest/>",
                       compress_type=zipfile.ZIP_DEFLATED)
            z.writestr(zipfile.ZipInfo(CONFIG_ENTRY),
                       patch_apk.encrypt(SAMPLE_LUA.encode(), b"aaa"),
                       compress_type=zipfile.ZIP_STORED)
            z.writestr(zipfile.ZipInfo("lib/arm64-v8a/libgame.so"), b"\x7fELF" * 100,
                       compress_type=zipfile.ZIP_STORED)
            for sig in ("META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA"):
                z.writestr(sig, b"old signature")
            z.writestr("META-INF/androidx.core_core.version", b"1.0.0")
            z.writestr(zipfile.ZipInfo(MAP_ENTRY),
                       patch_apk.encrypt(MAP_LUA.encode(), b"aaa"),
                       compress_type=zipfile.ZIP_STORED)

    def test_rewrites_config_drops_old_signature_and_keeps_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.apk", Path(tmp) / "out.apk"
            self._source_apk(src)
            patch_apk.write_patched_apk(src, dst, NEW_URL)
            with zipfile.ZipFile(dst) as z:
                names = z.namelist()
                lua = patch_apk.decrypt(z.read(CONFIG_ENTRY), b"aaa").decode()
                self.assertIn(NEW_URL, lua)
                self.assertNotIn("tool-sah", lua)
                self.assertNotIn("META-INF/CERT.RSA", names)
                self.assertNotIn("META-INF/CERT.SF", names)
                self.assertNotIn("META-INF/MANIFEST.MF", names)
                self.assertIn("META-INF/androidx.core_core.version", names)
                fixed = patch_apk.decrypt(z.read(MAP_ENTRY), b"aaa").decode()
                self.assertIn("self.m_guideBuilding = nil;", fixed)
                self.assertEqual(z.getinfo(CONFIG_ENTRY).compress_type, zipfile.ZIP_STORED)
                self.assertEqual(z.getinfo("lib/arm64-v8a/libgame.so").compress_type,
                                 zipfile.ZIP_STORED)
                self.assertEqual(z.getinfo("AndroidManifest.xml").compress_type,
                                 zipfile.ZIP_DEFLATED)

    def test_refuses_to_overwrite_its_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.apk"
            self._source_apk(src)
            with self.assertRaises(ValueError):
                patch_apk.write_patched_apk(src, src, NEW_URL)


if __name__ == "__main__":
    unittest.main()
