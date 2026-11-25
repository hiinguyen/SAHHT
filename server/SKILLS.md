# Hero and enemy skills

The original server ran one Python script per skill (`skill_detail.sprite_py`), and none of them shipped with the client.
This server rebuilds them as data: `data/skill_specs.json` describes every skill chain of every hero up to card id 38700 (heroes released through 2018), and `data/enemy_skill_specs.json` describes the 150 campaign-enemy skills that are not already hero skills (166 ids in total; the other 16 are legacy 4-digit hero base skills).
Both files use the same DSL and `sahht_server/battle.py` runs their effects; `sahht_server/skills.py` loads both and refuses a key defined twice.
`sahht_server/skill_spec.py` is the schema; `python3 -m sahht_server.skill_spec data/skill_specs.json data/enemy_skill_specs.json` checks files.

`data/leader_skill_specs.json` is a third, smaller file for leader skills (`sahht_server/leader_skill.py`, see the last section).

## What a spec is keyed by

A hero's skill slot `i` starts at `character_detail.skill_<i>_source[0][0]` (the base skill id).
`skill_detail.is_evolution` links each skill to its next tier, forming a chain such as `1010 -> 1011 -> 1012`.
One spec is written per base skill id and covers the whole chain.
At run time the engine takes the tier's own `effect`, `effect_lvchange`, `attr_effect`, `cd`, `pre_cd` and `rate` from `skill_detail`, so tiers that only change numbers need nothing extra.

## Numbers

Any number in a spec may be a literal or one of these words:

- `"effect"`: the tier's `effect + effect_lvchange * skill_level`, exactly what the client shows in place of the word `effect` in the description.
- `"attr"`: the tier's `attr_effect` (element damage percent; the description writes it as a literal such as `140%` or as `attr_effect%`).
- `"-effect"` / `"-attr"`: the same, negated, for reductions such as "giảm effect% phòng ngự" (`"value": "-effect"`).
- `"effect100"` / `"attr100"`: the same divided by 100, for rows whose effect is written in basis points (`42420` has `effect` 800 = 8%).
- `"effect+20"` / `"effect-20"`: the same plus or minus a literal (`41430`'s "effect+20%" ST).

Percentages are written as plain numbers: `150` means 150%.
Use the literal numbers the base skill's description states (for example "kéo dài 2 hiệp" is `"rounds": 2`).

## Spec fields

```json
{
  "1010": {
    "trigger": "active",
    "aim": "enemy_front",
    "effects": [
      {"op": "damage", "target": "target", "type": "phys", "scale": 100, "ignore_def": "effect"},
      {"op": "dot", "target": "target", "kind": "bleed", "scale": 3, "of": "target_max_hp", "rounds": 3}
    ],
    "note": "optional: what was simplified and why"
  }
}
```

| Field | Meaning |
|---|---|
| `trigger` | When the skill fires (table below). Required. |
| `aim` | How an `active` skill picks its primary target, which effects then address as `target`. Default `enemy_front`. Needs `count` for `*_random`. |
| `count` | Number of units for a random `aim`. |
| `limit_per_round` | Most times the skill may fire per round ("mỗi hiệp tối đa 2 lần"). |
| `once` | Fires at most once per battle ("mỗi trận chỉ 1 lần"). |
| `rounds` | `[first, last]` round window in which the skill may fire ("từ hiệp 2": `[2, 30]`; "trước 7 hiệp": `[1, 7]`). |
| `effects` | Ordered list of effects (below). An empty list is allowed only with a `note` explaining why. |
| `note` | Free text: simplifications, parts left out. |

### Triggers

| `trigger` | `skill_type` | Fires |
|---|---|---|
| `active` | `KBEFOREATTACK` | On the unit's turn, instead of its normal attack, when off cooldown and the `rate` roll succeeds. |
| `before_battle` | `KBEFOREBATTLE` | Once, before round 1 ("kĩ năng trước trận"). |
| `before_round` | `KBEFOREROUND` | At the start of every round ("trước hiệp", "mỗi hiệp bắt đầu"). |
| `before_hit` | `KBEFOREHERT` | When an enemy attack is about to hit the unit; effects land before the damage, so a dodge or damage-reduction buff counts for that hit. Counter-attacks go here too. `target` is the attacker. |
| `after_hit` | `KBEATTACK` | After the unit was hit and is still alive. `target` is the attacker. |
| `on_death` | `KDEAD` | When the unit dies. `target` is the killer. |
| `on_attack` | `KATTACK` | After the unit's own attack or skill hit something. `target` is the unit it hit. |
| `passive` | (none) | Always on: its `buff` effects are applied before round 1 with no animation and never expire. |

Use the trigger the description implies when it disagrees with `skill_type` or `skill_type` is empty.
The `rate` roll (from `skill_detail`, a percent) gates `active`, `before_hit`, `after_hit`, `on_death` and `on_attack`; `before_battle`, `before_round` and `passive` always fire.
A `rate` of 0 (some early heroes) means the skill always fires.
`cd` counts rounds: after firing, the skill waits `cd` rounds (`cd` 1 = at most once per round); `pre_cd` delays its first use.

### Targets

| `target` | Who |
|---|---|
| `self` | The caster. |
| `target` | The primary target: the `aim` pick of an `active` skill, the attacker for `before_hit` / `after_hit`, the killer for `on_death`, the unit hit for `on_attack`. |
| `hit` | Every unit the most recent `damage` effect of this cast actually hit. |
| `enemy_front` | First living enemy in slot order (front row first). "mục tiêu", "kẻ địch", "đối phương" with no qualifier. |
| `enemy_back` | First living enemy of the back row, else the front row. "xếp sau", "phía sau". |
| `enemy_row_front` / `enemy_row_back` | Every living enemy of that row (falls back to the other row when empty). "hàng trước", "hàng sau". |
| `enemy_line` | The front enemy and the enemy behind it in the same lane. "trực tuyến", "mục tiêu và phía sau hắn", "xuyên thấu". |
| `enemy_all` | Every living enemy. "toàn bộ", "toàn thể", "tất cả địch". |
| `enemy_random` | `count` random living enemies ("2 mục tiêu ngẫu nhiên"; "1-3" means pick the upper bound). |
| `enemy_lowest_hp` / `enemy_highest_hp` / `enemy_highest_atk` / `enemy_fastest` | One enemy chosen by current HP percent, attack or speed. |
| `ally_all` / `ally_others` | Every living ally including / excluding the caster. "toàn bộ phe ta", "đồng đội". |
| `ally_lowest_hp` | The living ally with the lowest HP percent. |
| `ally_random` | `count` random living allies. |
| `ally_front` | First living ally in slot order. |
| `ally_dead` | Dead allies (only meaningful for `revive`). |

Any effect may add `count` to cap how many of the selected units it touches.

### Effect fields every op accepts

| Field | Meaning |
|---|---|
| `op` | The operation (below). |
| `target` | Who it applies to. Required except for `revive`, `state`, `extra_action`, `rage` (default `self`). |
| `chance` | Percent chance, rolled per unit ("có 30% tỉ lệ làm choáng"). |
| `if` | Condition (or list of conditions, all required) checked per unit. |
| `count` | Cap on the number of units. |

### Ops

| `op` | Fields | Meaning |
|---|---|---|
| `damage` | `type` (`phys`, `magic`, `true`), `scale`, `stat`, `ignore_def`, `hits`, `bonus`, `crit`, `sure_hit`, `crit_bonus` | Damage of `scale`% of the caster's `stat`. `stat` defaults to `patk` for `phys` and `true`, `matk` for `magic`. Other stats: `def`, `speed`, `max_hp` (caster's), `hp_lost` (caster's missing HP), `target_max_hp`, `target_hp`, `target_def`, `damage_taken` (damage the caster just took, for counters). `phys` and `magic` are reduced by the target's defense, minus `ignore_def` percent; `true` ignores defense ("sát thương thực", "không thể phòng ngự", "bỏ qua phòng ngự"). `hits` splits the damage into that many blows (display only). `bonus` is a list of `{"if": cond, "pct": n}`: `pct`% more damage when the condition holds ("nếu mục tiêu đang bị thiêu đốt thì tạo thêm 100% sát thương"). `crit`: `always` or `never`; `crit_bonus` adds percentage points of crit chance for this hit ("+50% tỉ lệ bạo kích"); `sure_hit` skips the hit roll ("chắc chắn trúng"). |
| `attr_damage` | `element` (`fire`, `water`, `wind`, `earth`, `own`), `scale` | Element damage: `scale`% of the caster's element attack minus the target's element defense. "sát thương thuộc tính Gió" is `wind`; "Lửa/Hỏa" `fire`, "Nước/Thủy" `water`, "Đất/Thổ" `earth`; unnamed element is `own`. Usually `"scale": "attr"`. |
| `heal` | `scale`, `of` | Restore `scale`% of: `max_hp` (the healed unit's), `lost_hp` (its missing HP), `patk` / `matk` / `def` (the caster's), `damage` (damage this cast dealt; lifesteal such as "10% sát thương chuyển hóa thành HP"). |
| `buff` | `stat`, `value`, `rounds`, `max_stack` | Change a stat for `rounds` rounds (`0` = rest of battle). Negative `value` is a debuff. `patk`, `matk`, `def`, `speed`, `max_hp`, `all` (patk+matk+def+speed), `attr_atk`, `attr_def` are percent of the unit's base value; `crit`, `dodge` ("né tránh"), `hit` ("chính xác"), `dmg_dealt` ("tăng sát thương"), `dmg_taken` (negative: "giảm sát thương phải chịu", "giảm thương"), `heal_taken`, `lifesteal`, `reflect` ("phản đòn x% sát thương") are percentage points. `max_stack` lets repeated casts add up ("tối đa dồn 3 lần"); without it a recast refreshes. |
| `control` | `kind`, `rounds` | Crowd control lasting `rounds` of the victim's turns. `stun` ("choáng"), `freeze` ("đóng băng", "băng phong"), `petrify` ("hóa đá"), `sleep` ("ngủ say", broken by damage), `paralyze` ("tê liệt"), `root` ("đứng im", "trói buộc"), `fear` ("sợ hãi") all skip the turn. `silence` ("câm lặng", "phong ấn") forbids skills. `chaos` ("hỗn loạn") and `charm` ("mê hoặc") make the victim attack its own side. |
| `dot` | `kind` (`burn`, `bleed`, `poison`), `scale`, `of`, `rounds` | Damage at the start of each round: `scale`% of `target_max_hp`, or of the caster's `patk` / `matk`. "thiêu đốt/cháy" `burn`, "chảy máu/tụt HP" `bleed`, "trúng độc" `poison`. |
| `shield` | `scale`, `of`, `rounds` | Absorbs damage up to `scale`% of `max_hp` (the shielded unit's) or the caster's `patk` / `matk` / `def`. |
| `invincible` | `rounds` or `hits` | Takes no damage for `rounds` rounds, or for the next `hits` hits ("miễn dịch sát thương 2 lần"). |
| `immune_control` | `rounds` or `times` | Ignores new `control` effects. |
| `dispel` | `what` (`debuffs`, `buffs`, `all`) | Remove debuffs, controls and DoTs ("xóa hiệu quả xấu/phụ", "tẩy trừ") or buffs, shields and invincibility ("xua tan"). |
| `revive` | `scale` | Come back with `scale`% max HP. Use with `on_death` (the `rate` roll is the revive chance) or on `ally_dead`. |
| `execute` | `below` | Kill the target outright when its HP is below `below`% ("kết liễu"). |
| `hp_cost` | `scale`, `of` (`max_hp`, `hp`) | The target (usually `self`) loses HP ("hi sinh 20% HP bản thân"); never kills. |
| `rage` | `value`, `side` (`ally`, `enemy`) | Change the leader's rage ("tăng 15 điểm nộ khí cho anh hùng phe ta"). Kept for completeness; leader skills are not implemented yet, so it has no effect. |
| `state` | `name`, `rounds` | Put a named state on the unit (`0` rounds = rest of battle), for later `self_state:<name>` conditions ("trạng thái giác ngộ" -> `awaken`). |
| `extra_action` | | The unit acts once more this round. |

### Conditions

Written as `name` or `name:arg`; a list means all must hold.
`target_*` conditions test the unit the effect lands on; when the effect lands on the caster's own side (a self-heal "nếu mục tiêu bị mê hoặc"), they test the cast's primary target instead.

| Condition | Holds when |
|---|---|
| `target_has:<status>` / `target_lacks:<status>` / `self_has:<status>` | The unit carries that status. Statuses: any control kind, any DoT kind, `control` (any), `debuff` (any), `buff` (any), `shield`, `invincible`. |
| `self_state:<name>` / `self_lacks_state:<name>` | The caster is (not) in a `state`. |
| `target_boss` / `target_not_boss` | The target is (not) a boss. |
| `target_race:<n>` / `target_not_race:<n>` | The target is / is not of race n (0 sức mạnh, 1 nguyên tố, 2 Zombie, 3 bản địa, 4 lí tính, 5 linh tính). |
| `enemy_has_race:<n>` / `ally_has_race:<n>` / `ally_lacks_race:<n>` | Some enemy / some ally is of race n; no ally is. |
| `target_hp_below:<n>` / `target_hp_above:<n>` / `self_hp_below:<n>` / `self_hp_above:<n>` | HP percent below / above n. |
| `round_ge:<n>` / `round_le:<n>` | Current round number. |
| `target_atk_higher` / `target_atk_lower` / `target_speed_higher` | Comparison of the target's attack (max of patk, matk) or speed with the caster's. |
| `target_count:<n>[,<n>...]` | The cast hit exactly one of these numbers of units. |
| `normal_attack` | The triggering attack was a normal attack, not a skill. |

## Battle rules the engine applies

- Each round starts with a `sort` frame; living units act in descending speed order (ties by slot).
- At round start, DoTs tick, then `before_round` skills fire; at round end buffs lose a round and expired ones are removed.
- On its turn a unit skips if it holds a turn-skipping control; with `chaos` / `charm` it attacks a random ally instead.
- Otherwise its first ready `active` skill (slot order) whose `rate` roll succeeds is cast, unless the unit is silenced; failing that it makes a normal attack.
- A normal attack is 100% physical damage, or magical when the unit's `matk` is higher than its `patk`.
- Physical and magical damage is `raw * raw / (raw + defense)` with `raw = stat * scale / 100`, then multiplied by `1 + dmg_dealt/100` and `1 + dmg_taken/100`; it is at least 1.
- Every hit rolls hit (`hit - dodge` percent, at least 5%) and crit (`crit` percent, 150% damage); `sure_hit` skips the first roll.
- "Giảm thương" (`subhurt`) removes that percentage of the final damage, on top of `dmg_taken`.
- Heroes have a base of crit 10, hit 100, dodge 0 and add their gear's `crit`, `hit`, `dodge` and `subhurt`; campaign enemies use their `crit`, `hr`, `dr` and `subhurt`.
- Element stats come from equipment (suit effects, enchant `atts`) and add to combat power 1:1; in battle they feed `attr_damage` (an `own` element is the caster's strongest). Normal attacks do not add element damage, because no source states that rule.
- Not wiping the enemy within 30 rounds is a loss.

## Leader skills

`leader_skill.config` has 96 rows; only the 12 whose `script` has a file in
`skill_effect/leader_skill/` are learnable (the rest are passive nodes whose scripts never
shipped). `data/leader_skill_specs.json` describes those 12 with a small DSL:

| field | meaning |
|---|---|
| `aim` | default target (`enemy_all`, `enemy_front`, `enemy_random`, `enemy_lowest_hp`, `ally_all`, `ally_lowest_hp`) |
| `effects` | `{"op": "damage", "type", "stat", "scale"}` and `{"op": "control", "kind", "rounds"}`, each with an optional `target` |
| `stat` | `ally_max_matk`, `ally_avg_matk`, `ally_max_patk`, `enemy_max_matk`, `enemy_max_patk` |
| `scale` | `effect1` / `effect2` (resolved from `base_effect1/2` + `add_effect1/2` per level) or a literal |

In battle the player side has a rage bar (0..100): +10 when an ally acts, +5 when an ally is
hit. At the start of a round with 100 rage the first equipped skill whose `ready_time` and
`cd` are satisfied casts, emitting a `skill_hero` frame (`{src: 0, name: <script>, skillid,
des, hurt}`), then rage returns to 0. Leader damage is `stat * scale%` without the normal
defense step. These are server rules: the client has no formula for any of them.

## Curation rules

- Describe what the description says, not what the skill name suggests.
- Keep the description's order of effects.
- Flavour text ("triệu hồi bầy dơi") is not an effect unless it states a mechanic.
- When a mechanic cannot be expressed exactly, write the closest expression and say what changed in `note`.
- When a sentence cannot be expressed at all, leave it out and quote it in `note`.
- "BOSS hiệu quả giảm một nửa" and similar boss caps: add the same effect again with `if: target_boss` and half the value, and `if: target_not_boss` on the full one.
- Stories in Chinese (some top tiers) are translations of the same mechanic; read them only to resolve ambiguity.
