"""HTTP front end: routing, session guard, request log."""

import argparse
import errno
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import campaign, cards, gacha, handlers, payment, shop
from . import scope as scope_module
from .player import user_status
from .handlers import ConfigCache, Request, Services
from .scope import Scope
from .store import Store

SESSION_HANDLERS = {**handlers.SESSION_HANDLERS, **campaign.HANDLERS, **cards.HANDLERS,
                    **gacha.HANDLERS, **shop.HANDLERS, **payment.HANDLERS}
SERVICES = {"login", "api", "config", "pay", "dataosha", "lua_ver"}
SESSION_SERVICES = {"api", "pay", "dataosha"}
QUIET_SERVICES = {"dataosha"}   # the client's own analytics: answered, never shown
CLOSED_MSG = "Tính năng chưa mở."
REDACTED_PARAMS = {"passwd", "rans"}
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")
VERSION_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
NOT_FOUND = {"error": {"code": "NOT_FOUND", "message": "Không tìm thấy đối tượng."}}
MAX_BODY = 64 * 1024   # the largest client POST (cards.set_alignment) is a few hundred bytes


class RequestLog:
    """Append-only JSONL of every request, so unimplemented methods show up as work to do."""

    def __init__(self, path):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()

    def write(self, service, method, params, flag=None):
        """`flag` is "quiet" or "closed" for methods with no handler: the work still to do."""
        if self._path is None:
            return
        safe = {k: "<redacted>" if k in REDACTED_PARAMS else v for k, v in params.items()}
        record = {"service": service, "method": method, "params": safe}
        if flag:
            record[flag] = True
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class GameHandler(BaseHTTPRequestHandler):
    server_version = "sahht"

    def log_message(self, *_):
        pass  # the JSONL request log replaces the default access log

    def do_GET(self):
        self._handle(b"")

    def do_POST(self):
        """A few calls (cards.set_alignment, cards.butcher) send their params as a form body."""
        length = self.headers.get("Content-Length", "0")
        if not handlers.is_int(length) or int(length) > MAX_BODY:
            self._send(413, {"error": {"code": "TOO_LARGE", "message": "Yêu cầu quá lớn."}})
            return
        self._handle(self.rfile.read(int(length)))

    def _handle(self, form: bytes):
        try:
            status, body = self._route(form)
        except Exception as exc:  # a handler bug must not kill the connection thread
            # Path and method only: the query string carries the session ticket.
            where = urlsplit(self.path)
            method = parse_qs(where.query).get("method", ["?"])[0]
            print(f"internal error on {where.path} {method}: {exc!r}", file=sys.stderr)
            status, body = 500, {"error": {"code": "INTERNAL", "message": "Lỗi máy chủ."}}
        self._send(status, body)

    def _send(self, status, body):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self, form: bytes):
        url = urlsplit(self.path)
        lists = parse_qs(url.query, keep_blank_values=True)
        for key, values in parse_qs(form.decode("utf-8", "replace"), keep_blank_values=True).items():
            lists.setdefault(key, []).extend(values)
        params = {k: v[0] for k, v in lists.items()}
        parts = [p for p in url.path.split("/") if p]
        index = next((i for i, p in enumerate(parts) if p in SERVICES), None)
        if index is None:
            return 404, NOT_FOUND

        service, method = parts[index], params.get("method", "")
        host = self.headers.get("Host", "")
        if not HOST_RE.match(host):
            host = f"127.0.0.1:{self.server.server_address[1]}"
        prefix = "".join(f"/{p}" for p in parts[:index])
        req = Request(service, method, params, f"http://{host}{prefix}", host.split(":")[0], lists)
        svc = self.server.services

        if service == "lua_ver":
            version = parts[-1].removesuffix(".json")
            if index == len(parts) - 1 or not VERSION_RE.match(version):
                return 404, NOT_FOUND
            return 200, handlers.lua_manifest(version)

        body, flag = self._dispatch(req, svc)
        self.server.request_log.write(service, method, params, flag)
        return 200, body

    def _dispatch(self, req, svc):
        """(body, log flag): the flag is None, "quiet" or "closed"."""
        if req.service == "config":
            if req.method == "all_config":
                return handlers.all_config(req, svc), None
            return _refused(req.method), None
        if req.service == "login" and req.method in handlers.LOGIN_HANDLERS:
            return handlers.LOGIN_HANDLERS[req.method](req, svc), None

        handler = SESSION_HANDLERS.get((req.service, req.method))
        if handler is None and req.service not in SESSION_SERVICES:
            return _refused(req.method), None  # e.g. an unimplemented login method

        player = self._session_player(req, svc)
        if player is None:
            return handlers.need_login(), None
        flag, handler = _resolve(req, svc.scope, handler)
        # One transaction per request: concurrent requests of a player cannot interleave
        # their checks and writes, a crash leaves nothing half done, and a refusal
        # (an error status) never keeps a partial change.
        try:
            with svc.store.transaction():
                body = handler(req, svc, player)
                if body.get("status") != 0:
                    raise handlers.Refused.of(body)
                body["user_status"] = user_status(svc, player["uid"])
        except handlers.Refused as refused:
            body = refused.body
            body["user_status"] = user_status(svc, player["uid"])
        return body, flag

    @staticmethod
    def _session_player(req, svc):
        """The player the (ticket, user_token) pair identifies, or None."""
        account = svc.store.account_for_ticket(req.params.get("rans", ""))
        player = svc.store.player_for_uid(req.params.get("user_token", ""))
        if account is None or player is None or player["account"] != account:
            return None
        return player


def _resolve(req, scope: Scope, handler):
    """(log flag, handler) for a session request. Without a handler, a background call
    recorded in the scope gets its verified empty body, the client's analytics an empty
    success, and anything else a popup: an empty success would let the screen run on
    and fail on missing fields."""
    if handler is not None:
        return None, handler
    body = scope.quiet_body(req.method) if req.service == "api" else None
    if body is not None or req.service in QUIET_SERVICES:
        return "quiet", lambda *_: handlers.ok(body or {})
    return "closed", _closed


def _closed(*_):
    return handlers.fail("error_not_open", CLOSED_MSG)


def _refused(method):
    return handlers.fail("refused", f"chưa hỗ trợ: {method}")


class GameServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self):
        super().server_close()
        self.services.store.close()


def build_server(host, port, db_path, config_dir, version_map_path, request_log, scope_path=None):
    version_map = json.loads(Path(version_map_path).read_text(encoding="utf-8"))
    scope = Scope.load(scope_path or scope_module.DEFAULT_PATH)   # a bad file stops the start
    # Bound only once services exist: a failed bind calls server_close(), which closes the store.
    server = GameServer((host, port), GameHandler, bind_and_activate=False)
    server.services = Services(
        store=Store(str(db_path)),
        config_dir=Path(config_dir),
        version_map=version_map,
        all_config_version=handlers.version_map_etag(version_map),
        configs=ConfigCache(config_dir),
        scope=scope,
    )
    server.request_log = RequestLog(request_log)
    try:
        server.server_bind()
        server.server_activate()
    except BaseException:
        server.server_close()
        raise
    return server


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Minimal private server for the SAHHT client.")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--db", default=str(root / "data" / "sahht.db"))
    ap.add_argument("--config-dir", default=str(root.parent / "decompiled" / "apk" / "assets" / "config"))
    ap.add_argument("--version-map", default=str(root / "data" / "game_config_version.json"))
    ap.add_argument("--request-log", default=str(root / "data" / "requests.jsonl"))
    ap.add_argument("--scope", default=str(root / "data" / "scope_2018.json"))
    args = ap.parse_args()

    try:
        server = build_server(args.host, args.port, args.db, args.config_dir,
                              args.version_map, args.request_log, args.scope)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        sys.exit(f"port {args.port} on {args.host} is already in use by another process; "
                 f"find it with: ss -ltnp 'sport = :{args.port}'")
    print(f"listening on http://{args.host}:{server.server_address[1]}/pub_abroad_vr", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
