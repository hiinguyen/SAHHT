"""Run every normal campaign fight with a fixed sample team, to measure balance.

The numbers are a trend, not a promise: the sample team is the five quality-3
heroes 5300/100/200/300/400 at the enemy's level, fully evolved, with their
skills at level 1. The point is to compare the campaign before and after an
engine change (enemy skills, secondary stats) under the same conditions.

    python3 -m tools.simulate_campaign                 # summary per chapter tier
    python3 -m tools.simulate_campaign --cities 100,101  # only these cities
    python3 -m tools.simulate_campaign --json out.json

Each fight uses `random.Random(fight id)`, so two runs of the same code agree.
"""

import argparse
import json
import random
import statistics
from pathlib import Path

from sahht_server import campaign
from sahht_server.battle import WIN, formation_layout, simulate
from sahht_server.progression import ACTIVE, Rules
from sahht_server.skills import SkillBook
from tools.audit_enemy_skills import CONFIG_DIR, campaign_fights, services

SAMPLE_HEROES = (5300, 100, 200, 300, 400)


def max_step(rules, character) -> int:
    table = rules.evolution_table(character)
    steps = [int(k) for k in table if k.isdigit()]
    return max(steps) if steps else 0


def sample_attackers(rules, book, level: int, step: int, heroes=SAMPLE_HEROES) -> list:
    units = []
    for slot, c_id in enumerate(heroes):
        character = rules.characters[str(c_id)]
        card = {"id": f"s{slot}", "c_id": c_id, "lv": level, "step": step,
                "exp": 0, "skills": {}}
        doc = rules.card_document(card, level)
        skills = []
        for skill_slot in range(1, 8):
            entry = doc.get(f"s_{skill_slot}")
            if entry and entry["s"] and entry["avail"] == ACTIVE:
                skill = book.skill(entry["s"], entry["lv"])
                if skill is not None:
                    skills.append((skill_slot, skill))
        units.append({
            "pos": slot, "card_id": str(c_id), "id": f"x_s{slot}", "lv": level,
            "hp": doc["hp"], "patk": doc["patk"], "matk": doc["matk"],
            "def": doc["def"], "speed": doc["speed"],
            "crit": 10, "hit": 100, "dodge": 0,
            "animation": character.get("animation", ""), "race": character.get("race", -1),
            "skills": skills,
        })
    return units


def run(config_dir=CONFIG_DIR, cities=None, step=None, heroes=SAMPLE_HEROES):
    svc = services(config_dir)
    rules, book = Rules.load(svc.configs), SkillBook.load(svc.configs)
    fights = svc.configs.get("map_fight")
    formations = svc.configs.get("formation")
    rows, levels = [], {}
    for city, building, step_n, fight_id in campaign_fights(svc):
        if cities and city not in cities:
            continue
        fight = fights.get(str(fight_id))
        if not fight:
            continue
        defenders = campaign._defenders(svc, city, fight)
        level = max(d["lv"] for d in defenders)
        heroes = {str(c): max_step(rules, rules.characters[str(c)]) for c in heroes}
        team_step = min(heroes.values()) if step is None else step
        attackers = sample_attackers(rules, book, level, team_step, heroes)
        layouts = tuple(formation_layout(formations.get(str(f), {}))
                        for f in (1, fight.get("formation_id", 1)))
        winer, frames = simulate(
            attackers, defenders, rng=random.Random(fight_id), layouts=layouts,
            script=lambda unit, skill, slot: book.script(unit.animation, skill, slot))
        rows.append({"city": city, "building": building, "step": step_n,
                     "fight": fight_id, "level": level, "won": winer == WIN,
                     "frames": len(frames)})
        levels.setdefault(city, level)
    return rows


def summary(rows):
    won = sum(1 for r in rows if r["won"])
    return {
        "fights": len(rows),
        "wins": won,
        "win_rate": round(100 * won / len(rows), 1) if rows else 0.0,
        "median_frames": statistics.median(r["frames"] for r in rows) if rows else 0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-dir", default=str(CONFIG_DIR))
    ap.add_argument("--cities", default="", help="comma-separated city ids (default: all)")
    ap.add_argument("--step", type=int, default=None, help="evolution step (default: max)")
    ap.add_argument("--heroes", default="", help="comma-separated hero card ids of the team")
    ap.add_argument("--json", default="", help="write the per-fight rows here")
    args = ap.parse_args()
    cities = {c for c in args.cities.split(",") if c} or None
    heroes = tuple(int(h) for h in args.heroes.split(",") if h) or SAMPLE_HEROES
    rows = run(Path(args.config_dir), cities, args.step, heroes)
    overall = summary(rows)
    print(f"{overall['fights']} fights, win {overall['win_rate']}%, "
          f"median frames {overall['median_frames']}")
    # Group by city and by the first digit of the city number (chapter tier).
    by_city = {}
    for row in rows:
        by_city.setdefault(row["city"], []).append(row)
    for city in sorted(by_city, key=int):
        s = summary(by_city[city])
        print(f"  city {city}: {s['fights']:>4} fights, win {s['win_rate']:>5}%")
    tiers = {}
    for row in rows:
        tiers.setdefault(row["city"][0], []).append(row)
    print("by tier: " + ", ".join(f"{t}xx {summary(v)['win_rate']}%" for t, v in sorted(tiers.items())))
    if args.json:
        Path(args.json).write_text(json.dumps(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
