"""Mail: the inbox behind the "Thông tin" menu (notify.messages, notify.read, notify.auto_read).

Other modules send mail with `send`; a `key` makes it idempotent (a welcome mail is never
sent twice, even after it was claimed). The client replaces its whole list with the reply
of `read` and `auto_read`, so both answer `messages`, the mail that is still unclaimed.
`messages` and each message's `content`, `gift`, `send_name` and `id` are read unguarded.
"""

import time

from .handlers import ALERT_PROVIDERS, Refused, Request, Services, fail, is_int, ok
from .rewards import Granted, Loot, grant, merge_cache

DAY = 86400
DEFAULT_TTL_DAYS = 30
TOMBSTONE_DAYS = 30
SYSTEM_SENDER = "sys"


def send(svc: Services, uid: str, content: str, gift=(), *, key=None, title="",
         sender=SYSTEM_SENDER, ttl_days=DEFAULT_TTL_DAYS, now=None) -> int | None:
    """Put a mail in the player's inbox; None when `key` was already sent."""
    now = int(time.time()) if now is None else now
    return svc.store.add_mail(uid, key=key, sender=sender, title=title, content=content,
                              gift=[list(g) for g in gift], now=now, ttl=ttl_days * DAY)


def has_unclaimed(svc: Services, uid: str, now: int) -> bool:
    return bool(svc.store.mail_inbox(uid, now, limit=1))


ALERT_PROVIDERS["notify"] = has_unclaimed


def _messages(svc: Services, uid: str, now: int) -> list:
    return [{"id": str(m["id"]), "send_name": m["sender"], "title": m["title"],
             "content": m["content"], "gift": m["gift"]}
            for m in svc.store.mail_inbox(uid, now)]


def notify_messages(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    svc.store.purge_mail(uid, now - TOMBSTONE_DAYS * DAY)
    return ok({"messages": _messages(svc, uid, now)})


def _claim(svc: Services, uid: str, mail_ids: list, now: int) -> Granted:
    """Mark the mail claimed and grant their gifts as one loot; raises Refused to roll back."""
    loot = Loot()
    for mail_id in mail_ids:
        row = svc.store.mail_row(uid, mail_id, now)
        if row is None or not svc.store.claim_mail(uid, mail_id, now):
            raise Refused("error_param", "Thư không tồn tại hoặc đã nhận.")
        loot.merge(Loot.of(row["gift"]))
    return grant(svc, uid, loot, now)


def _answer(svc: Services, uid: str, now: int, granted: Granted | None):
    return ok({"messages": _messages(svc, uid, now),
               "reward": granted.reward if granted else {},
               "_client_cache_update": granted.cache if granted else {}})


def notify_read(req: Request, svc: Services, player: dict):
    uid, now = player["uid"], int(time.time())
    mail_id = req.params.get("message_id", "")
    if not is_int(mail_id):
        return fail("error_param", "Thư không hợp lệ.")
    with svc.store.transaction():
        granted = _claim(svc, uid, [int(mail_id)], now)
    return _answer(svc, uid, now, granted)


def notify_auto_read(req: Request, svc: Services, player: dict):
    """Claim every listed mail the player still has; unknown ids are skipped."""
    uid, now = player["uid"], int(time.time())
    wanted = {int(i) for i in req.params.get("message_id", "").split("|") if is_int(i)}
    ids = [row["id"] for row in svc.store.mail_inbox(uid, now) if row["id"] in wanted]
    if not ids:
        return _answer(svc, uid, now, None)
    try:
        with svc.store.transaction():
            granted = _claim(svc, uid, ids, now)
    except Refused:
        granted = _claim_until_refused(svc, uid, ids, now)
    return _answer(svc, uid, now, granted)


def _claim_until_refused(svc: Services, uid: str, ids: list, now: int) -> Granted:
    """The merged grant was refused (a full bag): claim one by one and stop at the first
    refusal; when nothing could be claimed the refusal is the answer."""
    total = None
    for mail_id in ids:
        try:
            with svc.store.transaction():
                granted = _claim(svc, uid, [mail_id], now)
        except Refused:
            if total is None:
                raise
            break
        total = granted if total is None else _combine(total, granted)
    return total


def _combine(first: Granted, second: Granted) -> Granted:
    reward = dict(first.reward)
    for key, value in second.reward.items():
        reward[key] = reward.get(key, [] if isinstance(value, list) else 0) + value
    return Granted(reward, merge_cache(first.cache, second.cache),
                   first.card_ids + second.card_ids, first.equip_ids + second.equip_ids,
                   second.level)


HANDLERS = {
    ("api", "notify.messages"): notify_messages,
    ("api", "notify.read"): notify_read,
    ("api", "notify.auto_read"): notify_auto_read,
}
