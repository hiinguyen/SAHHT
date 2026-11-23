"""Hero recruiting (gacha.get_all_gacha, gacha.get_gacha) from gacha.config.

Pool rules read from the config:
- `use_gacha [prev, n]`: the pool opens once pool `prev` has been drawn n times
  (so 999, the tutorial pool, gates everything; chains run 101 -> 102 -> 111 -> 112 ...);
- `gacha_sort 2` limits a pool to `gacha_num` draws, after which it is no longer listed;
- `use_level [min, max]`: player levels that see the pool;
- `consume_sort` 2 pays `value` silver ("Vàng"), 3 pays `value` coin ("Xu"), per draw;
- each draw gives `get_num` heroes from `good_item` + `bad_item` (`[c_id, kind, weight]`),
  and `add_point` builds a pity score: at `good_point` the draw comes from `good_item`.
Entries that are box ids, unknown heroes, or heroes after card 38700 (no skill specs)
are left out; a pool with no hero entries borrows those of a pool of its gacha_team.
"""

import random
import time

from .handlers import Request, Services, fail, ok
from .rewards import Loot, grant, pay
from .skills import LAST_HERO_ID

LIMITED = 2
UNLIMITED = -1            # gacha_all value the client shows without a count
CURRENCY = {2: "silver", 3: "coin"}
ENERGY_SLOT = 0           # the lucky-energy bar (refreshUi computes 200 - energy_slot)


def _pools(svc: Services) -> dict:
    return {k: v for k, v in svc.configs.get("gacha").items()
            if isinstance(v, dict) and v.get("consume_sort") in CURRENCY}


def _hero_entries(svc: Services, pool: dict, key: str) -> list:
    characters = svc.configs.get("character_detail")
    return [(e[0], e[-1]) for e in pool.get(key, [])
            if isinstance(e, list) and len(e) >= 3 and str(e[0]) in characters
            and e[0] <= LAST_HERO_ID and e[-1] > 0]


def _entries(svc: Services, pool_id: str) -> tuple:
    """(good, all) weighted hero lists of a pool, borrowing from its gacha_team if empty.
    `good` may be empty: such a pool has no pity target."""
    pools = _pools(svc)
    team = pools[pool_id].get("gacha_team")
    candidates = [pool_id] + sorted(k for k, v in pools.items() if v.get("gacha_team") == team)
    for candidate in candidates:
        good = _hero_entries(svc, pools[candidate], "good_item")
        bad = _hero_entries(svc, pools[candidate], "bad_item")
        if good or bad:
            return good, good + bad
    return (), ()


def _draws(svc: Services, uid: str, pool_id: str) -> int:
    return svc.store.counter(uid, f"gacha:{pool_id}")


def _available(svc: Services, uid: str, level: int) -> dict:
    """pool id -> draws left (UNLIMITED for no limit) of every pool the player can use now."""
    shown = {}
    for pool_id, pool in _pools(svc).items():
        low, high = (pool.get("use_level") or [1, 10**6])[:2]
        if not low <= level <= high:
            continue
        gate = pool.get("use_gacha") or []
        if len(gate) == 2 and _draws(svc, uid, str(gate[0])) < gate[1]:
            continue
        if not _entries(svc, pool_id)[1]:
            continue
        if pool.get("gacha_sort") == LIMITED:
            left = pool.get("gacha_num", 0) - _draws(svc, uid, pool_id)
            if left > 0:
                shown[pool_id] = left
        else:
            shown[pool_id] = UNLIMITED
    return shown


def _pick(entries, rng) -> int:
    pick = rng.uniform(0, sum(w for _, w in entries))
    for c_id, weight in entries:
        pick -= weight
        if pick <= 0:
            return c_id
    return entries[-1][0]


def _score_key(pool: dict) -> str:
    return f"gacha_score:{pool.get('gacha_team')}"


def _roll(svc: Services, uid: str, pool_id: str, pool: dict, rng) -> list:
    """The heroes of one draw, advancing the pool team's pity score."""
    good, everything = _entries(svc, pool_id)
    good_ids = {c for c, _ in good}
    threshold = pool.get("good_point", 0)
    score = svc.store.counter(uid, _score_key(pool))
    heroes = []
    for _ in range(max(1, pool.get("get_num", 1))):
        score += pool.get("add_point", 0)
        forced = good and threshold > 0 and score >= threshold
        hero = _pick(good if forced else everything, rng)
        if threshold > 0 and hero in good_ids:
            score = 0
        heroes.append(hero)
    svc.store.set_counter(uid, _score_key(pool), score)
    return heroes


def get_all_gacha(req: Request, svc: Services, player: dict):
    available = _available(svc, player["uid"], player["level"])
    first = _pools(svc).get(next(iter(available), ""), {})
    return ok({
        "gacha_all": available,
        "gacha_freetimes": {}, "gacha_expire": {},
        "energy_slot": ENERGY_SLOT, "discount_flag": 0, "guild_reward_sort": 0,
        "score": svc.store.counter(player["uid"], _score_key(first)),
    })


def get_gacha(req: Request, svc: Services, player: dict):
    uid, pool_id = player["uid"], req.params.get("gacha_type", "")
    pool = _pools(svc).get(pool_id)
    if pool is None or pool_id not in _available(svc, uid, player["level"]):
        return fail("error_gacha", "Không thể chiêu mộ ở đây.")
    now = int(time.time())
    with svc.store.transaction():
        pay(svc, uid, {CURRENCY[pool["consume_sort"]]: pool.get("value", 0)})
        heroes = _roll(svc, uid, pool_id, pool, random.Random())
        svc.store.set_counter(uid, f"gacha:{pool_id}", _draws(svc, uid, pool_id) + 1)
        granted = grant(svc, uid, Loot(cards=heroes), now)
    return ok({
        "new_card": granted.card_ids,
        "score": svc.store.counter(uid, _score_key(pool)),
        "energy_slot": ENERGY_SLOT,
        "gacha_all": _available(svc, uid, player["level"]),
        "gacha_freetimes": {},
        "reward": granted.reward,
        "_client_cache_update": granted.cache,
    })


HANDLERS = {
    ("api", "gacha.get_all_gacha"): get_all_gacha,
    ("api", "gacha.get_gacha"): get_gacha,
}
