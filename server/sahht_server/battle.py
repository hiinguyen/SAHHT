"""Battle engine: runs a fight with hero skills and records it as client frames.

The client never computes a battle; it plays back the frames this module
returns (`game_battle_scene.lua`). Frame shapes used here:

- `sort` [positions in acting order], once per round
- `attack` {src, des, hurt}: a normal attack (script `skill1`)
- `skill` {src, des: [...], hurt: [...], desh: [...], health: [...], name, skillid}:
  `name` is the script `skill_effect/<animation>/<name>.lua`
- `buff_skill` {src, des, name, hurt}: a damage-over-time tick
- `add_buff` / `remove_buff` {src, name}: status art (`skill_effect/buff/<name>.lua`)
- `cur_data` {pos: {maxHp, tempHp}}: authoritative HP after every action
- `death` pos, `reenter` {src} (revive), and finally `winer`

Rules are documented in SKILLS.md ("Battle rules the engine applies").
"""

import random
from dataclasses import dataclass, field

from .battle_unit import Buff, Dot, Unit
from .battle_art import (CONTROL_ART, CRIT_MULTIPLIER, DOT_ART, DOT_TICK_ART, GENERIC_ART,
                         HEAL_ART, INVINCIBLE_ART, MISS_ART, SHIELD_ART, STAT_ART, buff_art)
from .leader_battle import LeaderCasts

MAX_ROUNDS = 30          # the battle scene shows "round n/30"
WIN, LOSS = 1, 10        # the client treats winer < 5 as a win
MIN_HIT_CHANCE = 5
FOREVER = 10**6
NORMAL_ATTACK = {"op": "damage", "target": "target", "scale": 100}

# Formation cells a..f: a, b, c are the front column, d, e, f the back; a/d, b/e, c/f share a lane.
CELLS = ("position_a", "position_b", "position_c", "position_d", "position_e", "position_f")
DEFAULT_FORMATION = {"position_a": 0, "position_b": 1, "position_c": 2,
                     "position_d": 3, "position_e": 4, "position_f": 5}

def formation_layout(formation: dict) -> dict:
    """slot -> (row, lane) the way the battle scene places units: the cells whose
    formation value is non-zero, in a..f order, are slots 0..4."""
    cells = [i for i, key in enumerate(CELLS) if formation.get(key, 0) != 0][:5]
    return {slot: (cell // 3, cell % 3) for slot, cell in enumerate(cells)}


@dataclass
class Cast:
    """One action being resolved: a skill, a normal attack, or a reaction."""
    caster: Unit
    skill: object = None            # Skill, or None for a normal attack
    slot: int = 0
    target: Unit = None             # the attacker / killer / unit hit, for triggered skills
    normal: bool = False            # the triggering attack was a normal attack
    taken: int = 0                  # damage the caster just took (counters)
    depth: int = 0                  # reactions do not trigger further reactions
    primary: list = field(default_factory=list)
    last_hit: list = field(default_factory=list)
    hurt: dict = field(default_factory=dict)       # pos -> damage this cast
    heal: dict = field(default_factory=dict)       # pos -> healing this cast
    touched: list = field(default_factory=list)    # positions affected, in order
    changed: set = field(default_factory=set)      # positions whose HP changed
    art: list = field(default_factory=list)        # (pos, buff script)
    revived: list = field(default_factory=list)
    dealt: int = 0

    def value(self, v) -> float:
        return self.skill.value(v) if self.skill else float(v)

    def touch(self, unit: Unit):
        if unit.pos not in self.touched:
            self.touched.append(unit.pos)

    @property
    def root(self) -> int:
        return self.skill.root if self.skill else 0


class Battle(LeaderCasts):
    def __init__(self, units, rng=None, script=None, layouts=None, leaders=(), mods=None):
        self.units = units
        self.rng = rng or random.Random()
        self.script = script or (lambda unit, skill, slot: "skill1")
        default = formation_layout(DEFAULT_FORMATION)
        self.layouts = layouts or (default, default)
        self.frames = []
        self.round = 1
        self._init_leaders(leaders, mods)

    def run(self):
        self._apply_passives()
        self._before_battle()
        for self.round in range(1, MAX_ROUNDS + 1):
            if self._over():
                break
            order = self._acting_order()
            self.emit("sort", [u.pos for u in order])
            if self.leaders:
                self.emit("anger", {"src": 0, "value": self.rage})
            self._round_start()
            if not self._over():
                self._leader_cast()
            for unit in order:
                if self._over():
                    break
                self._take_turns(unit)
            self._round_end()
        winer = WIN if self._alive(True) and not self._alive(False) else LOSS
        self.emit("winer", winer)
        return winer, self.frames

    # ---- frames ----------------------------------------------------------

    def emit(self, flag, param):
        self.frames.append({"flag": flag, "param": param})

    def _emit_hp(self, positions):
        units = [u for u in self.units if u.pos in positions]
        if units:
            self.emit("cur_data", {str(u.pos): {"maxHp": u.max_hp, "tempHp": u.hp} for u in units})

    def _emit_art(self, art):
        for pos, name in dict.fromkeys(art):
            self.emit("add_buff", {"src": pos, "name": name})

    # ---- unit queries ----------------------------------------------------

    def _alive(self, attacker_side, dead=False):
        return sorted((u for u in self.units if u.attacker_side == attacker_side
                       and (u.dead if dead else u.alive)), key=lambda u: u.pos)

    def _over(self):
        return not self._alive(True) or not self._alive(False)

    def _acting_order(self):
        return sorted((u for u in self.units if u.alive),
                      key=lambda u: (-u.stat("speed"), u.pos))

    def _unit(self, pos):
        return next(u for u in self.units if u.pos == pos)

    def _cell(self, unit):
        layout = self.layouts[0 if unit.attacker_side else 1]
        return layout.get(unit.pos % 100, (0, unit.pos % 100))

    def _row(self, units, row):
        return [u for u in units if self._cell(u)[0] == row] or units

    def _select(self, caster, selector, count, cast):
        """Living units a selector names, relative to the caster."""
        if selector == "self":
            return [caster] if caster.alive else []
        if selector == "target":
            units = cast.primary if cast.skill and cast.skill.trigger == "active" else [cast.target]
            return [u for u in units if u is not None and u.alive]
        if selector == "hit":
            return [u for u in cast.last_hit if u.alive]
        side = caster.attacker_side != selector.startswith("enemy_")
        if selector == "ally_dead":
            return self._alive(side, dead=True)
        return self._pick(self._alive(side), selector.split("_", 1)[1], count, caster)

    def _pick(self, pool, how, count, caster):
        if not pool:
            return []
        rank = {"lowest_hp": lambda u: u.hp_pct, "highest_hp": lambda u: -u.hp_pct,
                "highest_atk": lambda u: -u.attack, "fastest": lambda u: -u.stat("speed")}
        if how in rank:
            return [min(pool, key=rank[how])]
        if how == "all":
            return pool
        if how == "others":
            return [u for u in pool if u is not caster]
        if how == "random":
            return self.rng.sample(pool, min(count, len(pool)))
        if how == "back":
            return self._row(pool, 1)[:1]
        if how in ("row_front", "row_back"):
            return self._row(pool, 0 if how == "row_front" else 1)
        if how == "line":
            lane = self._cell(pool[0])[1]
            return pool[:1] + [u for u in pool[1:] if self._cell(u)[1] == lane][:1]
        return pool[:1]  # front

    # ---- conditions ------------------------------------------------------

    def _holds(self, conds, unit, cast):
        conds = conds if isinstance(conds, list) else [conds] if conds else []
        return all(self._condition(c, unit, cast) for c in conds)

    def _condition(self, cond, unit, cast):
        name, _, arg = cond.partition(":")
        caster = cast.caster
        # target_* tests look at the unit the effect lands on, or at the cast's
        # primary target when the effect lands on the caster's own side.
        if unit is None or unit.attacker_side == caster.attacker_side:
            unit = (cast.primary or [cast.target])[0] if (cast.primary or cast.target) else unit
        def has_target():
            return unit is not None and unit is not caster
        tests = {
            "target_has": lambda: has_target() and unit.has(arg),
            "target_lacks": lambda: not has_target() or not unit.has(arg),
            "self_has": lambda: caster.has(arg),
            "self_state": lambda: arg in caster.states,
            "self_lacks_state": lambda: arg not in caster.states,
            "target_boss": lambda: has_target() and unit.boss,
            "target_not_boss": lambda: not has_target() or not unit.boss,
            "target_race": lambda: has_target() and unit.race == int(arg),
            "target_not_race": lambda: not has_target() or unit.race != int(arg),
            "enemy_has_race": lambda: any(u.race == int(arg)
                                          for u in self._alive(not caster.attacker_side)),
            "ally_has_race": lambda: any(u.race == int(arg)
                                         for u in self._alive(caster.attacker_side)),
            "ally_lacks_race": lambda: not any(u.race == int(arg)
                                               for u in self._alive(caster.attacker_side)),
            "target_hp_below": lambda: has_target() and unit.hp_pct < float(arg),
            "target_hp_above": lambda: has_target() and unit.hp_pct > float(arg),
            "self_hp_below": lambda: caster.hp_pct < float(arg),
            "self_hp_above": lambda: caster.hp_pct > float(arg),
            "round_ge": lambda: self.round >= int(arg),
            "round_le": lambda: self.round <= int(arg),
            "target_atk_higher": lambda: has_target() and unit.attack > caster.attack,
            "target_atk_lower": lambda: has_target() and unit.attack < caster.attack,
            "target_speed_higher": lambda: has_target()
            and unit.stat("speed") > caster.stat("speed"),
            "target_count": lambda: len(cast.last_hit) in {int(n) for n in arg.split(",")},
            "normal_attack": lambda: cast.normal,
        }
        return tests[name]()

    # ---- battle and round flow -------------------------------------------

    def _apply_passives(self):
        for unit in self.units:
            for slot, skill in unit.skills:
                if skill.trigger != "passive":
                    continue
                cast = Cast(unit, skill, slot)
                for index, effect in enumerate(skill.effects):
                    if effect.get("op") == "buff":
                        for target in self._targets(cast, effect):
                            self._buff(cast, effect, index, target, rounds=0)

    def _before_battle(self):
        """Pre-battle skills play as ordinary skill frames before round 1.

        Not as a `pre_battle` frame: with any skill in it the client loads
        ccbResources/pre_battle_bg_res.plist, which this APK lacks, and the
        native engine crashes. Depth 1: pre-battle damage provokes no counters.
        """
        for unit in self._acting_order():
            for slot, skill in unit.skills:
                if skill.trigger == "before_battle" and self._ready(unit, skill):
                    self._perform(Cast(unit, skill, slot, depth=1))

    def _round_start(self):
        for unit in self._acting_order():
            self._tick_dots(unit)
        for unit in self._acting_order():
            for slot, skill in unit.skills:
                if unit.alive and skill.trigger == "before_round" and self._ready(unit, skill):
                    self._perform(Cast(unit, skill, slot))

    def _tick_dots(self, unit):
        for dot in list(unit.dots):
            amount = 0 if unit.has("invincible") else min(unit.hp, dot.amount)
            unit.hp -= amount
            dot.rounds -= 1
            unit.dots = [d for d in unit.dots if d is not dot or d.rounds > 0]
            self.emit("buff_skill", {"src": unit.pos, "des": unit.pos,
                                     "name": DOT_TICK_ART[dot.kind], "hurt": amount})
            self._emit_hp({unit.pos})
            if unit.hp <= 0:
                self._die(unit, None, depth=0)  # clears the DoTs; a revive starts clean
                return

    def _round_end(self):
        for unit in self.units:
            for buff in unit.end_round():
                self.emit("remove_buff", {"src": unit.pos, "name": buff_art(buff.stat, buff.value)})

    def _take_turns(self, unit):
        if unit.attacker_side:
            self._gain_rage(10)   # an ally acted
        self._turn(unit)
        while unit.extra_actions > 0 and unit.alive and not self._over():
            unit.extra_actions -= 1
            self._turn(unit)

    def _turn(self, unit):
        if not unit.alive:
            return
        if unit.skips_turn():
            unit.spend_control_turn()
            return
        if unit.confused():
            unit.spend_control_turn()
            allies = [u for u in self._alive(unit.attacker_side) if u is not unit]
            if allies:
                self._normal_attack(unit, self.rng.choice(allies))
            return
        silenced = unit.silenced()
        unit.spend_control_turn()
        if not silenced:
            for slot, skill in unit.skills:
                if skill.trigger == "active" and self._ready(unit, skill) and self._roll_rate(skill):
                    self._perform(Cast(unit, skill, slot))
                    return
        enemies = self._alive(not unit.attacker_side)
        if enemies:
            self._normal_attack(unit, enemies[0])

    # ---- skill timers ----------------------------------------------------

    def _ready(self, unit, skill):
        if not unit.alive and skill.trigger != "on_death":
            return False
        first, last = skill.rounds
        if not first <= self.round <= last or skill.id in unit.used_once:
            return False
        if unit.ready_round.get(skill.id, 1 + skill.pre_cd) > self.round:
            return False
        return not (skill.limit_per_round and unit.fired.get(skill.id, 0) >= skill.limit_per_round)

    def _roll_rate(self, skill):
        # A rate of 0 marks skills whose original scripts fired unconditionally.
        return skill.rate <= 0 or self.rng.random() * 100 < skill.rate

    def _mark_used(self, unit, skill):
        unit.ready_round[skill.id] = self.round + skill.cd
        unit.fired[skill.id] = unit.fired.get(skill.id, 0) + 1
        if skill.once:
            unit.used_once.add(skill.id)

    def _react(self, unit, trigger, other, taken=0, normal=False, depth=0):
        """Fire the unit's skills of a reactive trigger (never from inside a reaction)."""
        if depth > 0:
            return
        for slot, skill in unit.skills:
            if skill.trigger == trigger and self._ready(unit, skill) and self._roll_rate(skill):
                self._perform(Cast(unit, skill, slot, target=other, normal=normal,
                                   taken=taken, depth=depth + 1))

    # ---- casting ---------------------------------------------------------

    def _normal_attack(self, unit, target):
        magic = unit.stat("matk") > unit.stat("patk")
        cast = Cast(unit, None, 0, target=target, normal=True, primary=[target])
        self._op_damage(cast, dict(NORMAL_ATTACK, type="magic" if magic else "phys"), 0, target)
        if not unit.alive:          # killed by a counter before the blow landed
            self._emit_hp(cast.changed)
            self._settle_deaths(cast)
            return
        self.emit("attack", {"src": unit.pos, "des": target.pos,
                             "hurt": cast.hurt.get(target.pos, 0)})
        self._finish(cast)

    def _perform(self, cast):
        """Cast a skill: resolve its effects, then emit its frame and settle the results."""
        self._resolve(cast)
        if not cast.caster.alive and cast.skill.trigger != "on_death":
            self._emit_hp(cast.changed)
            self._settle_deaths(cast)
            return
        self._emit_skill(cast)
        self._finish(cast)

    def _resolve(self, cast):
        skill = cast.skill
        self._mark_used(cast.caster, skill)
        if skill.trigger == "active":
            cast.primary = self._select(cast.caster, skill.aim, skill.count, cast)
        for index, effect in enumerate(skill.effects):
            if not cast.caster.alive and not (skill.trigger == "on_death"
                                              and effect.get("op") == "revive"):
                if skill.trigger != "on_death":
                    break
            self._apply(cast, effect, index)
        return cast

    def _emit_skill(self, cast):
        caster = cast.caster
        enemies = [p for p in cast.touched if (p < 100) != caster.attacker_side]
        healed = [p for p, n in cast.heal.items() if n > 0]  # a heal at full HP shows nothing
        param = {"src": caster.pos, "name": self.script(caster, cast.skill, cast.slot),
                 "skillid": cast.skill.id}
        if enemies:
            param["des"] = enemies
            param["hurt"] = [cast.hurt.get(p, 0) for p in enemies]
        if healed or not enemies:
            # Buff-only skills show the cast on the allies they touched, or on the caster.
            desh = healed or [p for p in cast.touched if p not in enemies] or [caster.pos]
            param["desh"] = desh
            param["health"] = [cast.heal.get(p, 0) for p in desh]
        self.emit("skill", param)

    def _finish(self, cast):
        """HP sync, status art, deaths, revives, then after-hit and on-attack reactions."""
        for unit in cast.revived:
            self.emit("reenter", {"src": unit.pos})
        self._emit_hp(cast.changed | {u.pos for u in cast.revived})
        self._emit_art(cast.art)
        self._settle_deaths(cast)
        if cast.depth > 0:
            return
        caster = cast.caster
        victims = [self._unit(p) for p in cast.hurt if (p < 100) != caster.attacker_side]
        for victim in victims:
            if victim.alive and caster.alive:
                self._react(victim, "after_hit", caster, cast.hurt[victim.pos], cast.normal)
        if victims and caster.alive:
            self._react(caster, "on_attack", victims[0], normal=cast.normal)

    def _settle_deaths(self, cast):
        for unit in self.units:
            if unit.hp <= 0 and not unit.dead:
                self._die(unit, cast.caster, cast.depth)

    def _die(self, unit, killer, depth):
        unit.hp = 0
        unit.dead = True
        unit.dots, unit.controls = [], {}
        self.emit("death", unit.pos)
        for slot, skill in unit.skills:
            if skill.trigger == "on_death" and self._ready(unit, skill) and self._roll_rate(skill):
                self._perform(Cast(unit, skill, slot, target=killer, depth=depth + 1))

    # ---- effects ---------------------------------------------------------

    def _targets(self, cast, effect):
        selector = effect.get("target", "self")
        units = self._select(cast.caster, selector, effect.get("count", 1), cast)
        if "count" in effect and selector not in ("enemy_random", "ally_random"):
            units = units[:effect["count"]]
        chance = effect.get("chance")
        return [u for u in units
                if self._holds(effect.get("if"), u, cast)
                and (chance is None or self.rng.random() * 100 < cast.value(chance))]

    def _apply(self, cast, effect, index):
        op = effect["op"]
        if op == "rage":
            return  # leader rage: leader skills are not implemented yet
        if op == "revive":
            self._revive(cast, effect)
            return
        if op == "damage":
            cast.last_hit = []
        handler = getattr(self, f"_op_{op}")
        for target in self._targets(cast, effect):
            handler(cast, effect, index, target)

    def _op_damage(self, cast, effect, index, target):
        caster = cast.caster
        if not target.alive or not caster.alive:
            return
        if target.attacker_side != caster.attacker_side:
            self._react(target, "before_hit", caster, normal=cast.normal, depth=cast.depth)
            if not caster.alive or not target.alive:
                return
        cast.touch(target)
        cast.last_hit.append(target)
        amount = self._damage_amount(cast, effect, target)
        if amount is None:
            cast.art.append((target.pos, MISS_ART))
            cast.hurt.setdefault(target.pos, 0)
            return
        self._hurt(cast, target, amount)

    def _damage_amount(self, cast, effect, target):
        """Final damage of one hit, or None for a miss."""
        caster = cast.caster
        kind = effect.get("type", "phys")
        # `sure_hit` skips the hit roll ("chắc chắn trúng"); passive element damage does not roll.
        if caster.attacker_side != target.attacker_side and not effect.get("sure_hit"):
            hit = max(MIN_HIT_CHANCE, caster.stat("hit") - target.stat("dodge"))
            if self.rng.random() * 100 >= hit:
                return None
        raw = self._stat_amount(cast, effect.get("stat"), kind, target) * cast.value(effect["scale"]) / 100
        for bonus in effect.get("bonus", ()):
            if self._holds(bonus.get("if"), target, cast):
                raw *= 1 + cast.value(bonus["pct"]) / 100
        if kind != "true" and raw > 0:
            ignore = min(100.0, cast.value(effect.get("ignore_def", 0)))
            defense = target.stat("def") * (1 - ignore / 100)
            raw = raw * raw / (raw + defense)
        crit = effect.get("crit")
        crit_chance = caster.stat("crit") + cast.value(effect.get("crit_bonus", 0))
        if crit == "always" or (crit != "never" and self.rng.random() * 100 < crit_chance):
            raw *= CRIT_MULTIPLIER
        raw *= max(0.0, 1 + caster.stat("dmg_dealt") / 100) * max(0.0, 1 + target.stat("dmg_taken") / 100)
        # "Giảm thương" (subhurt) is percentage points of the final damage, like dmg_taken.
        raw *= max(0.0, 1 - target.stat("subhurt") / 100)
        return max(1, round(raw))

    def _op_attr_damage(self, cast, effect, index, target):
        """Element damage: scale% of the caster's element attack minus the target's defense."""
        if not target.alive or not cast.caster.alive:
            return
        element = effect["element"]
        if element == "own":
            element = cast.caster.own_element()
        raw = cast.caster.element_atk(element) * cast.value(effect["scale"]) / 100
        amount = round(raw - target.element_dfs(element))
        cast.touch(target)
        if amount > 0:
            self._hurt(cast, target, amount)
        else:
            cast.hurt.setdefault(target.pos, 0)

    @staticmethod
    def _stat_amount(cast, stat, kind, target):
        caster = cast.caster
        stat = stat or ("matk" if kind == "magic" else "patk")
        values = {
            "max_hp": lambda: caster.max_hp, "hp_lost": lambda: caster.max_hp - caster.hp,
            "target_max_hp": lambda: target.max_hp, "target_hp": lambda: target.hp,
            "target_def": lambda: target.stat("def"), "damage_taken": lambda: cast.taken,
        }
        return values[stat]() if stat in values else caster.stat(stat)

    def _hurt(self, cast, target, amount):
        """Apply damage through invincibility and shields; lifesteal and reflect follow."""
        if target.invincible_rounds > 0:
            amount = 0
        elif target.invincible_hits > 0:
            target.invincible_hits -= 1
            amount = 0
        absorbed = min(target.shield, amount)
        target.shield -= absorbed
        amount = min(target.hp, amount - absorbed)
        target.hp -= amount
        if amount:
            target.controls.pop("sleep", None)
        cast.hurt[target.pos] = cast.hurt.get(target.pos, 0) + amount
        cast.changed.add(target.pos)
        caster = cast.caster
        if caster.attacker_side == target.attacker_side:
            return
        if target.attacker_side:
            self._ally_hit_rage()
        cast.dealt += amount
        steal = round(amount * caster.stat("lifesteal") / 100)
        if steal > 0 and caster.alive:
            self._restore(cast, caster, steal)
        back = min(caster.hp, round(amount * target.stat("reflect") / 100))
        if back > 0 and caster.alive:
            caster.hp -= back
            cast.changed.add(caster.pos)

    @staticmethod
    def _restore(cast, unit, amount):
        amount = round(amount * max(0.0, 1 + unit.stat("heal_taken") / 100))
        amount = max(0, min(unit.max_hp - unit.hp, amount))
        unit.hp += amount
        cast.heal[unit.pos] = cast.heal.get(unit.pos, 0) + amount
        cast.changed.add(unit.pos)
        cast.touch(unit)

    def _op_heal(self, cast, effect, index, target):
        of = effect["of"]
        base = {"max_hp": target.max_hp, "lost_hp": target.max_hp - target.hp,
                "damage": cast.dealt}.get(of)
        if base is None:
            base = cast.caster.stat(of)
        self._restore(cast, target, base * cast.value(effect["scale"]) / 100)
        cast.art.append((target.pos, HEAL_ART))

    def _buff(self, cast, effect, index, target, rounds=None):
        value = cast.value(effect["value"])
        target.add_buff(Buff(key=(cast.caster.pos, cast.root, index), stat=effect["stat"],
                             value=value, rounds=effect["rounds"] if rounds is None else rounds,
                             max_stack=max(1, effect.get("max_stack", 1))))
        cast.changed.add(target.pos)  # max_hp buffs move HP
        return buff_art(effect["stat"], value)

    def _op_buff(self, cast, effect, index, target):
        cast.touch(target)
        cast.art.append((target.pos, self._buff(cast, effect, index, target)))

    def _op_control(self, cast, effect, index, target):
        cast.touch(target)
        if target.immune_to_control():
            return
        kind = effect["kind"]
        target.controls[kind] = max(target.controls.get(kind, 0), max(1, effect["rounds"]))
        cast.art.append((target.pos, CONTROL_ART[kind]))

    def _op_dot(self, cast, effect, index, target):
        cast.touch(target)
        of = effect["of"]
        base = target.max_hp if of == "target_max_hp" else cast.caster.stat(of)
        amount = max(1, round(base * cast.value(effect["scale"]) / 100))
        key = (cast.caster.pos, cast.root, index)
        target.dots = [d for d in target.dots if d.key != key]
        target.dots.append(Dot(key, effect["kind"], amount, max(1, effect["rounds"])))
        cast.art.append((target.pos, DOT_ART[effect["kind"]]))

    def _op_shield(self, cast, effect, index, target):
        of = effect["of"]
        base = target.max_hp if of == "max_hp" else cast.caster.stat(of)
        target.shield = max(target.shield, round(base * cast.value(effect["scale"]) / 100))
        target.shield_rounds = effect.get("rounds") or FOREVER
        cast.touch(target)
        cast.art.append((target.pos, SHIELD_ART))

    def _op_invincible(self, cast, effect, index, target):
        if effect.get("hits"):
            target.invincible_hits = max(target.invincible_hits, effect["hits"])
        else:
            target.invincible_rounds = max(target.invincible_rounds, effect.get("rounds") or 1)
        cast.touch(target)
        cast.art.append((target.pos, INVINCIBLE_ART))

    def _op_immune_control(self, cast, effect, index, target):
        if effect.get("times"):
            target.immune_times = max(target.immune_times, effect["times"])
        else:
            target.immune_rounds = max(target.immune_rounds, effect.get("rounds") or FOREVER)
        cast.touch(target)

    def _op_dispel(self, cast, effect, index, target):
        what = effect["what"]
        if what in ("debuffs", "all"):
            target.clear_debuffs()
        if what in ("buffs", "all"):
            target.clear_buffs()
        cast.touch(target)
        cast.changed.add(target.pos)

    def _revive(self, cast, effect):
        selector = effect.get("target", "self")
        if selector == "self":
            candidates = [cast.caster] if cast.caster.dead else []
        else:
            candidates = self._select(cast.caster, selector, effect.get("count", 1), cast)
            candidates = candidates[:effect["count"]] if "count" in effect else candidates
        for unit in candidates:
            unit.dead = False
            unit.hp = max(1, round(unit.max_hp * cast.value(effect["scale"]) / 100))
            unit.clear_debuffs()
            cast.revived.append(unit)

    def _op_execute(self, cast, effect, index, target):
        if target.hp_pct < cast.value(effect["below"]) and not target.has("invincible"):
            cast.touch(target)
            self._hurt(cast, target, target.hp)

    def _op_hp_cost(self, cast, effect, index, target):
        base = target.max_hp if effect["of"] == "max_hp" else target.hp
        loss = min(target.hp - 1, round(base * cast.value(effect["scale"]) / 100))
        if loss > 0:
            target.hp -= loss
            cast.changed.add(target.pos)

    def _op_state(self, cast, effect, index, target):
        target.states[effect["name"]] = effect["rounds"]

    def _op_extra_action(self, cast, effect, index, target):
        target.extra_actions += 1


def build_unit(data: dict) -> Unit:
    """A Unit from the plain dict the campaign builds (see campaign._attackers)."""
    base = {k: data.get(k, 0) for k in ("hp", "patk", "matk", "def", "speed")}
    base.update(crit=data.get("crit", 0), hit=data.get("hit", 100),
                dodge=data.get("dodge", 0), subhurt=data.get("subhurt", 0))
    return Unit(pos=data["pos"], base=base, hp=data["hp"], animation=data.get("animation", ""),
                boss=bool(data.get("boss")), race=data.get("race", -1),
                elements=data.get("elements", {}), element_def=data.get("element_def", {}),
                skills=list(data.get("skills", ())))


def simulate(attackers: list, defenders: list, rng=None, script=None, layouts=None,
             leaders=(), mods=None):
    """Resolve a fight; returns (winer, frames) in the battle scene's playback format.

    Attackers sit at positions 0-4, defenders at 100-104. `script(unit, skill, slot)`
    names the client animation for a skill; `layouts` is (attacker, defender)
    `formation_layout` maps. `leaders` are the attacker side's leader skills and `mods`
    its learned passive nodes (`leader_passives.LeaderMods`).
    """
    units = [build_unit(u) for u in attackers + defenders]
    return Battle(units, rng=rng, script=script, layouts=layouts, leaders=leaders,
                  mods=mods).run()
