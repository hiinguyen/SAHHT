"""Event counting for the daily tasks (see quests.py); kept apart so game handlers can
call `record` without importing the quest screens."""

from .handlers import Services
from .shop import DAILY, period

SORT_FIGHT, SORT_SKILL, SORT_EQUIP, SORT_RESOURCE_WAR, SORT_EXP_STAGE, SORT_SURVIVAL = (
    78, 24, 35, 68, 76, 77)
# Task sorts a handler really reports; a daily task with another sort is not offered.
LIVE_SORTS = {SORT_FIGHT, SORT_SKILL, SORT_EQUIP, SORT_RESOURCE_WAR, SORT_EXP_STAGE,
              SORT_SURVIVAL}


def counter_name(sort: int) -> str:
    return f"quest:{sort}"


def record(svc: Services, uid: str, sort: int, now: int, amount: int = 1) -> None:
    """Count an event for today's daily tasks."""
    if sort not in LIVE_SORTS or amount <= 0:
        return
    day, name = period(DAILY, now), counter_name(sort)
    svc.store.set_counter(uid, name, svc.store.counter(uid, name, day) + amount, day)
