"""Leader skills inside a battle: the rage bar, the casts, and what passive nodes add.

`Battle` mixes this in. The player's side has a rage bar (0..100): +10 when an ally acts,
+5 when an ally is hit. At the start of a round, the first equipped skill that is off
cooldown casts once the bar holds its rage cost (100, less what passives cut), emitting a
`skill_hero` frame. These are server rules: the client has no formula for any of them.
"""

from .battle_art import CONTROL_ART, CRIT_MULTIPLIER, DOT_ART, buff_art
from .battle_unit import Buff, Dot
from .leader_passives import LeaderMods
from .leader_skill import RAGE_MAX


class LeaderCasts:
    def _init_leaders(self, leaders, mods):
        self.leaders = list(leaders)
        self.mods = mods or LeaderMods()
        start = round(self.mods.total("rage_start")) if self.leaders else 0
        self.rage = max(0, min(RAGE_MAX, start))
        self.leader_ready = {skill.id: skill.ready_time + 1 for skill in self.leaders}

    def _roll(self, chance: float) -> bool:
        return chance > 0 and self.rng.random() * 100 < chance

    # ---- rage ------------------------------------------------------------

    def _gain_rage(self, amount):
        if self.leaders:
            self.rage = min(RAGE_MAX, self.rage + amount)

    def _ally_hit_rage(self):
        self._gain_rage(5)
        if self._roll(self.mods.total("rage_on_hit")):
            self._gain_rage(1)

    def _rage_cost(self, skill) -> int:
        return max(0, RAGE_MAX - int(self.mods.total("rage_cost", skill)))

    def _spend_rage(self, skill):
        if not self._roll(self.mods.total("free_cast", skill)):
            self.rage = max(0, self.rage - self._rage_cost(skill))
        self.rage = max(self.rage, min(RAGE_MAX, round(self.mods.keep_rage())))

    # ---- casting ---------------------------------------------------------

    def _leader_cast(self):
        """Cast the first equipped leader skill that is off cooldown, if the rage is there."""
        skill = next((s for s in self.leaders if self.round >= self.leader_ready[s.id]), None)
        if skill is None or self.rage < self._rage_cost(skill):
            return
        hurt, touched, arts = {}, [], []
        for effect in skill.effects:
            self._leader_effect(skill, effect, hurt, touched, arts)
        if not touched:
            return
        self.emit("skill_hero", {"src": 0, "name": skill.script, "skillid": skill.id,
                                 "des": touched, "hurt": [hurt.get(p, 0) for p in touched]})
        self._emit_hp(set(touched))
        self._emit_art(arts)
        for unit in self.units:
            if unit.hp <= 0 and not unit.dead:
                self._die(unit, None, 0)
        self._spend_rage(skill)
        self.leader_ready[skill.id] = self.round + skill.cd

    def _leader_effect(self, skill, effect, hurt, touched, arts):
        targets = self._leader_targets(effect.get("target", skill.aim), skill)
        if effect["op"] == "damage":
            self._leader_damage(skill, effect, targets, hurt, touched, arts)
            return
        for target in targets:
            if target.immune_to_control():
                continue
            target.controls[effect["kind"]] = max(1, int(effect.get("rounds", 1)))
            arts.append((target.pos, CONTROL_ART[effect["kind"]]))

    def _leader_damage(self, skill, effect, targets, hurt, touched, arts):
        base = self._leader_stat(effect["stat"]) * skill.value(effect["scale"]) / 100
        targets, shrink = self._leader_reach(skill, targets)
        falloff = max(0.0, effect.get("falloff", 0) - self.mods.total("falloff_down", skill))
        for order, target in enumerate(targets):
            factor = ((1 + self.mods.damage_pct(skill, target) / 100) * (1 - shrink / 100)
                      * (1 - falloff / 100) ** order)
            if self._roll(self.mods.total("crit_chance", skill)):
                factor *= CRIT_MULTIPLIER + self.mods.total("crit_damage", skill) / 100
            amount = self._leader_hurt(target, round(base * factor))
            amount += self._leader_bonus(skill, target)
            if target.pos not in touched:
                touched.append(target.pos)
            hurt[target.pos] = hurt.get(target.pos, 0) + amount
            if target.hp > 0:
                self._leader_afflict(skill, target, arts)
        self._leader_rally(skill, arts)

    def _leader_reach(self, skill, targets):
        """The hit list after passives add targets, and the damage cut that costs each hit."""
        pool = [u for u in self._alive(False) if u not in targets]
        extra = max(self.mods.effects("extra_targets", skill),
                    key=lambda e: e.params["count"], default=None)
        shrink = 0.0
        if extra is not None:
            count = extra.params["count"]
            targets, pool = targets + pool[:count], pool[count:]
            shrink = max(0.0, extra.value * extra.params["reduction_scale"])
        if pool and self._roll(self.mods.total("extra_hit", skill)):
            targets = targets + [self.rng.choice(pool)]
        return targets, shrink

    def _leader_bonus(self, skill, target) -> int:
        """Extra hits some passives add on top of a hit: a share of a stat, by chance."""
        total = 0
        for effect in self.mods.effects("bonus_damage", skill):
            if self._roll(effect.value):
                share = self.rng.uniform(effect.params["low"], effect.params["high"])
                total += self._leader_hurt(
                    target, round(self._leader_stat(effect.params["stat"]) * share / 100))
        return total

    def _leader_afflict(self, skill, target, arts):
        """Controls, slows, burns and attack cuts a passive leaves on a target that was hit."""
        mods = self.mods
        for effect in mods.effects("control_chance", skill):
            if self._roll(effect.value) and not target.immune_to_control():
                kind, (low, high) = effect.params["control"], effect.params["rounds"]
                target.controls[kind] = max(target.controls.get(kind, 0),
                                            self.rng.randint(low, high))
                arts.append((target.pos, CONTROL_ART[kind]))
        for effect in mods.effects("slow_chance", skill):
            if self._roll(effect.value):
                self._leader_debuff(skill, target, "speed", effect.params["pct"],
                                    effect.params["rounds"], arts)
        for effect in mods.effects("atk_down", skill):
            self._leader_debuff(skill, target, effect.params["stat"], effect.value,
                                effect.params["rounds"], arts)
        for effect in mods.effects("burn_chance", skill):
            if self._roll(effect.value):
                scale = effect.params["scale"] * (1 + mods.total("burn_up", skill) / 100)
                key = ("leader", skill.id, "burn")
                target.dots = [d for d in target.dots if d.key != key]
                target.dots.append(Dot(key, "burn", max(1, round(target.max_hp * scale / 100)),
                                       effect.params["rounds"]))
                arts.append((target.pos, DOT_ART["burn"]))

    @staticmethod
    def _leader_debuff(skill, target, stat, pct, rounds, arts):
        target.add_buff(Buff(key=("leader", skill.id, stat), stat=stat, value=-pct,
                             rounds=rounds))
        arts.append((target.pos, buff_art(stat, -pct)))

    def _leader_rally(self, skill, arts):
        """Passives that bless the whole side after a cast, by chance."""
        for effect in self.mods.effects("ally_buff_chance", skill):
            if not self._roll(effect.value):
                continue
            for ally in self._alive(True):
                for stat in effect.params["stats"]:
                    ally.add_buff(Buff(key=("leader", skill.id, stat), stat=stat,
                                       value=effect.params["pct"],
                                       rounds=effect.params["rounds"]))
                arts.append((ally.pos, buff_art(effect.params["stats"][0], effect.params["pct"])))

    # ---- targets and numbers ----------------------------------------------

    def _leader_targets(self, selector, skill):
        enemies = self._alive(False)
        allies = self._alive(True)
        if selector == "enemy_all":
            return enemies
        if selector == "enemy_random":
            return self.rng.sample(enemies, min(3, len(enemies)))
        if selector == "enemy_lowest_hp":
            return sorted(enemies, key=lambda u: u.hp_pct)[:1]
        if selector == "ally_all":
            return allies
        if selector == "ally_lowest_hp":
            return sorted(allies, key=lambda u: u.hp_pct)[:1]
        return enemies[:1]

    def _leader_stat(self, name):
        """The aggregate of one side's live units a leader skill scales from."""
        kind, how, stat = name.split("_", 2)
        pool = self._alive(True) if kind == "ally" else self._alive(False)
        values = [unit.stat(stat) for unit in pool] or [0]
        return max(values) if how == "max" else sum(values) / len(values)

    @staticmethod
    def _leader_hurt(target, amount):
        """Leader damage goes through invincibility and shields, like any other hit."""
        if target.invincible_rounds > 0:
            amount = 0
        elif target.invincible_hits > 0:
            target.invincible_hits -= 1
            amount = 0
        absorbed = min(target.shield, amount)
        target.shield -= absorbed
        amount = min(target.hp, amount - absorbed)
        target.hp -= amount
        return amount
