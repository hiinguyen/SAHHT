"""Equipment splitting (equip.exchange, view 25): turn spare gear into metal and metalcore.

The client sends the ids as a repeated query key (`equip_id=1&equip_id=2`), so they are
read from `Request.lists`. Its screen refuses worn pieces, fate-bound pieces, duplicates
and ids it does not own; the server enforces the same rules, and one bad id refuses the
whole batch.

Per piece, the reward is the `equip_exchange` row of its `exchange_id` (falling back to
its quality) plus what the piece's enhance and refine levels cost:
- metal: a uniform draw in the row's `metal` `[min, max]`, plus
  `sum(i = 1..lv-1) ceil(equip_strongthen[i].quality<q> * 0.01 * equip_strongthen[i].metal)`
  and `sum(i = 1..st_lv) equip_st[i].metal`;
- metalcore: a uniform draw in the row's `metalcore` `[min, max]`, plus
  `sum(i = 1..st_lv) equip_st[i].metalcore`.
The client's third label ("đá") counts forge experience and is not paid here; that needs
the forge slice (`equip_forge_level`) to have run.
"""

import math
import random

from . import equipment
from .handlers import Refused, Request, Services, fail, ok
from .rewards import client_cache

MAX_PIECES = 11      # the client stops adding at #selected == 10, so 11 can be sent
METAL, METALCORE = "metal", "metalcore"


def _config(svc: Services, row: dict) -> dict:
    return svc.configs.get("equip").get(str(row["c_id"]), {})


def _strengthen_metal(svc: Services, row: dict) -> int:
    """The metal the client's own estimate refunds for the enhance levels."""
    table = svc.configs.get("equip_strongthen")
    quality = _config(svc, row).get("quality", 0)
    return sum(math.ceil(table.get(str(level), {}).get(f"quality{quality}", 0) * 0.01
                         * table.get(str(level), {}).get("metal", 0))
               for level in range(1, row["lv"]))


def _refine_refund(svc: Services, row: dict, key: str) -> int:
    table = svc.configs.get("equip_st")
    return sum(table.get(str(level), {}).get(key, 0)
               for level in range(1, row.get("st_lv", 0) + 1))


def _exchange_row(svc: Services, row: dict) -> dict | None:
    cfg = _config(svc, row)
    exchange_id = cfg.get("exchange_id") or cfg.get("quality")
    found = svc.configs.get("equip_exchange").get(str(exchange_id))
    return found if isinstance(found, dict) else None


def _draw(span) -> int:
    """Uniform integer in a `[min, max, weight]` triple; a fixed roll for tests."""
    low, high = int(span[0]), int(span[1])
    return random.randrange(low, high + 1) if high > low else low


def _reward(svc: Services, row: dict) -> tuple[int, int]:
    exchange = _exchange_row(svc, row)
    if exchange is None:
        raise Refused("error_param", "Trang bị này không thể phân giải.")
    metal_span = (exchange.get("metal") or [[0, 0]])[0]
    core_span = (exchange.get("metalcore") or [[0, 0]])[0]
    metal = (_draw(metal_span) + _strengthen_metal(svc, row)
             + _refine_refund(svc, row, METAL))
    metalcore = _draw(core_span) + _refine_refund(svc, row, METALCORE)
    return metal, metalcore


def equip_exchange(req: Request, svc: Services, player: dict):
    uid = player["uid"]
    ids = [value for value in req.lists.get("equip_id", []) if value]
    if not 0 < len(ids) <= MAX_PIECES or len(set(ids)) != len(ids):
        return fail("error_param", "Trang bị không hợp lệ.")
    rows = {row["id"]: row for row in svc.store.equipment_rows(uid)}
    if any(not equip_id.isdigit() or equip_id not in rows for equip_id in ids):
        return fail("error_param", "Trang bị không hợp lệ.")
    worn = {equip_id for _, _, equip_id in svc.store.equipment_positions(uid)}
    if any(equip_id in worn for equip_id in ids):
        return fail("error_param", "Trang bị đang sử dụng.")
    if any(equipment.extra(rows[equip_id]).get("bind_card") for equip_id in ids):
        return fail("error_param", "Trang bị đã khóa vận mệnh.")
    metal = metalcore = 0
    with svc.store.transaction():
        for equip_id in ids:
            piece_metal, piece_core = _reward(svc, rows[equip_id])
            metal += piece_metal
            metalcore += piece_core
        if not svc.store.remove_equipment(uid, ids):
            raise Refused("error_param", "Trang bị không hợp lệ.")
        svc.store.change_wallet(uid, {METAL: metal, METALCORE: metalcore})
    return ok({"reward": {METAL: metal, METALCORE: metalcore},
               "_client_cache_update": client_cache(svc, uid, removed_equips=ids)})


HANDLERS = {
    ("api", "equip.exchange"): equip_exchange,
}
