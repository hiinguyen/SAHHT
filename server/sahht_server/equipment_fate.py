"""Equipment fate (equip.fate_equip_bind/unbind/levelup, auto_fate_equip_levelup; views 182/193).

Binding locks a piece to a hero for `equip_fate["1"].cost` fate stones and starts its two
attribute percentages at 0: `bind_card` is the card id and `bind_data` maps the piece's
two ability indexes (as strings) to a percentage. The client reads either key without a
nil check, so both are always present while the piece is bound. `gem_fate` starts as
`[0,0,0,0]` (fate gems are out of scope).

Refreshing picks, for each attribute, the first `equip_fate` row of the piece's quality
whose `refresh_range1/2` still covers the current value. That row also prices the roll
(`refresh[sort - 1]` of each attribute, paid in `min/mid/max_fate_stone`). The change is a
weighted pick among the row's `refresh_equip_{min|mid|max}_fate{1|2}` bands, then a
uniform draw inside (`refresh_equip_fate_range` is the range the client prints). Values
are percentages and never go below 0.

`auto_fate_equip_levelup` rolls while the stones last, up to a bounded batch, and reports
how many range thresholds were crossed as `leveup_times`. Unbinding refunds the bind cost;
as the client warns, the upgrade stones are not returned.
"""

import random

from . import equipment
from .handlers import Refused, Request, Services, fail, ok
from .rewards import client_cache

MODES = {1: "min", 2: "mid", 3: "max"}
STONE_BY_SORT = {1: "min_fate_stone", 2: "mid_fate_stone", 3: "max_fate_stone"}
AUTO_LIMIT = 100
GEM_FATE = [0, 0, 0, 0]


def _config(svc: Services, row: dict) -> dict:
    return svc.configs.get("equip").get(str(row["c_id"]), {})


def _fields(row: dict) -> dict:
    return equipment.extra(row)


def _quality_rows(svc: Services, cfg: dict) -> list:
    """The config's rows for this quality, in key order (the client walks them the same)."""
    rows = svc.configs.get("equip_fate")
    return [rows[key] for key in sorted(rows, key=int)
            if isinstance(rows[key], dict) and rows[key].get("equip_quality") == cfg.get("quality")]


def _row_for(rows: list, value: float, attr: int) -> dict:
    field = f"refresh_range{attr}"
    for row in rows:
        if value <= row.get(field, 0):
            return row
    return rows[-1] if rows else {}


def _band(row: dict, mode: str, attr: int) -> list:
    return row.get(f"refresh_equip_{mode}_fate{attr}") or []


def _roll(bands) -> float:
    choices = [band for band in bands if len(band) >= 3 and band[2] > 0]
    total = sum(band[2] for band in choices)
    if not choices or total <= 0:
        return 0.0
    pick = random.uniform(0, total)
    for band in choices:
        pick -= band[2]
        if pick <= 0:
            return random.uniform(band[0], band[1])
    band = choices[-1]
    return random.uniform(band[0], band[1])


def _percent(bands) -> float:
    return round(_roll(bands) * 100, 2)


def _spend(svc: Services, uid: str, stone: str, count: int) -> bool:
    return count <= 0 or svc.store.change_wallet(uid, {stone: -count})


def _bind_cost(svc: Services) -> int:
    row = svc.configs.get("equip_fate").get("1", {})
    return int(row.get("cost", 0))


def _bind_fields(cfg: dict) -> dict:
    return {"bind_data": {str(cfg["ability1"]): 0, str(cfg["ability2"]): 0},
            "gem_fate": list(GEM_FATE)}


def fate_equip_bind(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    card_id = req.params.get("card_id", "")
    row = svc.store.equipment_row(uid, equip_id)
    card = svc.store.card(uid, card_id) if card_id else None
    if row is None or card is None:
        return fail("error_param", "Trang bị hoặc tướng không hợp lệ.")
    fields = _fields(row)
    if fields.get("bind_card"):
        return fail("error_param", "Trang bị đã được khóa vận mệnh.")
    cost = _bind_cost(svc)
    with svc.store.transaction():
        if not _spend(svc, uid, STONE_BY_SORT[1], cost):
            raise Refused("error_not_enough", "Đá Vận Mệnh không đủ.")
        fields = fields | _bind_fields(_config(svc, row)) | {"bind_card": str(card["id"])}
        svc.store.set_equipment_extra(uid, equip_id, fields)
    return ok({"_client_cache_update": client_cache(svc, uid, equips=[equip_id],
                                                   cards=[card["id"]])})


def fate_equip_unbind(req: Request, svc: Services, player: dict):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None:
        return fail("error_param", "Trang bị không hợp lệ.")
    fields = _fields(row)
    if not fields.get("bind_card"):
        return fail("error_param", "Trang bị chưa được khóa vận mệnh.")
    refund = _bind_cost(svc)
    fields = {k: v for k, v in fields.items()
              if k not in ("bind_card", "bind_data", "gem_fate", "bind_temp")}
    with svc.store.transaction():
        svc.store.set_equipment_extra(uid, equip_id, fields)
        if refund:
            svc.store.change_wallet(uid, {STONE_BY_SORT[1]: refund})
    return ok({STONE_BY_SORT[1]: refund,
               "_client_cache_update": client_cache(svc, uid, equips=[equip_id])})


def _roll_attributes(svc: Services, cfg: dict, bound: dict, mode: str) -> tuple[dict, dict]:
    """(new bind_data, change) for one refresh."""
    rows = _quality_rows(svc, cfg)
    new, change = {}, {}
    for attr in (1, 2):
        key = str(cfg[f"ability{attr}"])
        value = float(bound.get(key, 0))
        row = _row_for(rows, value, attr)
        delta = _percent(_band(row, mode, attr))
        new[key] = round(max(0.0, value + delta), 2)
        change[key] = round(new[key] - value, 2)
    return new, change


def _range(svc: Services, cfg: dict, bound: dict, sort: int) -> dict:
    """The [low, high] percent range the client prints for each attribute."""
    rows = _quality_rows(svc, cfg)
    shown = {}
    for attr in (1, 2):
        row = _row_for(rows, float(bound.get(str(cfg[f"ability{attr}"]), 0)), attr)
        spans = row.get("refresh_equip_fate_range") or [[0, 0]]
        span = spans[sort - 1] if len(spans) >= sort else spans[-1]
        shown[str(cfg[f"ability{attr}"])] = [round(span[0] * 100, 2), round(span[1] * 100, 2)]
    return shown


def _refresh_cost(svc: Services, cfg: dict, bound: dict, sort: int) -> int:
    rows = _quality_rows(svc, cfg)
    total = 0
    for attr in (1, 2):
        row = _row_for(rows, float(bound.get(str(cfg[f"ability{attr}"]), 0)), attr)
        refreshes = row.get("refresh") or []
        total += int(refreshes[sort - 1]) if len(refreshes) >= sort else 0
    return total


def _levelup(req: Request, svc: Services, player: dict, auto: bool):
    uid, equip_id = player["uid"], req.params.get("equip_id", "")
    sort = req.params.get("sort", "")
    row = svc.store.equipment_row(uid, equip_id)
    if row is None or not sort.isdigit() or int(sort) not in MODES:
        return fail("error_param", "Tham số không hợp lệ.")
    fields = _fields(row)
    bound = fields.get("bind_data")
    if not fields.get("bind_card") or not isinstance(bound, dict):
        return fail("error_param", "Trang bị chưa được khóa vận mệnh.")
    cfg, sort = _config(svc, row), int(sort)
    stone = STONE_BY_SORT[sort]
    with svc.store.transaction():
        change, times, crossed = {}, 0, 0
        limit = AUTO_LIMIT if auto else 1
        while times < limit:
            cost = _refresh_cost(svc, cfg, bound, sort)
            if not _spend(svc, uid, stone, cost):
                if times == 0:
                    raise Refused("error_not_enough", "Đá Vận Mệnh không đủ.")
                break
            before = dict(bound)
            bound, rolled = _roll_attributes(svc, cfg, bound, MODES[sort])
            for key, value in rolled.items():
                change[key] = round(change.get(key, 0) + value, 2)
            times += 1
            if auto and _crossed(svc, cfg, before, bound):
                crossed += 1
            if not auto:
                break
        fields = fields | {"bind_data": bound}
        svc.store.set_equipment_extra(uid, equip_id, fields)
    data = {"bind_data_temp": change, "fate_range": _range(svc, cfg, bound, sort),
            "_client_cache_update": client_cache(svc, uid, equips=[equip_id])}
    if auto:
        data["leveup_times"] = crossed
    return ok(data)


def _crossed(svc: Services, cfg: dict, before: dict, after: dict) -> bool:
    """True when an attribute moved into a higher refresh_range row."""
    rows = _quality_rows(svc, cfg)
    for attr in (1, 2):
        key = str(cfg[f"ability{attr}"])
        old, new = _row_for(rows, float(before.get(key, 0)), attr), \
            _row_for(rows, float(after.get(key, 0)), attr)
        if rows.index(new) > rows.index(old):
            return True
    return False


def fate_equip_levelup(req: Request, svc: Services, player: dict):
    return _levelup(req, svc, player, auto=False)


def auto_fate_equip_levelup(req: Request, svc: Services, player: dict):
    return _levelup(req, svc, player, auto=True)


HANDLERS = {
    ("api", "equip.fate_equip_bind"): fate_equip_bind,
    ("api", "equip.fate_equip_unbind"): fate_equip_unbind,
    ("api", "equip.fate_equip_levelup"): fate_equip_levelup,
    ("api", "equip.auto_fate_equip_levelup"): auto_fate_equip_levelup,
}
