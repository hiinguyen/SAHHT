"""Status art names the battle scene plays (`skill_effect/buff/<name>.lua`), shared by the
skill engine (`battle.py`) and the leader-skill rules (`leader_battle.py`)."""

CRIT_MULTIPLIER = 1.5

CONTROL_ART = {"stun": "buff_giddy", "freeze": "buff_ice", "petrify": "buff_shihua",
               "sleep": "buff_tired", "paralyze": "buff_mabi", "root": "buff_bingfeng",
               "fear": "buff_senility", "silence": "buff_chenmo", "chaos": "buff_giddy",
               "charm": "buff_giddy"}
DOT_ART = {"burn": "buff_fire", "bleed": "buff_hplow", "poison": "buff_corruption"}
DOT_TICK_ART = {"burn": "buff_fire_skill", "bleed": "buff_hplow_skill", "poison": "buff_hplow_skill"}
STAT_ART = {"patk": ("buff_phsc", "buff_phsclow"), "matk": ("buff_mgc", "buff_mgclow"),
            "def": ("buff_dfs", "buff_dfslow"), "speed": ("buff_speed", "buff_speedlow"),
            "max_hp": ("buff_hp", "buff_hplow"), "all": ("buff_allup", "buff_senility"),
            "dodge": ("buff_miss", "buff_speedlow")}
GENERIC_ART = ("buff_allup", "buff_senility")
MISS_ART, HEAL_ART, SHIELD_ART, INVINCIBLE_ART = "buff_miss", "buff_hp", "buff_shenyu", "buff_undead"


def buff_art(stat: str, value: float) -> str:
    if stat == "dmg_taken":
        return "buff_jianshang" if value < 0 else "buff_zhongshang"
    up, down = STAT_ART.get(stat, GENERIC_ART)
    return up if value >= 0 else down
