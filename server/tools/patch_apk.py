"""Repoint the SAHHT client at a different server.

The server URL lives in the XXTEA-encrypted `assets/lua/game_version_config.lua`.
This tool decrypts it, swaps the two SERVER_LIST_URL lines, re-encrypts it,
rebuilds the APK without the old signature, then zipaligns and re-signs it.

The cipher is cocos2d-x's xxtea_encrypt: a 5-byte "XXTEA" signature, then
XXTEA over little-endian words where the last plaintext word is the byte length.
"""

import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SIGNATURE = b"XXTEA"
LUA_KEY = b"aaa"
CONFIG_ENTRY = "assets/lua/game_version_config.lua"
_DELTA = 0x9E3779B9
_MASK = 0xFFFFFFFF

URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~\-/]*)?$")
URL_LINE_RE = re.compile(r'^(SERVER_LIST_URL_(NET|CN)\s*=\s*)"[^"\n]*"', re.MULTILINE)
# Fixes to client Lua bugs that the server cannot work around: entry -> [(shipped text, replacement)].
# Each shipped text must occur exactly once, so a changed client fails loudly instead of silently.
CLIENT_FIXES = {
    # The city map is one shared table. `destroy` clears m_guideBuilding, but leaving the screen
    # any other way (tutorial skip, an earlier failed create) keeps a freed sprite there, and the
    # next visit dies in createBuilding on `m_guideBuilding:getPositionY()` ("invalid 'self'").
    "assets/lua/game_ui/game_small_map_scene.lua": [
        ("    self.m_touchRef = 0;\n",
         "    self.m_touchRef = 0;\n    self.m_guideBuilding = nil; -- SAHHT fix: drop a stale sprite from the last visit\n"),
    ],
    # Lets a caller add its own controls to the shared confirm box: `onBuild(panel, text_label)`.
    "assets/lua/game_ui/game_pop_up_box.lua": [
        ('    local m_anim_node = ccbNode:nodeForName("m_anim_node");\n',
         '    if tableParams.onBuild then tableParams.onBuild(m_text_label:getParent(), m_text_label) end -- SAHHT\n'
         '    local m_anim_node = ccbNode:nodeForName("m_anim_node");\n'),
    ],
    # Quick evolution climbs one step. The server's `cards.auto_evolution` also takes `step` (the
    # target) and answers `max_step`; the confirm box gets a "-" button, a number field and a "+" button for the target.
    "assets/lua/game_ui/game_hero_advanced_sure.lua": [
        ("    local cardTable = {}\n",
         "    -- SAHHT: a re-run from the target button keeps the chosen step, a fresh tap resets it\n"
         "    if not self.m_shhht_keep then self.m_shhht_target = nil end\n"
         "    self.m_shhht_keep = nil\n"
         "    local shhht_hero = game_data:getCardDataById(tostring(self.m_selHeroId))\n"
         "    local shhht_cur, shhht_max = shhht_hero.step or 0, 0\n"
         "    local cardTable = {}\n"),
        ('        local cost_exp = data:getNodeWithKey("cost_exp"):toInt()\n',
         '        local cost_exp = data:getNodeWithKey("cost_exp"):toInt()\n'
         '        local shhht_max_node = data:getNodeWithKey("max_step")\n'
         '        shhht_max = shhht_max_node and shhht_max_node:toInt() or shhht_cur + 1\n'
         '        local shhht_target = self.m_shhht_target\n'
         '        if shhht_target == nil or shhht_target <= shhht_cur or shhht_target > shhht_max then\n'
         '            shhht_target = shhht_cur + 1\n'
         '        end\n'
         '        self.m_shhht_target = shhht_target\n'),
        ('            tips = "Xác nhận tiến hóa nhanh thẻ bài này?"\n',
         '            tips = "Xác nhận tiến hóa nhanh tới +" .. shhht_target .. " (tối đa +" .. shhht_max .. ")?"\n'),
        ("        params2.is_save = 1\n",
         "        params2.is_save = 1\n        params2.step = self.m_shhht_target\n"),
        ("            text = tips,      --可缺省\n",
         "            text = tips,      --可缺省\n"
         "            onBuild = (shhht_max > shhht_cur + 1) and function(panel, label)\n"
         "                local function setTarget(v)\n"
         "                    v = math.floor(tonumber(v) or shhht_target)\n"
         "                    v = math.max(shhht_cur + 1, math.min(shhht_max, v))\n"
         "                    if v == shhht_target then return false end\n"
         "                    self.m_shhht_target = v\n"
         "                    self.m_shhht_keep = true\n"
         "                    -- close and rebuild after this touch or edit event has finished\n"
         "                    performWithDelay(CCDirector:sharedDirector():getRunningScene(), function()\n"
         "                        game_util:closeAlertView()\n"
         "                        self:onQuickFunc()\n"
         "                    end, 0)\n"
         "                    return true\n"
         "                end\n"
         "                local lx, ly = label:getPosition()\n"
         "                local y = ly - 26\n"
         "                local box = game_util:createEditBox({size = CCSizeMake(50, 24), fontSize = 16,\n"
         "                    maxLength = 3, text = tostring(shhht_target), inputMode = kEditBoxInputModeNumeric,\n"
         "                    scriptEditBoxHandler = function(event, sender)\n"
         "                        if event == \"return\" then\n"
         "                            local edit = tolua.cast(sender, \"CCEditBox\")\n"
         "                            if not setTarget(edit:getText()) then edit:setText(tostring(shhht_target)) end\n"
         "                        end\n"
         "                    end})\n"
         "                box:setTouchPriority(GLOBAL_TOUCH_PRIORITY - 3)\n"
         "                box:setPosition(ccp(lx, y))\n"
         "                panel:addChild(box)\n"
         "                local function stepper(text, dx, delta)\n"
         "                    local btn = game_util:createCCControlButton2(\"public_littleBtn.png\", text,\n"
         "                        function() setTarget(shhht_target + delta) end, GLOBAL_TOUCH_PRIORITY - 3, 22)\n"
         "                    btn:setPosition(ccp(lx + dx, y))\n"
         "                    panel:addChild(btn)\n"
         "                end\n"
         "                stepper(\"-\", -50, -1)\n"
         "                stepper(\"+\", 50, 1)\n"
         "            end or nil,\n"),
        ("    params.is_save = 0\n",
         "    params.is_save = 0\n    params.step = self.m_shhht_target\n"),
    ],
}
SIGNATURE_FILE_RE = re.compile(r"^META-INF/(MANIFEST\.MF|[^/]+\.(SF|RSA|DSA|EC))$")


# ---- cocos2d-x XXTEA ------------------------------------------------------

def _key_words(key: bytes):
    return struct.unpack("<4I", key[:16].ljust(16, b"\0"))


def _mx(s, y, z, p, e, k):
    return ((((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((s ^ y) + (k[(p & 3) ^ e] ^ z))) & _MASK


def _encrypt_words(v, k):
    n = len(v)
    s, z = 0, v[-1]
    for _ in range(6 + 52 // n):
        s = (s + _DELTA) & _MASK
        e = (s >> 2) & 3
        for p in range(n):
            y = v[(p + 1) % n]
            v[p] = (v[p] + _mx(s, y, z, p, e, k)) & _MASK
            z = v[p]
    return v


def _decrypt_words(v, k):
    n = len(v)
    rounds = 6 + 52 // n
    s, y = (rounds * _DELTA) & _MASK, v[0]
    for _ in range(rounds):
        e = (s >> 2) & 3
        for p in range(n - 1, -1, -1):
            z = v[p - 1]
            v[p] = (v[p] - _mx(s, y, z, p, e, k)) & _MASK
            y = v[p]
        s = (s - _DELTA) & _MASK
    return v


def encrypt(data: bytes, key: bytes) -> bytes:
    if not data:
        raise ValueError("cannot encrypt empty data")
    padded = data + b"\0" * (-len(data) % 4)
    words = list(struct.unpack(f"<{len(padded) // 4}I", padded)) + [len(data)]
    return SIGNATURE + struct.pack(f"<{len(words)}I", *_encrypt_words(words, _key_words(key)))


def decrypt(blob: bytes, key: bytes) -> bytes:
    if not blob.startswith(SIGNATURE):
        raise ValueError("missing XXTEA signature")
    body = blob[len(SIGNATURE):]
    if len(body) % 4 or len(body) < 8:
        raise ValueError("ciphertext is not a whole number of words")
    n = len(body) // 4
    words = _decrypt_words(list(struct.unpack(f"<{n}I", body)), _key_words(key))
    length, capacity = words[-1], (n - 1) * 4
    if not capacity - 3 <= length <= capacity:
        raise ValueError("bad length word: wrong key or corrupt data")
    return struct.pack(f"<{n - 1}I", *words[:-1])[:length]


# ---- patching -------------------------------------------------------------

def patch_server_url(lua_source: str, url: str) -> str:
    """Point both active SERVER_LIST_URL assignments at `url`."""
    if not URL_RE.match(url):
        raise ValueError(f"refusing unsafe or malformed URL: {url!r}")
    found = [m.group(2) for m in URL_LINE_RE.finditer(lua_source)]
    if sorted(found) != ["CN", "NET"]:
        raise ValueError(f"expected one SERVER_LIST_URL_NET and one _CN line, found {found}")
    return URL_LINE_RE.sub(lambda m: f'{m.group(1)}"{url}"', lua_source)


def apply_client_fixes(entry: str, lua_source: str) -> str:
    """Apply the CLIENT_FIXES of `entry`; other entries come back unchanged."""
    for old, new in CLIENT_FIXES.get(entry, []):
        if lua_source.count(old) != 1:
            raise ValueError(f"{entry}: expected exactly one {old.strip()!r}, found {lua_source.count(old)}")
        lua_source = lua_source.replace(old, new)
    return lua_source


def write_patched_apk(src: Path, dst: Path, url: str) -> None:
    """Copy `src` to `dst` with the config re-pointed and the old signature removed (unsigned)."""
    src, dst = Path(src).resolve(), Path(dst).resolve()
    if src == dst:
        raise ValueError("output must differ from the input APK")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if SIGNATURE_FILE_RE.match(info.filename):
                continue
            data = zin.read(info)
            if info.filename == CONFIG_ENTRY:
                patched = patch_server_url(decrypt(data, LUA_KEY).decode("utf-8"), url)
                data = encrypt(patched.encode("utf-8"), LUA_KEY)
                if decrypt(data, LUA_KEY).decode("utf-8") != patched:
                    raise RuntimeError("re-encryption did not round-trip")
            elif info.filename in CLIENT_FIXES:
                patched = apply_client_fixes(info.filename, decrypt(data, LUA_KEY).decode("utf-8"))
                data = encrypt(patched.encode("utf-8"), LUA_KEY)
                if decrypt(data, LUA_KEY).decode("utf-8") != patched:
                    raise RuntimeError("re-encryption did not round-trip")
            out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            zout.writestr(out, data)


# ---- align and sign -------------------------------------------------------

def _build_tools() -> Path:
    sdk = Path(os.environ.get("ANDROID_HOME", Path.home() / "Android" / "Sdk"))
    candidates = sorted((sdk / "build-tools").glob("*/apksigner"))
    if not candidates:
        raise SystemExit(f"no build-tools with apksigner under {sdk}; install with sdkmanager")
    return candidates[-1].parent


def _debug_keystore() -> Path:
    """The standard Android debug keystore; created on first use."""
    path = Path.home() / ".android" / "debug.keystore"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["keytool", "-genkeypair", "-keystore", str(path), "-storepass", "android",
             "-alias", "androiddebugkey", "-keypass", "android", "-keyalg", "RSA",
             "-keysize", "2048", "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"],
            check=True, capture_output=True,
        )
    return path


def align_and_sign(unsigned: Path, out: Path) -> None:
    tools = _build_tools()
    with tempfile.TemporaryDirectory() as tmp:
        aligned = Path(tmp) / "aligned.apk"
        subprocess.run([str(tools / "zipalign"), "-P", "16", "-f", "4", str(unsigned), str(aligned)],
                       check=True)
        subprocess.run(
            [str(tools / "apksigner"), "sign", "--ks", str(_debug_keystore()),
             "--ks-pass", "pass:android", "--ks-key-alias", "androiddebugkey",
             "--key-pass", "pass:android", "--out", str(out), str(aligned)],
            check=True,
        )
    subprocess.run([str(tools / "apksigner"), "verify", str(out)], check=True)


def main():
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True,
                    help="new master URL, e.g. http://10.0.2.2:8080/pub_abroad_vr")
    ap.add_argument("--apk", default=str(root.parent / "sahht-sl-1.5.0.apk"))
    ap.add_argument("--out", default=str(root / "build" / "sahht-local.apk"))
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        unsigned = Path(tmp) / "unsigned.apk"
        write_patched_apk(Path(args.apk), unsigned, args.url)
        align_and_sign(unsigned, out)
    print(f"wrote {out} -> {args.url}", file=sys.stderr)


if __name__ == "__main__":
    main()
