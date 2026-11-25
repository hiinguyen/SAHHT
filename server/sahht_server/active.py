"""Activity hall ("Hoạt động") and its chapter activities.

The hall is one popup (`game_activity_new_pop`) fed by `active.index`. This server serves five
of its rows, each a screen of its own:

| row | what                         | chapters                                   |
|-----|------------------------------|--------------------------------------------|
| 40  | resource war                 | 1                                          |
| 50  | daily challenge (button 108) | 100..160, one per weekday                  |
| 60  | extreme challenge (109)      | 200, 210, 220 and 230, two weekdays apiece |
| 70  | exp stage (105)              | 80                                         |
| 80  | survival test (107)          | `survival.py`                              |

A chapter is a list of stages (`active_detail`), each a run of three fights. A run starts at
step 0 and costs one of the day's attempts; an unfinished run survives the day boundary and
is continued from its next step. The last step pays the stage's reward.
Every other row is hidden by `config_overrides` (an unserved row would crash the popup).
"""

import random
import time
from datetime import datetime

from . import campaign, survival
from .battle import WIN
from .handlers import Refused, Request, Services, fail, is_int, ok, team_combat
from .player import vip_level
from .rewards import Loot, client_cache, grant, merge_cache, pay, roll
from .shop import DAILY, LOCAL, period

MONTH_WEEK_AWARD = 2   # the popup reads both as an int; 2 is "already claimed"
SWEEP_FAILED_STEP = 0


def weekday(now: int) -> int:
    """1 = Monday ... 7 = Sunday, in the server's time zone (`active_chapter.open`)."""
    return datetime.fromtimestamp(now, LOCAL).isoweekday()


def _is_open(chapter: dict, now: int) -> bool:
    """`time_sort` 1: an hour range every day; 2: a list of weekday windows."""
    if chapter.get("time_sort") != 2:
        return True
    day = weekday(now)
    return any(low <= day <= high for low, high in chapter.get("open", []))


def todays_chapters(svc: Services, now: int) -> dict:
    """row key -> the chapter id the popup shows today. Exactly one per served chapter row:
    the popup indexes `index[<chapter>]` for it with no nil guard."""
    rows, chapters = svc.configs.get("active"), svc.configs.get("active_chapter")
    today = {}
    for key in ("40", "50", "60", "70"):
        ids = rows[key]["active_chapterID"]
        ids = ids[0] if ids and isinstance(ids[0], list) else ids
        open_now = [c for c in ids if _is_open(chapters[str(c)], now)]
        if open_now:
            today[key] = open_now[0]
    return today


def _row_of(svc: Services, chapter: int, now: int):
    return next((key for key, c in todays_chapters(svc, now).items() if c == chapter), None)


def _level_window(svc: Services, chapter: int, row: str) -> list:
    """Chapters from 100 carry their own window; the early ones use the hall row's."""
    if chapter >= 100:
        return svc.configs.get("active_chapter")[str(chapter)]["level"]
    return svc.configs.get("active")[row]["level"]


def _in(window, level: int) -> bool:
    return window[0] <= level <= window[1]


def _counter(svc, uid, chapter, name, now) -> int:
    return svc.store.counter(uid, f"act:{chapter}:{name}", period(DAILY, now))


def _set_counter(svc, uid, chapter, name, value, now) -> None:
    svc.store.set_counter(uid, f"act:{chapter}:{name}", max(0, value), period(DAILY, now))


def chapter_index(svc: Services, uid: str, chapter: int, now: int) -> dict:
    cfg = svc.configs.get("active_chapter")[str(chapter)]
    run = svc.store.active_run(uid, chapter)
    return {
        "cur_times": _counter(svc, uid, chapter, "done", now),
        "times": cfg["times"],
        "cur_buy_times": _counter(svc, uid, chapter, "bought", now),
        # Never `{"<id>": []}`: the map scene reads the last key's last step.
        "active_steps": {str(run[0]): run[1]} if run and run[1] else {},
    }


def active_index(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    chapters = todays_chapters(svc, now)
    return ok({
        "month_award": MONTH_WEEK_AWARD, "week_award": MONTH_WEEK_AWARD, "world_boss": 0,
        "index": {str(c): chapter_index(svc, uid, c, now) for c in chapters.values()},
        "gift_reward": {},
        "active_forever": survival.snapshot(svc, uid, now),
    })


# ---- chapter checks ----------------------------------------------------------

def _chapter_request(req: Request, svc: Services, player: dict, now: int):
    """(chapter id, stage id, step, stage row) of a valid request, or a failure body."""
    values = [req.params.get(k, "") for k in ("chapter", "active_id", "step_n")]
    if not all(is_int(v) for v in values):
        return fail("error_param", "Tham số không hợp lệ.")
    chapter, active_id, step = (int(v) for v in values)
    row = _row_of(svc, chapter, now)
    cfg = svc.configs.get("active_chapter").get(str(chapter))
    detail = svc.configs.get("active_detail").get(str(active_id))
    if row is None or cfg is None or detail is None or active_id not in cfg["active_detail"]:
        return fail("error_param", "Hoạt động không mở hôm nay.")
    if not (_in(_level_window(svc, chapter, row), player["level"])
            and _in(detail["level"], player["level"])):
        return fail("error_level", "Chưa đủ cấp.")
    if not 0 <= step < len(detail["fight"]):
        return fail("error_param", "Tham số không hợp lệ.")
    return chapter, active_id, step, detail


def map_fight_and_enemy(req: Request, svc: Services, player: dict):
    checked = _chapter_request(req, svc, player, int(time.time()))
    if isinstance(checked, dict):
        return checked
    _, _, step, detail = checked
    fight_id = str(detail["fight"][step][1])
    fight_row = svc.configs.get("map_fight")[fight_id]
    return ok({"map_fight": {fight_id: fight_row},
               "enemy_detail": {str(e): campaign._enemy(svc, "active", e)
                                for _, e in campaign._enemy_ids(fight_row)}})


# ---- runs -------------------------------------------------------------------

def _start_or_continue(svc, uid, chapter, active_id, step, cfg, now) -> None:
    """Step 0 starts a run (one attempt, unless an unfinished run was already counted);
    any other step must follow the run's last won step. Raises Refused."""
    run = svc.store.active_run(uid, chapter)
    if step == 0:
        if run is None:
            done = _counter(svc, uid, chapter, "done", now)
            if done >= cfg["times"]:
                raise Refused("error_times", "Hết lượt tham gia hôm nay.")
            _set_counter(svc, uid, chapter, "done", done + 1, now)
        svc.store.set_active_run(uid, chapter, active_id, [])
    elif run is None or run[0] != active_id or step != len(run[1]):
        raise Refused("error_param", "Chưa thắng các bước trước.")


def _stage_loot(detail: dict, first: bool, rng: random.Random) -> Loot:
    """Guaranteed 3-field entries, one roll over the weighted 4-field ones, plus the
    stage's first-clear pair the first time."""
    loot = Loot.of([e for e in detail.get("reward", []) if len(e) == 3])
    if (extra := roll(detail.get("reward", []), rng)) is not None:
        loot.add(*extra)
    if first:
        for entry in detail.get("reward_first_base", []):
            loot.add(*entry[:3])
        if (bonus := roll(detail.get("reward_first_rate", []), rng)) is not None:
            loot.add(*bonus)
    return loot


def _finish_run(svc, uid, chapter, active_id, detail, now):
    """Pay the stage and close the run."""
    first_key = f"act:first:{active_id}"
    first = svc.store.counter(uid, first_key) == 0
    svc.store.set_counter(uid, first_key, 1)
    svc.store.clear_active_run(uid, chapter)
    return grant(svc, uid, _stage_loot(detail, first, random.Random()), now)


def fight(req: Request, svc: Services, player: dict):
    now, uid = int(time.time()), player["uid"]
    checked = _chapter_request(req, svc, player, now)
    if isinstance(checked, dict):
        return checked
    chapter, active_id, step, detail = checked
    if req.params.get("is_sweep") == "1":
        return _sweep(svc, player, chapter, active_id, detail, now)
    cfg = svc.configs.get("active_chapter")[str(chapter)]
    _start_or_continue(svc, uid, chapter, active_id, step, cfg, now)

    fight_row = svc.configs.get("map_fight")[str(detail["fight"][step][1])]
    attackers = campaign._attackers(svc, uid, player["level"])
    defenders = campaign._defenders(svc, "active", fight_row, random.Random())
    data = campaign.run_battle(svc, uid, player, attackers, defenders, fight_row)
    won, last = data["battle"]["winer"] == WIN, step == len(detail["fight"]) - 1
    data["next_step"] = (-1 if last else step + 1) if won else step
    if won:
        data.update(_win(svc, uid, chapter, active_id, step, last, detail, fight_row,
                         attackers, now))
    return ok(data)


def _win(svc, uid, chapter, active_id, step, last, detail, fight_row, attackers, now) -> dict:
    rewards, cards = campaign.battle_exp(svc, uid, fight_row, attackers, now)
    cache = client_cache(svc, uid, cards=cards)
    reward = {}
    if last:
        granted = _finish_run(svc, uid, chapter, active_id, detail, now)
        reward, cache = granted.reward, merge_cache(cache, granted.cache)
        rewards["reward_character"] = [{"c_id": str(c["c_id"])}
                                       for c in campaign._new_cards(svc, uid, granted)]
    else:
        run = svc.store.active_run(uid, chapter)
        svc.store.set_active_run(uid, chapter, active_id, [*run[1], step])
    return {"battle_rewards": rewards, "reward": reward, "_client_cache_update": cache}


def _sweep(svc, player, chapter, active_id, detail, now) -> dict:
    """Instant clear for a team that out-powers the stage: one attempt, final reward only."""
    uid, cfg = player["uid"], svc.configs.get("active_chapter")[str(chapter)]
    done = _counter(svc, uid, chapter, "done", now)
    if svc.store.active_run(uid, chapter) is not None:
        return fail("error_param", "Đang có lượt chưa xong.")
    if done >= cfg["times"]:
        return fail("error_times", "Hết lượt tham gia hôm nay.")
    if team_combat(svc, uid) < detail.get("combat_need", 0):
        return ok({"next_step": SWEEP_FAILED_STEP, "done_times": cfg["times"] - done,
                   "sweep_reward": {}})
    _set_counter(svc, uid, chapter, "done", done + 1, now)
    granted = _finish_run(svc, uid, chapter, active_id, detail, now)
    return ok({"next_step": -1, "done_times": cfg["times"] - done - 1,
               "sweep_reward": granted.reward, "_client_cache_update": granted.cache})


def buy_fight_times(req: Request, svc: Services, player: dict):
    now, uid = int(time.time()), player["uid"]
    chapter = req.params.get("chapter", "")
    cfg = svc.configs.get("active_chapter").get(chapter) if is_int(chapter) else None
    if cfg is None or _row_of(svc, int(chapter), now) is None:
        return fail("error_param", "Tham số không hợp lệ.")
    chapter = int(chapter)
    level = vip_level(svc.configs, svc.store.wallet(uid).get("vip_exp", 0))
    bought = _counter(svc, uid, chapter, "bought", now)
    if svc.configs.get("vip")[str(level)].get("active_times") != 1 or bought >= len(cfg["vip_buy"]):
        return fail("error_times", "Không thể mua thêm lượt.")
    pay(svc, uid, {"coin": cfg["vip_buy"][bought]})
    _set_counter(svc, uid, chapter, "bought", bought + 1, now)
    _set_counter(svc, uid, chapter, "done", _counter(svc, uid, chapter, "done", now) - 1, now)
    return ok({})


def clear_fight_log(req: Request, svc: Services, player: dict):
    chapter = req.params.get("chapter", "")
    if not is_int(chapter):
        return fail("error_param", "Tham số không hợp lệ.")
    svc.store.clear_active_run(player["uid"], int(chapter))
    return ok({})


HANDLERS = {
    ("api", "active.index"): active_index,
    ("api", "active.map_fight_and_enemy"): map_fight_and_enemy,
    ("api", "active.fight"): fight,
    ("api", "active.buy_fight_times"): buy_fight_times,
    ("api", "active.clear_fight_log"): clear_fight_log,
    **survival.HANDLERS,
}
