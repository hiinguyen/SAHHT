"""Daily tasks, achievements and the bounty list (module `reward`).

Daily tasks ("Nhiệm vụ ngày", reward_diary.config) count events per day: `record` bumps the
daily counter `quest:<target_sort>` from the handler where the event happens, and only the
sorts in LIVE_SORTS are offered, so no task points at a closed feature. Points open the
four boxes of diaryscore.config. Achievements (reward_once.config) are derived from player
state (level, recaptured cities) and claimed once (lifetime counter `once:<id>`). The bounty
list (wanted.config) lists every unclaimed id: for the client an absent id is a claimed one.

Online-time rows exist in the client's table but nothing feeds them yet, so they stay at
state 0 and their view stays closed.
"""

import time

from . import campaign
from .handlers import ALERT_PROVIDERS, Request, Services, fail, ok
from .rewards import Loot, grant
from .quest_events import LIVE_SORTS, counter_name, record  # noqa: F401 (record re-exported)
from .shop import DAILY, period

ONCE_LEVEL, ONCE_RECAPTURE = 1, 2
WANTED_RECAPTURE = 100
MAX_SCORE = 100
BOXES = 4
STATE_PENDING, STATE_READY, STATE_CLAIMED = 0, 1, 2


# ---- daily tasks ---------------------------------------------------------------------

def _diary_rows(svc: Services) -> dict:
    return {key: row for key, row in svc.configs.get("reward_diary").items()
            if row.get("target_sort") in LIVE_SORTS}


def _thresholds(svc: Services) -> list:
    return sorted(int(key) for key in svc.configs.get("diaryscore"))


def _diary_done(svc: Services, uid: str, now: int) -> dict:
    day = period(DAILY, now)
    return {key: svc.store.counter(uid, counter_name(row["target_sort"]), day)
            for key, row in _diary_rows(svc).items()}


def _score(svc: Services, done: dict) -> int:
    rows = _diary_rows(svc)
    return min(MAX_SCORE, sum(min(count, rows[key]["num"]) * rows[key]["reward_score"]
                              for key, count in done.items()))


def _box_claimed(svc: Services, uid: str, score: int, now: int) -> bool:
    return bool(svc.store.counter(uid, f"diary_box:{score}", period(DAILY, now)))


def _diary_state(svc: Services, uid: str, now: int) -> dict:
    done = _diary_done(svc, uid, now)
    thresholds = _thresholds(svc)
    claimed = [t for t in thresholds if _box_claimed(svc, uid, t, now)]
    return {
        "diary_done": done, "diaryscore": _score(svc, done), "diaryscore_done": claimed,
        "diary_boxes": [{"slot": slot, "score": t, "done": t in claimed}
                        for slot, t in enumerate(thresholds[:BOXES], 1)],
    }


def reward_diary_index(req: Request, svc: Services, player: dict):
    state = _diary_state(svc, player["uid"], int(time.time()))
    return ok({"diary": {"result": {key: 1 for key in _diary_rows(svc)}}, **state})


def reward_diary_score_award(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    thresholds = _thresholds(svc)
    score_text, slot = req.params.get("score", ""), req.params.get("slot")
    if not score_text.isdigit() or int(score_text) not in thresholds:
        return fail("error_param", "Mốc điểm không hợp lệ.")
    score = int(score_text)
    if slot is not None and slot != str(thresholds.index(score) + 1):
        return fail("error_param", "Mốc điểm không hợp lệ.")
    with svc.store.transaction():
        state = _diary_state(svc, uid, now)
        if state["diaryscore"] < score:
            return fail("error_param", "Chưa đủ điểm hoạt động.")
        if score in state["diaryscore_done"]:
            return fail("error_param", "Đã nhận phần thưởng này.")
        svc.store.set_counter(uid, f"diary_box:{score}", 1, period(DAILY, now))
        granted = grant(svc, uid, Loot.of(svc.configs.get("diaryscore")[str(score)]), now)
    state = _diary_state(svc, uid, now)
    return ok({"reward": granted.reward, "diaryscore": state["diaryscore"],
               "diaryscore_done": state["diaryscore_done"],
               "diary_boxes": state["diary_boxes"], "_client_cache_update": granted.cache})


def _claimable_boxes(svc: Services, uid: str, now: int) -> int:
    state = _diary_state(svc, uid, now)
    return sum(1 for box in state["diary_boxes"]
               if not box["done"] and state["diaryscore"] >= box["score"])


# ---- achievements ---------------------------------------------------------------------

def _recaptured(svc: Services, uid: str, city) -> int:
    buildings = campaign._city_plan(svc, str(city)).buildings
    return campaign._regain(buildings, svc.store.cleared_buildings(uid))


def _once_value(svc: Services, uid: str, level: int, row: dict) -> int:
    sort, target = row.get("target_sort"), (row.get("target_data") or [0])[0]
    if sort == ONCE_LEVEL:
        return level
    if sort == ONCE_RECAPTURE:
        return _recaptured(svc, uid, target)
    return 0


def _once_result(svc: Services, uid: str) -> dict:
    level = svc.store.player_for_uid(uid)["level"]
    result = {}
    for key, row in svc.configs.get("reward_once").items():
        need = (row.get("target_data") or [0])[0]
        value = _once_value(svc, uid, level, row)
        if svc.store.counter(uid, f"once:{key}"):
            state = STATE_CLAIMED
        else:
            reachable = row.get("target_sort") in (ONCE_LEVEL, ONCE_RECAPTURE)
            state = STATE_READY if reachable and value >= need else STATE_PENDING
        result[key] = [value, need, state]
    return result


def reward_once_index(req: Request, svc: Services, player: dict):
    return ok({"once": {"result": _once_result(svc, player["uid"])}})


def reward_once_award(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    award = req.params.get("award_id", "")
    row = svc.configs.get("reward_once").get(award)
    with svc.store.transaction():
        if row is None or _once_result(svc, uid)[award][2] != STATE_READY:
            return fail("error_param", "Chưa thể nhận thành tựu này.")
        svc.store.set_counter(uid, f"once:{award}", 1)
        granted = grant(svc, uid, Loot.of(row["reward"]), now)
    return ok({"reward": granted.reward, "once": {"result": _once_result(svc, uid)},
               "_client_cache_update": granted.cache})


def _has_claimable_once(svc: Services, uid: str, now: int) -> bool:
    return any(state == STATE_READY for _, _, state in _once_result(svc, uid).values())


# ---- bounty list ----------------------------------------------------------------------

def _wanted_result(svc: Services, uid: str) -> dict:
    result = {}
    for key, row in svc.configs.get("wanted").items():
        if svc.store.counter(uid, f"wanted_claimed:{key}"):
            continue
        need = (row.get("target_data1") or [1])[0]
        if row.get("target_sort") == WANTED_RECAPTURE:
            value = min(100, _recaptured(svc, uid, (row.get("target_data") or [0])[0]))
            result[key] = [value, need, 1 if value >= need else 0]
        else:
            result[key] = [0, need, 0]   # fight statistics are not tracked yet
    return result


def reward_index(req: Request, svc: Services, player: dict):
    return ok({"wanted_data": {"result": _wanted_result(svc, player["uid"])}})


def reward_wanted_award(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    award = req.params.get("award_id", "")
    with svc.store.transaction():
        entry = _wanted_result(svc, uid).get(award)
        if entry is None or entry[2] != 1:
            return fail("error_param", "Chưa thể nhận treo thưởng này.")
        svc.store.set_counter(uid, f"wanted_claimed:{award}", 1)
        granted = grant(svc, uid, Loot.of(svc.configs.get("wanted")[award]["reward"]), now)
    return ok({"reward": granted.reward, "wanted": {"result": _wanted_result(svc, uid)},
               "_client_cache_update": granted.cache})


ALERT_PROVIDERS["diary"] = _claimable_boxes
ALERT_PROVIDERS["once"] = _has_claimable_once
ALERT_PROVIDERS["reward"] = lambda svc, uid, now: False

HANDLERS = {
    ("api", "reward.index"): reward_index,
    ("api", "reward.wanted_award"): reward_wanted_award,
    ("api", "reward.diary_index"): reward_diary_index,
    ("api", "reward.diary_score_award"): reward_diary_score_award,
    ("api", "reward.once_index"): reward_once_index,
    ("api", "reward.once_award"): reward_once_award,
}
