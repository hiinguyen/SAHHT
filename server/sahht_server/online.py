"""Time a player spends online, for the welfare tab "Thưởng online" (reward_once sort 79).

The client keeps no heartbeat, so time is measured from the requests it makes: every
authenticated request adds the gap since the previous one to a lifetime counter, unless the
gap is longer than IDLE_LIMIT (the player left, so a login the next day is not "online all
night"). The client counts its own countdown between requests; a claim right after it ends
carries that gap, so the server never lags behind the countdown.
"""

from .handlers import Services

SECONDS = "online:seconds"
MARK = "online:mark"
IDLE_LIMIT = 30 * 60


def touch(svc: Services, uid: str, now: int) -> None:
    """Credit the time since the player's previous request."""
    store = svc.store
    mark = store.counter(uid, MARK)
    gap = now - mark
    if mark and 0 < gap <= IDLE_LIMIT:
        store.set_counter(uid, SECONDS, store.counter(uid, SECONDS) + gap)
    store.set_counter(uid, MARK, now)


def seconds(svc: Services, uid: str) -> int:
    """Seconds credited so far (up to the player's latest request)."""
    return svc.store.counter(uid, SECONDS)
