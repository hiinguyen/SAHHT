"""Battle engine mechanics, one rule per test, with hand-built skills."""

import random
import unittest

from sahht_server.battle import LOSS, WIN, formation_layout, simulate
from sahht_server.skills import Skill


def skill(effects, trigger="active", skill_id=1, **kw):
    fields = dict(id=skill_id, root=skill_id, trigger=trigger, aim="enemy_front", count=1,
                  effects=tuple(effects), effect=100.0, attr=0.0, cd=0, pre_cd=0, rate=100.0,
                  limit_per_round=0, once=False, rounds=(1, 10**6), sprite="")
    fields.update(kw)
    return Skill(**fields)


def unit(pos, hp=1000, patk=100, defense=0, speed=100, skills=(), **kw):
    return {"pos": pos, "hp": hp, "patk": patk, "def": defense, "speed": speed,
            "skills": [(i + 1, s) for i, s in enumerate(skills)], **kw}


def run(attackers, defenders, seed=1, **kw):
    return simulate(attackers, defenders, rng=random.Random(seed),
                    script=lambda u, s, slot: f"script_{s.id}", **kw)


def flags(frames, flag):
    return [f["param"] for f in frames if f["flag"] == flag]


def actions_by_round(frames, pos):
    counts = []
    for f in frames:
        if f["flag"] == "sort":
            counts.append(0)
        elif f["flag"] in ("attack", "skill") and f["param"]["src"] == pos and counts:
            counts[-1] += 1
    return counts


DAMAGE = {"op": "damage", "target": "target", "type": "phys", "scale": "effect"}


class ActiveSkillTests(unittest.TestCase):
    def test_active_skill_replaces_the_normal_attack_with_a_skill_frame(self):
        strike = skill([dict(DAMAGE, scale=200)], skill_id=110)
        _, frames = run([unit(0, skills=[strike])], [unit(100, hp=10**6)])
        first = flags(frames, "skill")[0]
        # raw 200, no defense: 200 * 200 / 200
        self.assertEqual(first, {"src": 0, "name": "script_110", "skillid": 110,
                                 "des": [100], "hurt": [200]})

    def test_cooldown_counts_rounds_and_normal_attacks_fill_the_gap(self):
        strike = skill([DAMAGE], cd=3)
        _, frames = run([unit(0, skills=[strike])], [unit(100, hp=10**6, patk=0)])
        actions = [f["flag"] for f in frames if f["flag"] in ("skill", "attack")
                   and f["param"]["src"] == 0][:7]
        self.assertEqual(actions, ["skill", "attack", "attack", "skill", "attack", "attack", "skill"])

    def test_rate_zero_means_the_skill_always_fires(self):
        strike = skill([DAMAGE], rate=0)
        _, frames = run([unit(0, skills=[strike])], [unit(100, hp=10**6, patk=0)])
        self.assertFalse([p for p in flags(frames, "attack") if p["src"] == 0])

    def test_minus_effect_is_a_reduction_that_scales_with_level(self):
        weaken = skill([DAMAGE, {"op": "buff", "target": "target", "stat": "patk",
                                 "value": "-effect", "rounds": 0}], effect=50.0, once=True)
        enemy = unit(100, hp=10**6, patk=200, speed=50)
        _, frames = run([unit(0, hp=10**6, skills=[weaken])], [enemy])
        enemy_hits = [p["hurt"] for p in flags(frames, "attack") if p["src"] == 100]
        self.assertEqual(enemy_hits[0], 100)  # 200 patk halved, no defense

    def test_bonus_applies_only_when_the_condition_holds(self):
        burn = skill([{"op": "dot", "target": "target", "kind": "burn", "scale": 1,
                       "of": "target_max_hp", "rounds": 5}], skill_id=1, once=True)
        finisher = skill([dict(DAMAGE, bonus=[{"if": "target_has:burn", "pct": 100}])],
                         skill_id=2, cd=2)
        _, frames = run([unit(0, skills=[burn, finisher])], [unit(100, hp=10**6, patk=0)])
        hurts = [p["hurt"][0] for p in flags(frames, "skill") if p["skillid"] == 2]
        self.assertEqual(hurts[0], 200)

    def test_back_row_aim_follows_the_defender_formation(self):
        snipe = skill([DAMAGE], aim="enemy_back")
        layouts = (formation_layout({"position_b": 1, "position_c": 1, "position_d": 1}),) * 2
        defenders = [unit(100, hp=10**6, patk=0), unit(101, hp=10**6, patk=0),
                     unit(102, hp=10**6, patk=0)]
        _, frames = run([unit(0, skills=[snipe])], defenders, layouts=layouts)
        self.assertEqual(flags(frames, "skill")[0]["des"], [102])  # slot 2 = cell d, back row


class StatusTests(unittest.TestCase):
    def test_stunned_unit_skips_its_turn(self):
        stun = skill([DAMAGE, {"op": "control", "target": "target", "kind": "stun", "rounds": 1}],
                     once=True)
        _, frames = run([unit(0, skills=[stun], speed=200)], [unit(100, hp=10**6, speed=100)])
        self.assertEqual(actions_by_round(frames, 100)[:2], [0, 1])
        self.assertIn({"src": 100, "name": "buff_giddy"}, flags(frames, "add_buff"))

    def test_dot_ticks_at_round_start(self):
        bleed = skill([{"op": "dot", "target": "target", "kind": "bleed", "scale": 10,
                        "of": "target_max_hp", "rounds": 2}], once=True)
        _, frames = run([unit(0, patk=0, skills=[bleed])], [unit(100, hp=1000, patk=0)])
        tick = {"src": 100, "des": 100, "name": "buff_hplow_skill", "hurt": 100}
        self.assertEqual(flags(frames, "buff_skill"), [tick, tick])

    def test_shield_absorbs_before_hp(self):
        guard = skill([{"op": "shield", "target": "self", "scale": 10, "of": "max_hp"}],
                      trigger="before_battle")
        _, frames = run([unit(0, patk=1)], [unit(100, hp=1000, patk=0, skills=[guard])])
        first_hit = next(p for p in flags(frames, "attack") if p["des"] == 100)
        self.assertEqual(first_hit["hurt"], 0)  # the 1 damage is absorbed by a 100 shield

    def test_before_battle_skill_plays_as_a_skill_frame_and_lasts(self):
        rally = skill([{"op": "buff", "target": "ally_all", "stat": "patk", "value": 100,
                        "rounds": 3}], trigger="before_battle", skill_id=830)
        _, frames = run([unit(0, skills=[rally])], [unit(100, hp=10**6, patk=0)])
        # Never a pre_battle frame: with a skill in it the client crashes (missing plist).
        self.assertNotIn("pre_battle", [f["flag"] for f in frames])
        self.assertEqual(frames[0]["flag"], "skill")
        self.assertEqual((frames[0]["param"]["skillid"], frames[0]["param"]["desh"]), (830, [0]))
        # The client draws MISS for a health of 0 on every desh target, so a buff-only cast sends none.
        self.assertEqual(frames[0]["param"]["health"], [])
        hurts = [p["hurt"] for p in flags(frames, "attack") if p["src"] == 0]
        self.assertEqual(hurts[:4], [200, 200, 200, 100])  # 3 rounds of +100% patk


class ReactionTests(unittest.TestCase):
    def test_counter_fires_before_the_hit_lands(self):
        counter = skill([dict(DAMAGE, scale=50)], trigger="before_hit", skill_id=1210,
                        limit_per_round=1)
        _, frames = run([unit(0, hp=10**6)], [unit(100, hp=10**6, patk=0, skills=[counter])])
        order = [(f["flag"], f["param"]["src"]) for f in frames if f["flag"] in ("attack", "skill")]
        self.assertEqual(order[:2], [("skill", 100), ("attack", 0)])

    def test_pre_battle_damage_provokes_no_counter(self):
        opener = skill([{"op": "damage", "target": "enemy_front", "type": "phys", "scale": 100}],
                       trigger="before_battle")
        counter = skill([DAMAGE], trigger="before_hit")
        _, frames = run([unit(0, skills=[opener])], [unit(100, hp=10**6, skills=[counter])])
        self.assertEqual(frames[0]["param"]["hurt"], [100])
        self.assertNotIn(100, [p["src"] for p in flags(frames, "skill")][:1])

    def test_a_reaction_inside_a_cast_does_not_announce_deaths_before_the_cast_frame(self):
        # Unit 100 dies to the first hit of the sweep; unit 101's before_hit reaction runs while
        # the sweep's frame is still unwritten. A `death` ahead of the `skill` frame makes the
        # client drop the sprite and then play the hit on it, which crashes the native bar.
        sweep = skill([dict(DAMAGE, target="target")], aim="enemy_all", skill_id=77)
        ward = skill([{"op": "buff", "target": "self", "stat": "def", "value": 10, "rounds": 2}],
                     trigger="before_hit", skill_id=78)
        _, frames = run([unit(0, patk=1000, speed=500, skills=[sweep])],
                        [unit(100, hp=10), unit(101, hp=10**6, skills=[ward])])
        names = [(f["flag"], f["param"] if f["flag"] == "death" else None) for f in frames]
        cast = next(i for i, f in enumerate(frames)
                    if f["flag"] == "skill" and f["param"]["skillid"] == 77)
        self.assertLess(cast, names.index(("death", 100)))
        self.assertTrue(any(f["flag"] == "skill" and f["param"]["skillid"] == 78 for f in frames[:cast + 3]))

    def test_revive_on_death_reenters_with_hp(self):
        rebirth = skill([{"op": "revive", "scale": 50}], trigger="on_death", once=True)
        winer, frames = run([unit(0, patk=1000)], [unit(100, hp=100, patk=0, skills=[rebirth])])
        self.assertEqual(winer, WIN)
        self.assertEqual(flags(frames, "death").count(100), 2)
        reenter = frames.index({"flag": "reenter", "param": {"src": 100}})
        self.assertEqual(frames[reenter + 1]["param"], {"100": {"maxHp": 100, "tempHp": 50}})

    def test_invincible_hits_block_whole_hits(self):
        ward = skill([{"op": "invincible", "target": "self", "hits": 2}], trigger="before_battle")
        _, frames = run([unit(0)], [unit(100, hp=10**6, patk=0, skills=[ward])])
        hurts = [p["hurt"] for p in flags(frames, "attack") if p["src"] == 0][:3]
        self.assertEqual(hurts, [0, 0, 100])

    def test_execute_spares_targets_above_the_threshold(self):
        reap = skill([{"op": "execute", "target": "target", "below": 50}])
        winer, _ = run([unit(0, patk=0, skills=[reap])], [unit(100, hp=1000, patk=0)])
        self.assertEqual(winer, LOSS)  # a full-HP target is never below 50%


if __name__ == "__main__":
    unittest.main()
