"""Inventory of what the client can call and show, checked against data/scope_2018.json.

    python3 -m tools.audit_scope            # report
    python3 -m tools.audit_scope --draft    # print a draft scope file to stdout

Read-only: it reads the decrypted Lua, the APK configs and the scope file. The draft is
printed, never written over the real file; every guess in it carries scope.UNCLASSIFIED
until a person has checked it.
"""

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from sahht_server.rewards import CARD, ITEM
from sahht_server.scope import DEFAULT_PATH, UNCLASSIFIED
from sahht_server.shop import USE_BOX
from sahht_server.skills import LAST_HERO_ID

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT.parent / "decompiled" / "lua"
CONFIG_DIR = ROOT.parent / "decompiled" / "apk" / "assets" / "config"
URL_RE = re.compile(r'(\w+)\s*=\s*"/(\w+)/\?method=([\w.]+)"')
# Every way the client names a view id: a direct check, a menu table entry
# (game_function_pop filters its items by InReviewId), or a raw in_review_<id> key.
VIEW_RE = re.compile(r"isView(?:Open|Show)ByID\(\s*(\d+)\s*\)|InReviewId\s*=\s*(\d+)|in_review_(\d+)")
UNUSED_REASON = "không nơi nào trong Lua gọi view này"
URL_KEY_RE = re.compile(r'getUrlForKey\(\s*"(\w+)"\s*\)')
WINDOW = 30   # lines around a view check searched for the API calls that screen makes

OPEN_NOW = {"user", "cards", "gacha", "shop", "item", "private_city", "payment"}
OUT_PREFIXES = ("server_", "god_field", "guild_high_war", "cosmic", "universe_", "cb_",
                "world_cup", "large_super", "super_rich", "roulette", "new_roulette",
                "large_roulette", "diamond_wheel", "redpacket", "red_bag")
OUT_MODULES = {"yunxin", "servers_fight", "world_one", "monopoly", "super_tycoon_active",
               "super_luck", "luck_lottery", "jigsaw", "fire_chess", "idol_festival"}
OUT_REASON = "ngoài phạm vi 2018: liên server, sự kiện nạp/quay thưởng hoặc SDK"
# The roadmap's guess per phase; each one still needs checking against its screen.
PHASE_GUESS = {
    1: {"reward", "daily_award", "notify", "friend", "vip", "vip_reward", "pay_award",
        "recharge_package", "gift"},
    2: {"equip", "factory", "equip_gacha", "gem", "commander"},
    3: {"leader_skill"},
    4: {"pyramid", "maze", "nightmare_tower", "search_treasure", "public_land", "mine", "mining"},
    5: {"card_develop", "talent_skill", "sacrifice", "soul", "pets", "badge", "medal"},
    6: {"arena", "association", "guild_gvg", "team_boss"},
}


def load_config(name: str, config_dir=CONFIG_DIR) -> dict:
    path = Path(config_dir) / f"{name}.config"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def url_keys(lua_dir=LUA_DIR) -> dict:
    """game_url_config.lua: key -> (service, method)."""
    text = (Path(lua_dir) / "game_url_config.lua").read_text(encoding="utf-8", errors="replace")
    return {key: (service, method) for key, service, method in URL_RE.findall(text)}


def api_modules(keys: dict) -> dict:
    """/api/ methods grouped by module (the part before the dot)."""
    modules = collections.defaultdict(set)
    for service, method in keys.values():
        if service == "api" and "." in method:
            modules[method.split(".", 1)[0]].add(method)
    return dict(modules)


def view_configs(config_dir=CONFIG_DIR) -> dict:
    views = {}
    for name in ("inreview", "server_inreview"):
        for key, row in load_config(name, config_dir).items():
            views[int(key)] = {"config": name, "name": row.get("name", ""), "story": row.get("story", "")}
    return views


def view_refs(lua_dir=LUA_DIR) -> dict:
    """view id -> [(file, line, url keys used within WINDOW lines)]."""
    refs = collections.defaultdict(list)
    for path in sorted(Path(lua_dir).rglob("*.lua")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith("--"):
                continue   # a commented-out menu entry is not on screen
            for groups in VIEW_RE.findall(line):
                view = next(g for g in groups if g)
                window = "\n".join(lines[max(0, number - 1 - WINDOW):number + WINDOW])
                refs[int(view)].append((str(path.relative_to(lua_dir)), number,
                                        URL_KEY_RE.findall(window)))
    return dict(refs)


def client_views() -> set:
    """Every view id the client can hide: listed in its configs or named in its Lua.
    A view missing from inreview.config is shown by default, so it needs a row too."""
    return set(view_configs()) | set(view_refs())


def reward_triples(value):
    """Every `[type, id, count, ...]` list inside a config value."""
    if isinstance(value, list):
        head = value[:3]
        if len(head) == 3 and all(isinstance(v, int) and not isinstance(v, bool) for v in head):
            yield value
        else:
            for part in value:
                yield from reward_triples(part)
    elif isinstance(value, dict):
        for part in value.values():
            yield from reward_triples(part)


def server_reward_sources(config) -> list:
    """Every reward this server hands out from configs: shop goods, campaign building
    rewards, the starting bag. `config` maps a config name to its dict."""
    triples = []
    for row in config("shop").values():
        triples += list(reward_triples(row.get("shop_reward", [])))
    for row in config("map_title_detail").values():
        for key, value in row.items():
            if key.startswith("reward_"):
                triples += list(reward_triples(value))
    for row in config("role_detail").values():
        triples += [[ITEM, entry[0], entry[1]] for entry in row.get("item", [])
                    if isinstance(entry, list) and len(entry) >= 2]
    return triples


def reachable_cards(triples, items: dict, boxes: dict) -> set:
    """Hero ids the rewards can lead to, opening box items (is_use 1, box = use_effect[0])
    through any depth of boxes inside boxes."""
    todo, seen_items, seen_boxes, cards = list(triples), set(), set(), set()
    while todo:
        kind, ref = todo.pop()[:2]
        if kind == CARD:
            cards.add(ref)
        elif kind == ITEM and ref not in seen_items:
            seen_items.add(ref)
            detail = items.get(str(ref), {})
            if detail.get("is_use") == USE_BOX:
                box = str((detail.get("use_effect") or [0])[0])
                if box in boxes and box not in seen_boxes:
                    seen_boxes.add(box)
                    todo.extend(reward_triples(boxes[box]))
    return cards


def _guess_module(refs: list, keys: dict) -> str | None:
    votes = collections.Counter()
    for _, _, near in refs:
        for key in near:
            service, method = keys.get(key, ("", ""))
            if service == "api" and "." in method:
                votes[method.split(".", 1)[0]] += 1
    return votes.most_common(1)[0][0] if votes else None


def draft_module(name: str) -> dict:
    if name in OPEN_NOW:
        return {"phase": 0, "open": True}
    if name.startswith(OUT_PREFIXES) or name in OUT_MODULES:
        return {"phase": None, "open": False, "reason": OUT_REASON}
    for phase, names in PHASE_GUESS.items():
        if name in names:
            return {"phase": phase, "open": False,
                    "reason": f"{UNCLASSIFIED}: gợi ý giai đoạn {phase} theo lộ trình"}
    return {"phase": None, "open": False, "reason": UNCLASSIFIED}


def draft_view(refs: list, keys: dict, modules: dict) -> dict:
    guess = _guess_module(refs, keys)
    where = ", ".join(f"{f}:{n}" for f, n, _ in refs[:2]) or "không nơi nào gọi"
    if guess in modules:
        return {"module": guess, "reason": f"{UNCLASSIFIED}: đoán từ {where}"}
    return {"open": False, "reason": f"{UNCLASSIFIED}: không thấy API gần {where}"}


def draft() -> dict:
    keys = url_keys()
    modules, refs = api_modules(keys), view_refs()
    return {
        "card_id_max": LAST_HERO_ID,
        "city_order_max": None,
        "modules": {m: draft_module(m) for m in sorted(modules)},
        "quiet": {},
        "views": {str(v): draft_view(refs.get(v, []), keys, modules) for v in sorted(client_views())},
    }


def _city_lines(card_max: int) -> list:
    items, boxes = load_config("item"), load_config("box")
    order = load_config("cityid_cityorderid")
    stories = {str(r.get("stage_id")): r for r in load_config("map_main_story").values()}
    by_city = collections.defaultdict(list)
    for building, row in load_config("map_title_detail").items():
        if building.isdigit():
            for key, value in row.items():
                if key.startswith("reward_"):
                    by_city[str(int(building) // 1000)] += list(reward_triples(value))
    lines = []
    for city, number in sorted(order.items(), key=lambda kv: int(kv[1])):
        cards = reachable_cards(by_city.get(city, []), items, boxes)
        top = max(cards) if cards else "-"
        flag = "  > 2018" if cards and max(cards) > card_max else ""
        level = stories.get(city, {}).get("open_level", "?")
        lines.append(f"city order {number:>4} id {city:>4} open_level {level:>4} max hero {top}{flag}")
    return lines


def report(scope_path=DEFAULT_PATH) -> list:
    from sahht_server.app import SESSION_HANDLERS
    keys = url_keys()
    modules, configs, refs = api_modules(keys), view_configs(), view_refs()
    path = Path(scope_path)
    scope = (json.loads(path.read_text(encoding="utf-8")) if path.is_file()
             else {"card_id_max": LAST_HERO_ID, "modules": {}, "views": {}, "quiet": {}})
    handled = {m for s, m in SESSION_HANDLERS if s == "api"}
    lines = ["== modules (handled/total, quiet)"]
    for module in sorted(modules):
        entry = scope["modules"].get(module)
        state = "MISSING" if entry is None else f"phase={entry.get('phase')} open={entry.get('open')}"
        done = sum(1 for m in modules[module] if m in handled)
        quiet = sum(1 for m in modules[module] if m in scope["quiet"])
        lines.append(f"{module:28} {state:22} {done}/{len(modules[module])} handled, {quiet} quiet")
    lines.append("== views")
    for view in sorted(set(configs) | set(refs)):
        entry = scope["views"].get(str(view))
        where = ", ".join(f"{f}:{n}" for f, n, _ in refs.get(view, [])[:3]) or "không nơi nào gọi"
        state = "MISSING" if entry is None else json.dumps(
            {k: v for k, v in entry.items() if k != "reason"}, ensure_ascii=False)
        info = configs.get(view, {"name": "(không có trong config)", "story": ""})
        lines.append(f"view {view:>5} {state:30} {info['name']} | {info['story']} | {where}")
    lines.append("== level-gated buttons (button_open.config): check each on the emulator")
    for button, text in sorted(load_config("button_open").items(), key=lambda kv: int(kv[0])):
        lines.append(f"button {button:>4} {text}")
    lines.append("== campaign cities")
    lines += _city_lines(scope["card_id_max"])
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draft", action="store_true", help="print a draft scope file to stdout")
    args = ap.parse_args()
    if args.draft:
        json.dump(draft(), sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        print("\n".join(report()))


if __name__ == "__main__":
    main()
