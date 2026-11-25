"""Gem actions: synthesis, resolve and evolution (views 129, 130, 203).

Gems are stacks keyed by `gems.make_key`; every action spends only copies that are not
placed on a formation position (the client's own screens skip placed gems, and spending
a placed one would leave the grid pointing at a stack that no longer exists).

- `gem.synthesis` (`gem_id`, `gem_num`): `gem_num` times, spend `gem.config[gem_id].gem_num`
  gems of its `need_gem` (plain ones first, then evolved ones from the lowest level, as
  the client counts them), `iron` metal and the `need_item` items; grant the target gem.
- `gem.resolve` (`gems=<key>_<count>`, repeated): break stacks into metalcore, one uniform
  draw per gem in the `exchange` `[min, max]` of its config (the screen's "xilian" label).
- `gem.evolution` (`gem_id` key, `super_evo` 0/1): raise one gem a level for
  `gem_evolution[next]` metal and `gem_material`. A normal attempt succeeds with `rate`
  percent; a failure drops the gem to `false_back` and refunds `gem_material_return`.
  The super attempt costs `super_multiple` times as much and cannot fail (server rule:
  the original script is not available).
- `gem.upgrade` (feed gems to another for experience) is not served: the screen reads
  `exp`, `lv_max` and `eaten_exp`, which this version's gems no longer have.
"""

import random
from collections import Counter

from . import gems
from .handlers import Refused, Request, Services, fail, is_int, ok
from .rewards import client_cache, pay

ITEM = 6
METAL, METALCORE = "metal", "metalcore"
MAX_BATCH = 99
KEY_RE = gems.KEY_RE


def _item_costs(entries, times: int) -> dict:
    """`[[6, item id, count], ...]` -> {item id: count * times}; other kinds are ignored."""
    costs = {}
    for entry in entries or []:
        if entry and entry[0] == ITEM:
            costs[int(entry[1])] = costs.get(int(entry[1]), 0) + int(entry[2]) * times
    return costs


def _spend_items(svc: Services, uid: str, costs: dict) -> None:
    if costs and not svc.store.change_items(uid, {k: -v for k, v in costs.items()}):
        raise Refused("error_not_enough", "Không đủ nguyên liệu.")


def _change_gems(svc: Services, uid: str, deltas: dict) -> None:
    deltas = {key: delta for key, delta in deltas.items() if delta}
    if deltas and not svc.store.change_gems(uid, deltas):
        raise Refused("error_not_enough", "Không đủ đá quý.")


def _materials(free: dict, cid: str, total: int) -> dict:
    """Which stacks of gem `cid` pay for `total` copies: plain first, then by level."""
    pool = sorted(((gems.split_key(key)[0], key) for key in free
                   if gems.split_key(key)[1] == cid))
    spend, need = {}, total
    for _, key in pool:
        take = min(free[key], need)
        if take:
            spend[key] = take
            need -= take
    if need:
        raise Refused("error_not_enough", "Không đủ đá quý.")
    return spend


def synthesis(req: Request, svc: Services, player: dict):
    uid = player["uid"]
    gem_id, raw_count = req.params.get("gem_id", ""), req.params.get("gem_num", "1")
    if not is_int(gem_id) or not is_int(raw_count) or not 0 < int(raw_count) <= MAX_BATCH:
        return fail("error_param", "Đá quý không hợp lệ.")
    cfg = gems.config(svc.configs, gem_id)
    need = str(cfg.get("need_gem") or 0) if cfg else "0"
    if cfg is None or need == "0" or gems.config(svc.configs, need) is None:
        return fail("error_param", "Đá này không thể hợp thành.")
    count = int(raw_count)
    with svc.store.transaction():
        spend = _materials(gems.free_counts(svc.store, uid), need, cfg["gem_num"] * count)
        pay(svc, uid, {METAL: cfg.get("iron", 0) * count})
        items = _item_costs(cfg.get("need_item"), count)
        _spend_items(svc, uid, items)
        deltas = {key: -n for key, n in spend.items()}
        deltas[gem_id] = deltas.get(gem_id, 0) + count
        _change_gems(svc, uid, deltas)
    return ok({"reward": {"gem": [gem_id] * count},
               "_client_cache_update": client_cache(svc, uid, gems=list(deltas), items=items)})


def _draw(span) -> int:
    low, high = int(span[0]), int(span[1])
    return random.randrange(low, high + 1) if high > low else low


def resolve(req: Request, svc: Services, player: dict):
    uid = player["uid"]
    wanted = Counter()
    for raw in req.lists.get("gems", []):
        key, separator, count = raw.rpartition("_")
        if (not separator or not KEY_RE.fullmatch(key) or not is_int(count)
                or int(count) < 1 or gems.config(svc.configs, key) is None):
            return fail("error_param", "Đá quý không hợp lệ.")
        wanted[key] += int(count)
    free = gems.free_counts(svc.store, uid)
    if not wanted or any(free.get(key, 0) < n for key, n in wanted.items()):
        return fail("error_param", "Đá quý không đủ hoặc đang được gắn.")
    metalcore = sum(_draw(gems.config(svc.configs, key).get("exchange", [0, 0]))
                    for key, n in wanted.items() for _ in range(n))
    with svc.store.transaction():
        _change_gems(svc, uid, {key: -n for key, n in wanted.items()})
        svc.store.change_wallet(uid, {METALCORE: metalcore})
    return ok({"reward": {METALCORE: metalcore},
               "_client_cache_update": client_cache(svc, uid, gems=list(wanted))})


def evolution(req: Request, svc: Services, player: dict):
    uid, key = player["uid"], req.params.get("gem_id", "")
    if not KEY_RE.fullmatch(key) or (cfg := gems.config(svc.configs, key)) is None:
        return fail("error_param", "Đá quý không hợp lệ.")
    level, cid = gems.split_key(key)
    if level >= cfg.get("evo_max", 0):
        return fail("error_param", "Đá Quý đã đầy cấp!")
    row = svc.configs.get("gem_evolution").get(str(level + 1))
    if not isinstance(row, dict):
        return fail("error_param", "Đá Quý đã đầy cấp!")
    if gems.free_counts(svc.store, uid).get(key, 0) < 1:
        return fail("error_param", "Đá quý không có hoặc đang được gắn.")
    super_evo = req.params.get("super_evo") == "1"
    times = row.get("super_multiple", 1) if super_evo else 1
    success = super_evo or random.randrange(100) < row.get("rate", 0)
    new_level = level + 1 if success else min(level, row.get("false_back", 0))
    new_key = gems.make_key(new_level, cid)
    items = _item_costs(row.get("gem_material"), times)
    with svc.store.transaction():
        pay(svc, uid, {METAL: row.get("metal", 0) * times})
        _spend_items(svc, uid, items)
        if not success:
            refund = _item_costs(row.get("gem_material_return"), 1)
            svc.store.change_items(uid, refund)
            items = {**items, **refund}
        _change_gems(svc, uid, {key: -1, new_key: 1} if new_key != key else {})
    return ok({"success": "true" if success else "false", "got_gem": new_key,
               "_client_cache_update": client_cache(svc, uid, gems=[key, new_key], items=items)})


HANDLERS = {
    ("api", "gem.synthesis"): synthesis,
    ("api", "gem.resolve"): resolve,
    ("api", "gem.evolution"): evolution,
}
