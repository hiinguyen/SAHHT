"""A fighter's state during one battle: stats, buffs, controls, DoTs and skill timers."""

from dataclasses import dataclass, field

# Stats a buff changes by percent of the base value; the rest are percentage points.
PERCENT_STATS = ("patk", "matk", "def", "speed", "max_hp", "attr_atk", "attr_def")
ALL_STATS = ("patk", "matk", "def", "speed")    # what an "all" buff raises
SKIP_TURN = ("stun", "freeze", "petrify", "sleep", "paralyze", "root", "fear")
CONFUSE = ("chaos", "charm")
DOT_KINDS = ("burn", "bleed", "poison")
ELEMENTS = ("fire", "water", "wind", "earth")


@dataclass
class Buff:
    key: tuple          # (caster pos, skill root, effect index): recasts refresh or stack
    stat: str
    value: float        # per stack
    rounds: int         # rounds left; 0 = until the battle ends
    stacks: int = 1
    max_stack: int = 1

    @property
    def total(self) -> float:
        return self.value * self.stacks


@dataclass
class Dot:
    key: tuple
    kind: str
    amount: int         # damage per tick
    rounds: int         # ticks left


@dataclass
class Unit:
    pos: int
    base: dict                      # hp, patk, matk, def, speed, crit, hit, dodge
    hp: int
    animation: str = ""
    boss: bool = False
    race: int = -1
    elements: dict = field(default_factory=dict)       # element -> attack
    element_def: dict = field(default_factory=dict)    # element -> defense
    skills: list = field(default_factory=list)         # (slot, Skill)
    dead: bool = False
    buffs: list = field(default_factory=list)
    dots: list = field(default_factory=list)
    controls: dict = field(default_factory=dict)       # kind -> own turns left
    states: dict = field(default_factory=dict)         # name -> rounds left (0 = battle)
    shield: int = 0
    shield_rounds: int = 0
    invincible_rounds: int = 0
    invincible_hits: int = 0
    immune_rounds: int = 0
    immune_times: int = 0
    ready_round: dict = field(default_factory=dict)    # skill id -> first round it may fire
    fired: dict = field(default_factory=dict)          # skill id -> times this round
    used_once: set = field(default_factory=set)
    extra_actions: int = 0

    @property
    def attacker_side(self) -> bool:
        return self.pos < 100

    @property
    def alive(self) -> bool:
        return not self.dead and self.hp > 0

    def stat(self, name: str) -> float:
        bonus = sum(b.total for b in self.buffs
                    if b.stat == name or (b.stat == "all" and name in ALL_STATS))
        if name in PERCENT_STATS:
            base = self.base.get("hp" if name == "max_hp" else name, 0)
            return max(0.0, base * (1 + bonus / 100))
        return self.base.get(name, 0) + bonus

    @property
    def max_hp(self) -> int:
        return max(1, int(self.stat("max_hp")))

    @property
    def hp_pct(self) -> float:
        return 100 * self.hp / self.max_hp

    @property
    def attack(self) -> float:
        return max(self.stat("patk"), self.stat("matk"))

    def element_atk(self, element: str) -> float:
        if element == "own":
            element = max(ELEMENTS, key=lambda e: self.elements.get(e, 0))
        return self.elements.get(element, 0) * (1 + self.stat("attr_atk") / 100)

    def element_dfs(self, element: str) -> float:
        if element == "own":
            return 0
        return self.element_def.get(element, 0) * (1 + self.stat("attr_def") / 100)

    def has(self, status: str) -> bool:
        checks = {
            "control": lambda: bool(self.controls),
            "debuff": lambda: bool(self.controls or self.dots
                                   or any(b.total < 0 for b in self.buffs)),
            "buff": lambda: any(b.total > 0 for b in self.buffs),
            "shield": lambda: self.shield > 0,
            "invincible": lambda: self.invincible_rounds > 0 or self.invincible_hits > 0,
        }
        if status in checks:
            return checks[status]()
        if status in DOT_KINDS:
            return any(d.kind == status for d in self.dots)
        return status in self.controls

    def skips_turn(self) -> bool:
        return any(kind in self.controls for kind in SKIP_TURN)

    def confused(self) -> bool:
        return any(kind in self.controls for kind in CONFUSE)

    def silenced(self) -> bool:
        return "silence" in self.controls

    def spend_control_turn(self):
        """Controls last a number of the victim's own turns."""
        self.controls = {k: t - 1 for k, t in self.controls.items() if t > 1}

    def immune_to_control(self) -> bool:
        if self.immune_rounds > 0:
            return True
        if self.immune_times > 0:
            self.immune_times -= 1
            return True
        return False

    def add_buff(self, buff: Buff):
        """Same source refreshes (and stacks up to max_stack); max_hp changes move hp too."""
        before = self.max_hp
        for current in self.buffs:
            if current.key == buff.key:
                current.rounds = buff.rounds
                current.stacks = min(current.max_stack, current.stacks + 1)
                break
        else:
            self.buffs.append(buff)
        self._follow_max_hp(before)

    def remove_buffs(self, keep) -> list:
        """Drop buffs for which keep(buff) is false; returns the dropped ones."""
        before = self.max_hp
        dropped = [b for b in self.buffs if not keep(b)]
        self.buffs = [b for b in self.buffs if keep(b)]
        self._follow_max_hp(before)
        return dropped

    def _follow_max_hp(self, before: int):
        after = self.max_hp
        if after > before and self.alive:
            self.hp += after - before
        self.hp = min(self.hp, after)

    def end_round(self) -> list:
        """Count down everything that lasts in rounds; returns expired buffs."""
        expired = self.remove_buffs(lambda b: b.rounds != 1)
        for b in self.buffs:
            if b.rounds > 1:
                b.rounds -= 1
        self.states = {k: (0 if r == 0 else r - 1) for k, r in self.states.items() if r != 1}
        self.shield_rounds = max(0, self.shield_rounds - 1)
        if self.shield_rounds == 0:
            self.shield = 0
        self.invincible_rounds = max(0, self.invincible_rounds - 1)
        self.immune_rounds = max(0, self.immune_rounds - 1)
        self.fired = {}
        return expired

    def clear_debuffs(self):
        self.controls = {}
        self.dots = []
        self.remove_buffs(lambda b: b.total >= 0)

    def clear_buffs(self):
        self.remove_buffs(lambda b: b.total <= 0)
        self.shield = self.shield_rounds = 0
        self.invincible_rounds = self.invincible_hits = 0
