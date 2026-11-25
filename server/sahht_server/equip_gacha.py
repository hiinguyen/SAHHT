"""Equipment recruiting (equip_gacha.get_all_gacha, get_gacha) from equip_gacha.config.

Pools follow the hero-gacha rules: `use_gacha [prev, n]` unlocks after n draws of the
previous pool, `gacha_sort 2` limits the pool to `gacha_num` draws, and a pity score
(`add_point` per draw, `good_point` threshold) forces an entry from `good_item`.
Entries are `[type, id, count, weight]`; type 7 is an equipment config id, type 6 an
item id. Each equipment draw creates a new instance; `new_card` is the client's display
list `[type, instance id or 0, id, count]`.
"""

import random
import time

from .handlers import Request, Services, fail, ok
from .rewards import Loot, grant, pay

CURRENCY = {2: "silver", 3: "coin"}
LIMITED = 2
UNLIMITED = -1


def _pools(svc: Services) -> dict:
    return {k: v for k, v in svc.configs.get("equip_gacha").items()
            if isinstance(v, dict) and v.get("consume_sort") in CURRENCY}


def _entries(svc: Services, pool: dict, key: str) -> list:
    equips, items = svc.configs.get("equip"), svc.configs.get("item")
    found = []
    for entry in pool.get(key, []):
        if not isinstance(entry, list) or len(entry) < 4 or entry[3] <= 0:
            continue
        kind, ref = entry[0], str(entry[1])
        if kind == 7 and ref in equips:
            found.append((kind, int(entry[1]), entry[2], entry[3]))
        elif kind == 6 and ref in items:
            found.append((kind, int(entry[1]), entry[2], entry[3]))
    return found


def _draws(svc: Services, uid: str, pool_id: str) -> int:
    return svc.store.counter(uid, f"equip_gacha:{pool_id}")


def _score(svc: Services, uid: str, pool_id: str) -> int:
    return svc.store.counter(uid, f"equip_gacha_score:{pool_id}")


def _available(svc: Services, uid: str, level: int) -> dict:
    shown = {}
    for pool_id, pool in _pools(svc).items():
        low, high = (pool.get("use_level") or [1, 10**6])[:2]
        if not low <= level <= high:
            continue
        gate = pool.get("use_gacha") or []
        if len(gate) == 2 and _draws(svc, uid, str(gate[0])) < gate[1]:
            continue
        if not (_entries(svc, pool, "good_item") or _entries(svc, pool, "bad_item")):
            continue
        if pool.get("gacha_sort") == LIMITED:
            left = pool.get("gacha_num", 0) - _draws(svc, uid, pool_id)
            if left > 0:
                shown[pool_id] = left
        else:
            shown[pool_id] = UNLIMITED
    return shown


def _pick(entries, rng):
    pick = rng.uniform(0, sum(e[3] for e in entries))
    for entry in entries:
        pick -= entry[3]
        if pick <= 0:
            return entry
    return entries[-1]


def _one_draw(svc: Services, uid: str, pool_id: str, pool: dict, rng) -> list:
    good = _entries(svc, pool, "good_item")
    bad = _entries(svc, pool, "bad_item")
    everything = good + bad
    threshold = pool.get("good_point", 0)
    score = _score(svc, uid, pool_id) + pool.get("add_point", 0)
    forced = bool(good) and threshold > 0 and score >= threshold
    result = []
    for _ in range(max(1, pool.get("get_num", 1))):
        entry = _pick(good if forced else everything, rng)
        if forced or entry in good:
            score = 0
        forced = False
        result.append(entry)
    svc.store.set_counter(uid, f"equip_gacha_score:{pool_id}", score)
    return result


def get_all_gacha(req: Request, svc: Services, player: dict):
    available = _available(svc, player["uid"], player["level"])
    first = next(iter(available), "")
    return ok({
        "gacha_all": available,
        "gacha_freetimes": {}, "gacha_expire": {},
        "score": _score(svc, player["uid"], first) if first else 0,
        "energy_slot": 0, "discount_flag": 0, "guild_reward_sort": 0,
    })


def get_gacha(req: Request, svc: Services, player: dict):
    uid, pool_id = player["uid"], req.params.get("gacha_type", "")
    pool = _pools(svc).get(pool_id)
    if pool is None or pool_id not in _available(svc, uid, player["level"]):
        return fail("error_gacha", "Không thể chiêu mộ trang bị ở đây.")
    now = int(time.time())
    with svc.store.transaction():
        rolled = _one_draw(svc, uid, pool_id, pool, random.Random())
        loot = Loot()
        for kind, ref, count, _ in rolled:
            if kind == 7:
                loot.equips.extend([ref] * max(1, count))
            else:
                loot.items[ref] = loot.items.get(ref, 0) + max(1, count)
        pay(svc, uid, {CURRENCY[pool["consume_sort"]]: pool.get("value", 0)})
        svc.store.set_counter(uid, f"equip_gacha:{pool_id}", _draws(svc, uid, pool_id) + 1)
        granted = grant(svc, uid, loot, now)
    equip_iter = iter(granted.equip_ids)
    new_card = []
    for kind, ref, count, _ in rolled:
        if kind == 7:
            for _ in range(max(1, count)):
                new_card.append([7, next(equip_iter), ref, 1])
        else:
            new_card.append([6, 0, ref, max(1, count)])
    return ok({
        "new_card": new_card,
        "reward": {},
        "score": _score(svc, uid, pool_id),
        "gacha_all": _available(svc, uid, player["level"]),
        "gacha_freetimes": {}, "gacha_expire": {},
        "energy_slot": 0, "discount_flag": 0, "guild_reward_sort": 0,
        "_client_cache_update": granted.cache,
    })


HANDLERS = {
    ("api", "equip_gacha.get_all_gacha"): get_all_gacha,
    ("api", "equip_gacha.get_gacha"): get_gacha,
}
