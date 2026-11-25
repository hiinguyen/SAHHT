"""Inventory of the skills campaign enemies use, and their spec coverage.

The battle engine runs enemy skills from `data/enemy_skill_specs.json`, the same
DSL as the hero specs in `data/skill_specs.json` (see SKILLS.md). This tool lists
every skill id an enemy of a normal campaign fight actually casts, ranked by how
often it appears, and flags the ids that still have no spec.

    python3 -m tools.audit_enemy_skills            # coverage report
    python3 -m tools.audit_enemy_skills --detail   # numbers and description per missing id

Coverage is measured on the normal campaign only (the elite chapters reuse the
same enemy tables); `--all-chapters` includes elite chapters for a wider check.
"""

import argparse
import collections
import json
from pathlib import Path
from types import SimpleNamespace

from sahht_server import campaign
from sahht_server.handlers import ConfigCache

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT.parent / "decompiled" / "apk" / "assets" / "config"
SPECS_PATH = ROOT / "data" / "enemy_skill_specs.json"
HERO_SPECS_PATH = ROOT / "data" / "skill_specs.json"

# Per-skill fields that decide the run-time numbers and the animation.
DETAIL_FIELDS = ("skill_name", "skill_type", "cd", "pre_cd", "rate", "effect",
                 "effect_lvchange", "attr_effect", "sprite_py", "skill_quality", "max_lv")


def load_config(name: str, config_dir=CONFIG_DIR) -> dict:
    path = Path(config_dir) / f"{name}.config"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def load_specs(path=SPECS_PATH) -> dict:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def services(config_dir=CONFIG_DIR):
    """Just enough of Services for campaign's config readers."""
    return SimpleNamespace(configs=ConfigCache(Path(config_dir)))


def _normal_chapters(chapter: dict) -> set:
    return {key for key, row in chapter.items()
            if isinstance(row, dict) and row.get("is_hard") == 0}


def campaign_cities(svc: SimpleNamespace, all_chapters=False) -> list:
    """Cities of a chapter set, in campaign order (cityid_cityorderid)."""
    normal = _normal_chapters(svc.configs.get("chapter"))
    story = svc.configs.get("map_main_story")
    order = svc.configs.get("cityid_cityorderid")
    reached = {}
    for row in story.values():
        if not isinstance(row, dict):
            continue
        if not all_chapters and str(row.get("chapter")) not in normal:
            continue
        city = str(row.get("stage_id"))
        if city in order:
            reached[city] = int(order[city])
    return [city for city, _ in sorted(reached.items(), key=lambda kv: kv[1])]


def campaign_fights(svc: SimpleNamespace, all_chapters=False) -> list:
    """(city, building id, fight id) for every building of every campaign city."""
    fights = []
    for city in campaign_cities(svc, all_chapters):
        for building_id in campaign._city_buildings(svc).get(city, []):
            detail = svc.configs.get("map_title_detail")[str(building_id)]
            for step, (_, fight_id) in enumerate(detail["fight_list"]):
                fights.append((city, building_id, step, int(fight_id)))
    return fights


def enemy_skills(svc: SimpleNamespace, all_chapters=False) -> collections.Counter:
    """skill id -> how many enemy slots across the campaign carry it."""
    counts = collections.Counter()
    fights = svc.configs.get("map_fight")
    seen = set()
    for city, _, _, fight_id in campaign_fights(svc, all_chapters):
        if fight_id in seen:
            continue
        seen.add(fight_id)
        fight = fights.get(str(fight_id)) or {}
        for _, enemy_id in campaign._enemy_ids(fight):
            enemy = campaign._enemy(svc, city, enemy_id)
            for slot in range(1, 4):
                skill = enemy.get(f"skill{slot}") or []
                if skill and skill[0]:
                    counts[int(skill[0])] += 1
    return counts


def difficulty_by_city(svc: SimpleNamespace, skills: dict, all_chapters=False) -> dict:
    """city -> the skill ids its enemies need specs for (whose specs are missing)."""
    fights = svc.configs.get("map_fight")
    needed = collections.defaultdict(set)
    for city, _, _, fight_id in campaign_fights(svc, all_chapters):
        fight = fights.get(str(fight_id)) or {}
        for _, enemy_id in campaign._enemy_ids(fight):
            enemy = campaign._enemy(svc, city, enemy_id)
            for slot in range(1, 4):
                skill = enemy.get(f"skill{slot}") or []
                if skill and skill[0] and int(skill[0]) not in skills:
                    needed[city].add(int(skill[0]))
    return dict(needed)


def detail_row(details: dict, skill_id: int) -> dict:
    row = details.get(str(skill_id)) or {}
    return {key: row.get(key) for key in DETAIL_FIELDS}


def report(config_dir=CONFIG_DIR, specs_path=SPECS_PATH, all_chapters=False, detail=False):
    svc = services(config_dir)
    counts = enemy_skills(svc, all_chapters)
    # The legacy 4-digit enemy skills double as hero base skills; their spec may
    # live in either file.
    specs = {**load_specs(HERO_SPECS_PATH), **load_specs(specs_path)}
    missing = {skill_id: n for skill_id, n in counts.items() if str(skill_id) not in specs}
    details = load_config("skill_detail", config_dir)
    print(f"{len(campaign_fights(svc, all_chapters))} fights, "
          f"{len(counts)} enemy skill ids, {len(counts) - len(missing)} specced, "
          f"{len(missing)} missing")
    if not missing:
        return 0
    by_city = difficulty_by_city(svc, specs, all_chapters)
    print("missing ids are needed by these cities: " +
          ", ".join(sorted(by_city, key=int, reverse=True)[:10]) +
          (" ..." if len(by_city) > 10 else ""))
    for skill_id, n in sorted(missing.items(), key=lambda kv: (-kv[1], kv[0])):
        line = f"{skill_id:>6}  x{n:<5}"
        if detail:
            row = detail_row(details, skill_id)
            line += "  " + " ".join(f"{k}={v!r}" for k, v in row.items()
                                    if k != "skill_name")
            print(line)
            print(f"        name={row['skill_name']!r}")
        else:
            print(line)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-dir", default=str(CONFIG_DIR))
    ap.add_argument("--specs", default=str(SPECS_PATH))
    ap.add_argument("--all-chapters", action="store_true",
                    help="include elite chapters (they reuse the same enemy tables)")
    ap.add_argument("--detail", action="store_true",
                    help="print the numbers and description of every missing id")
    args = ap.parse_args()
    raise SystemExit(report(Path(args.config_dir), Path(args.specs),
                           args.all_chapters, args.detail))


if __name__ == "__main__":
    main()
