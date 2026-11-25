"""Game-master tool: make an account, look items and heroes up, give anything to any account.

    python3 -m tools.admin account GM  secret123            # a game-master account, level 120
    python3 -m tools.admin find  "Tề Thiên"                 # ids of items, heroes, gear, gems
    python3 -m tools.admin give  GM --card 6500 --card 7900:3 --item 1018:99 --coin 5000000
    python3 -m tools.admin give  GM --cur silver=100000 --equip 10101 --gem 502:20 --level 100
    python3 -m tools.admin show  GM
    python3 -m tools.admin token                            # secret for the phone app (gm-app/)

Run it against the same database as the server (`--db`, default data/sahht.db). Restart the
game client (or log in again) afterwards: cards and items reach the client in the login
replies. Heroes after the 2018 cut (id > 38700) are refused like in the game, unless
`--allow-late` is given; they have no skill specs, so they fight without skills.

This writes the database directly. It is a local development tool: do not expose it.
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

from sahht_server import gm
from sahht_server.handlers import ConfigCache, Services
from sahht_server.scope import DEFAULT_PATH, Scope
from sahht_server.store import Store

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT.parent / "decompiled" / "apk" / "assets" / "config"
TOKEN_PATH = ROOT / "data" / "admin_token"


def open_services(db: Path) -> Services:
    """The parts of Services that the game-master operations read, over the real database."""
    return Services(store=Store(str(db)), config_dir=CONFIG_DIR, version_map={},
                    all_config_version="", configs=ConfigCache(CONFIG_DIR),
                    scope=Scope.load(DEFAULT_PATH))


def cmd_account(args, svc) -> None:
    result = gm.ensure_account(svc, args.account, args.password, args.level)
    print(("đã tạo" if result["created"] else "đã có, cập nhật"),
          f"tài khoản {args.account}: uid {result['uid']}, cấp {args.level}, ví đầy.")


def cmd_give(args, svc) -> None:
    loot = gm.parse_loot(svc.configs, cards=args.card, items=args.item, equips=args.equip,
                         gems=args.gem, currencies=args.cur + [f"coin={a}" for a in args.coin])
    print(f"đã cấp cho {args.account}: "
          f"{gm.give(svc, args.account, loot, args.level, getattr(args, 'allow_late', False))}")
    print("Khởi động lại game (hoặc đăng nhập lại) để thấy thay đổi.")


def cmd_find(args, svc) -> None:
    for group in gm.search(svc.configs, args.text, args.limit):
        print(f"== {group['label']} (--{group['kind']})")
        for row in group["rows"]:
            print(f"  {row['id']:>8}  {row['name']}")
        if group["more"]:
            print(f"  ... {group['more']} dòng nữa (tăng --limit)")


def cmd_show(args, svc) -> None:
    info = gm.overview(svc, args.account)
    print(f"{info['account']}: uid {info['uid']}, cấp {info['level']}, {info['cards']} thẻ tướng, "
          f"{info['items']} loại vật phẩm")
    print("ví:", info["wallet"])


def cmd_token(args, svc) -> None:
    """Create the phone app's secret once; `--new` replaces it (the app must be updated)."""
    if TOKEN_PATH.exists() and not args.new:
        print(TOKEN_PATH.read_text(encoding="utf-8").strip())
        return
    TOKEN_PATH.write_text(secrets.token_hex(16) + "\n", encoding="utf-8")
    os.chmod(TOKEN_PATH, 0o600)
    print(TOKEN_PATH.read_text(encoding="utf-8").strip())
    print("Khởi động lại server để bật dịch vụ quản trị.", file=sys.stderr)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "sahht.db"))
    ap.add_argument("--allow-late", action="store_true", help="cho phép tướng id > 38700")
    sub = ap.add_subparsers(dest="command", required=True)
    account = sub.add_parser("account", help="tạo hoặc cập nhật tài khoản GM")
    account.add_argument("account")
    account.add_argument("password")
    account.add_argument("--level", type=int, default=gm.GM_LEVEL)
    give = sub.add_parser("give", help="cấp thẻ tướng, vật phẩm, trang bị, đá quý, tiền")
    give.add_argument("account")
    for name, help_text in (("card", "ID[:SL] thẻ tướng"), ("item", "ID[:SL] vật phẩm"),
                            ("equip", "ID[:SL] trang bị"), ("gem", "MÃ[:SL] đá quý"),
                            ("cur", "TÊN=SL tiền tệ (vd silver=100000)"), ("coin", "SL xu")):
        give.add_argument(f"--{name}", action="append", default=[], help=help_text)
    give.add_argument("--level", type=int, default=0, help="đặt cấp người chơi")
    give.add_argument("--allow-late", action="store_true", default=argparse.SUPPRESS,
                      help="cho phép tướng id > 38700")
    find = sub.add_parser("find", help="tìm id theo tên")
    find.add_argument("text")
    find.add_argument("--limit", type=int, default=30)
    show = sub.add_parser("show", help="xem tóm tắt tài khoản")
    show.add_argument("account")
    token = sub.add_parser("token", help="in (hoặc tạo) token của app điện thoại")
    token.add_argument("--new", action="store_true", help="tạo token mới, thay token cũ")
    return ap


COMMANDS = {"account": cmd_account, "give": cmd_give, "find": cmd_find, "show": cmd_show,
            "token": cmd_token}


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    if args.command == "token":
        cmd_token(args, None)
        return
    svc = open_services(Path(args.db))
    try:
        COMMANDS[args.command](args, svc)
    except gm.GmError as error:
        sys.exit(str(error))
    finally:
        svc.store.close()


if __name__ == "__main__":
    main()
