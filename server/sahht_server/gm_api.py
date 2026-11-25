"""The `admin` HTTP service: `gm.py` behind a secret token, for the phone app.

Off unless the server was started with a token (`data/admin_token`, made by
`python3 -m tools.admin token`). Every call is a GET with `token=<secret>`; the answers carry
`Access-Control-Allow-Origin: *` (see `app.py`) because the app's page is a local file.
Whoever holds the token can give anything to any account and create accounts, so keep it
private and prefer to reach the server over a trusted network.

    admin.ping                                  -> {"ok": true}
    admin.accounts                              -> [{account, uid, level}]
    admin.show     account=                     -> overview of one account
    admin.search   q=                           -> id search groups (cards, items, gear, gems)
    admin.create   account= passwd= [level=]    -> make or refresh a game-master account
    admin.give     account= [card= item= equip= gem= cur=] [level=] [late=1]
                   each list is comma separated `ID[:count]`; `cur` is `name=amount`
"""

import hmac

from . import gm
from .handlers import Request, Services, fail, is_int, ok

MAX_LIST = 200


def _list(req: Request, key: str) -> list:
    """A comma separated parameter (repeated parameters are joined too)."""
    values = req.lists.get(key, [])
    return [part for value in values for part in value.split(",") if part.strip()][:MAX_LIST]


def _level(req: Request, default: int = 0) -> int:
    value = req.params.get("level", "")
    if not value:
        return default
    if not is_int(value) or not 1 <= int(value) <= 999:
        raise gm.GmError("cấp không hợp lệ")
    return int(value)


def _account(req: Request) -> str:
    account = req.params.get("account", "").strip()
    if not account:
        raise gm.GmError("thiếu tên tài khoản")
    return account


def _create(req: Request, svc: Services):
    return gm.ensure_account(svc, _account(req), req.params.get("passwd", ""),
                             _level(req, gm.GM_LEVEL))


def _give(req: Request, svc: Services):
    loot = gm.parse_loot(svc.configs, cards=_list(req, "card"), items=_list(req, "item"),
                         equips=_list(req, "equip"), gems=_list(req, "gem"),
                         currencies=_list(req, "cur"))
    return {"summary": gm.give(svc, _account(req), loot, _level(req),
                               allow_late=req.params.get("late") == "1")}


METHODS = {
    "admin.ping": lambda req, svc: {"ok": True},
    "admin.accounts": lambda req, svc: gm.accounts(svc),
    "admin.show": lambda req, svc: gm.overview(svc, _account(req)),
    "admin.search": lambda req, svc: gm.search(svc.configs, req.params.get("q", "")),
    "admin.create": _create,
    "admin.give": _give,
}


def authorized(req: Request, token: str | None) -> bool:
    """Constant-time check of the request's token against the configured one."""
    return bool(token) and hmac.compare_digest(req.params.get("token", "").encode(), token.encode())


def handle(req: Request, svc: Services, token: str | None) -> dict:
    if token is None:
        return fail("error_not_open", "Dịch vụ quản trị đang tắt.")
    if not authorized(req, token):
        return fail("error_token", "Sai token quản trị.")
    method = METHODS.get(req.method)
    if method is None:
        return fail("refused", f"chưa hỗ trợ: {req.method}")
    try:
        return ok(method(req, svc))
    except gm.GmError as error:
        return fail("error_param", str(error))
