"""
Local bridge: serves the web panel and exposes every OpenPath feature to it as
a small JSON API.

Why a bridge: the panel on GitHub Pages is a static file, so it cannot call the
Cloudflare API or start a proxy on your phone by itself. When you run

    openpath panel

OpenPath starts this bridge on 127.0.0.1, serves the very same panel from it
(same origin, so no CORS / mixed-content problem) and injects a short session
code. The panel then drives the real work: deploying workers, starting the DPI
proxy, running latency tests, ...

Endpoints all live under /api/ and need the code in `X-OpenPath-Code` (the
injected page does this automatically).
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple

from . import cf as cf_mod
from . import configs, dpi as dpi_mod
from . import gas as gas_mod
from . import net as net_mod
from . import paas as paas_mod
from . import sub as sub_mod
from . import util
from . import warp as warp_mod

VERSION = "1.0.0"

PANEL_DIR_CANDIDATES = ("panel", os.path.join("..", "panel"), os.path.join("..", "..", "panel"))

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def panel_dir() -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "..", "panel"), os.path.join(os.getcwd(), "panel")]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(os.path.join(path, "index.html")):
            return path
    return None


def new_code(n: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    import secrets

    return "".join(secrets.choice(alphabet) for _ in range(n))


class BridgeState:
    def __init__(self) -> None:
        self.code = new_code()
        self.dpi: Optional[dpi_mod.DesyncProxy] = None
        self.gas: Optional[gas_mod.ProxyServer] = None
        self.sub_server = None
        self.sub_port = 0
        self.panel_dir = panel_dir()


STATE = BridgeState()


# --------------------------------------------------------------------------- #
# API implementation
# --------------------------------------------------------------------------- #
def api_hello(_body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "version": VERSION,
        "bridge": True,
        "python": __import__("sys").version.split()[0],
        "termux": util.is_termux(),
        "persian": util.persian_supported(),
    }


def api_state(_body: Dict[str, Any]) -> Dict[str, Any]:
    st = util.get_state()
    return {
        "ok": True,
        "cf_token_set": bool(cf_mod.token()),
        "gas_url": st.get("gas_url", ""),
        "gas_key_set": bool(st.get("gas_key")),
        "workers": cf_mod.deployments(),
        "warp": warp_mod.load(),
        "saved_subs": len(sub_mod.load()),
        "dpi_running": bool(STATE.dpi),
        "gas_running": bool(STATE.gas),
        "sub_port": STATE.sub_port,
    }


def api_configs(body: Dict[str, Any]) -> Dict[str, Any]:
    cfgs = [configs.normalize(c) for c in (body.get("configs") or [])]
    fmt = (body.get("format") or "b64").lower()
    mode = body.get("mode") or "global"
    if fmt == "links":
        out = [configs.to_uri(c) for c in cfgs]
        return {"ok": True, "links": out}
    try:
        text = sub_mod.export(cfgs, fmt, mode)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "output": text, "count": len(cfgs)}


def api_parse(body: Dict[str, Any]) -> Dict[str, Any]:
    text = body.get("text") or ""
    cfgs = configs.parse_any(text)
    return {"ok": True, "configs": cfgs, "count": len(cfgs)}


def api_cf_deploy(body: Dict[str, Any]) -> Dict[str, Any]:
    if body.get("token"):
        cf_mod.set_token(body["token"])
    settings = body.get("settings") or cf_mod.default_settings(body.get("node_name") or "OpenPath")
    settings.setdefault("uuid", configs.new_uuid())
    settings.setdefault("trojan_password", configs.rand_password(12))
    settings.setdefault("ws_path", "/" + util.rand_hex(4))
    settings.setdefault("sub_path", "sub-" + util.rand_hex(3))
    script_name = util.safe_name(body.get("script_name") or f"openpath-{util.rand_hex(3)}")
    script = cf_mod.render_worker(settings)
    info = cf_mod.deploy(script_name, script, body.get("account_id"))
    cf_mod.save_deployment(info, settings)
    host = (info.get("url") or "").replace("https://", "").replace("http://", "").strip("/")
    cfgs = cf_mod.worker_configs(host, settings, clean_ip=body.get("clean_ip") or "")
    sub_url = cf_mod.subscription_url(host, settings.get("sub_path", "sub"))
    return {"ok": True, "deployment": info, "settings": settings, "configs": cfgs, "subscription": sub_url}


def api_cf_render(body: Dict[str, Any]) -> Dict[str, Any]:
    settings = body.get("settings") or cf_mod.default_settings()
    return {"ok": True, "code": cf_mod.render_worker(settings), "settings": settings}


def api_cf_list(_body: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "workers": cf_mod.deployments()}


def api_warp_generate(body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        count = max(1, min(5, int(body.get("count") or 1)))
        cfgs = warp_mod.generate(license_key=(body.get("license") or ""), count=count, verbose=False)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "configs": cfgs, "conf": [warp_mod.conf(c) for c in cfgs]}


def api_gas_script(body: Dict[str, Any]) -> Dict[str, Any]:
    path, key = gas_mod.write_script(auth_key=body.get("key") or None)
    gas_mod.configure(key=key)
    return {"ok": True, "path": path, "key": key, "code": util.read_text(path)}


def api_gas_configure(body: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "config": gas_mod.configure(body.get("url") or "", body.get("key") or "")}


def api_gas_test(_body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        relay = gas_mod.Relay()
        ms = relay.ping()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": ms is not None, "ms": round(ms, 1) if ms else None}


def api_gas_serve(body: Dict[str, Any]) -> Dict[str, Any]:
    if STATE.gas:
        return {"ok": True, "already": True, "port": STATE.gas.port}
    port = int(body.get("port") or 8080)
    try:
        STATE.gas = gas_mod.serve_forever(port=port, mitm=bool(body.get("mitm", True)))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "port": port, "ca": gas_mod.ca_cert_path()}


def api_gas_stop(_body: Dict[str, Any]) -> Dict[str, Any]:
    if STATE.gas:
        STATE.gas.stop()
        STATE.gas = None
    return {"ok": True}


def api_dpi_start(body: Dict[str, Any]) -> Dict[str, Any]:
    if STATE.dpi:
        return {"ok": True, "already": True, "port": STATE.dpi.port}
    port = int(body.get("port") or 8081)
    try:
        STATE.dpi = dpi_mod.start(
            port=port,
            chunks=int(body.get("chunks") or 3),
            delay=float(body.get("delay") or 0.012),
            fake=bool(body.get("fake", True)),
            sni_spoof=bool(body.get("sni_spoof", False)),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "port": port}


def api_dpi_stop(_body: Dict[str, Any]) -> Dict[str, Any]:
    if STATE.dpi:
        STATE.dpi.stop()
        STATE.dpi = None
    return {"ok": True}


def api_sub_fetch(body: Dict[str, Any]) -> Dict[str, Any]:
    cfgs, report = sub_mod.collect(
        source_ids=body.get("sources") or None,
        extra_urls=body.get("urls") or None,
        limit_per_source=int(body.get("limit") or 40),
        progress=False,
    )
    cfgs = sub_mod.rename(cfgs, body.get("prefix") or "OpenPath")
    sub_mod.save(cfgs)
    return {"ok": True, "configs": cfgs, "report": report, "count": len(cfgs)}


def api_sub_serve(body: Dict[str, Any]) -> Dict[str, Any]:
    cfgs = [configs.normalize(c) for c in (body.get("configs") or [])] or sub_mod.load()
    if not cfgs:
        return {"ok": False, "error": "no configs to serve"}
    if STATE.sub_server:
        try:
            STATE.sub_server.shutdown()
        except Exception:
            pass
    httpd, port = sub_mod.serve(cfgs, host="0.0.0.0", port=int(body.get("port") or 0), mode=body.get("mode") or "global")
    STATE.sub_server, STATE.sub_port = httpd, port
    ip = _lan_ip()
    return {"ok": True, "port": port, "local": f"http://127.0.0.1:{port}/sub", "lan": f"http://{ip}:{port}/sub" if ip else None}


def api_test(body: Dict[str, Any]) -> Dict[str, Any]:
    cfgs = [configs.normalize(c) for c in (body.get("configs") or [])]
    if not cfgs:
        return {"ok": False, "error": "no configs"}
    results = net_mod.test_many(cfgs, workers=int(body.get("workers") or 24), timeout=float(body.get("timeout") or 4))
    return {"ok": True, "results": results}


def api_speed(body: Dict[str, Any]) -> Dict[str, Any]:
    proxy = body.get("proxy")
    return {"ok": True, "result": net_mod.speed_test(proxy=proxy, size=int(body.get("size") or 1_000_000))}


def api_paas_presets(_body: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "presets": paas_mod.PRESETS}


def api_paas_render(body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = paas_mod.render_deploy(
            name=body.get("name") or "openpath",
            repo=body.get("repo") or "",
            branch=body.get("branch") or "main",
            region=body.get("region") or "frankfurt",
            preset=body.get("preset") or "vless-ws",
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


def api_paas_codespace(body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = paas_mod.codespace_deploy(
            repo=body.get("repo") or "", preset=body.get("preset") or "vless-ws", ref=body.get("ref") or "main"
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


def api_settings(body: Dict[str, Any]) -> Dict[str, Any]:
    data = {k: v for k, v in body.items() if k in ("cf_token", "render_key", "gas_url", "gas_key")}
    if data.get("cf_token"):
        cf_mod.set_token(data["cf_token"])
    if data.get("render_key"):
        util.set_key("render_key", data["render_key"])
    return {"ok": True, "saved": sorted(data.keys())}


def api_worker_code(body: Dict[str, Any]) -> Dict[str, Any]:
    settings = body.get("settings") or cf_mod.default_settings()
    return {"ok": True, "code": cf_mod.render_worker(settings)}


def api_gas_code(_body: Dict[str, Any]) -> Dict[str, Any]:
    code, key = gas_mod.render_script()
    return {"ok": True, "code": code, "key": key}


def api_selftest(_body: Dict[str, Any]) -> Dict[str, Any]:
    from .selftest import run_selftest

    passed, failed, lines = run_selftest()
    return {"ok": failed == 0, "passed": passed, "failed": failed, "lines": lines}


ROUTES: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "/api/hello": api_hello,
    "/api/state": api_state,
    "/api/settings": api_settings,
    "/api/configs": api_configs,
    "/api/parse": api_parse,
    "/api/cf/deploy": api_cf_deploy,
    "/api/cf/render": api_cf_render,
    "/api/cf/list": api_cf_list,
    "/api/worker/code": api_worker_code,
    "/api/gas/code": api_gas_code,
    "/api/gas/script": api_gas_script,
    "/api/gas/configure": api_gas_configure,
    "/api/gas/test": api_gas_test,
    "/api/gas/serve": api_gas_serve,
    "/api/gas/stop": api_gas_stop,
    "/api/dpi/start": api_dpi_start,
    "/api/dpi/stop": api_dpi_stop,
    "/api/warp/generate": api_warp_generate,
    "/api/sub/fetch": api_sub_fetch,
    "/api/sub/serve": api_sub_serve,
    "/api/test": api_test,
    "/api/speed": api_speed,
    "/api/paas/presets": api_paas_presets,
    "/api/paas/render": api_paas_render,
    "/api/paas/codespace": api_paas_codespace,
    "/api/selftest": api_selftest,
}


def _lan_ip() -> Optional[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OpenPathBridge/" + VERSION

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("OPENPATH_DEBUG"):
            super().log_message(fmt, *args)

    # -- helpers ----------------------------------------------------------- #
    def _cors(self, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-OpenPath-Code")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: str, inject: bool = False) -> None:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._json({"ok": False, "error": "not found"}, 404)
        ctype = STATIC_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        if inject and ctype.startswith("text/html"):
            snippet = (
                f'<script>window.OPENPATH_BRIDGE="";window.OPENPATH_CODE="{STATE.code}";'
                f'window.OPENPATH_VERSION="{VERSION}";</script>'
            ).encode()
            data = data.replace(b"</head>", snippet + b"</head>", 1)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # -- verbs ------------------------------------------------------------- #
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        if route.startswith("/api/"):
            handler = ROUTES.get(route)
            if not handler:
                return self._json({"ok": False, "error": f"unknown endpoint {route}"}, 404)
            if route != "/api/hello":
                code = self.headers.get("X-OpenPath-Code") or (urllib.parse.parse_qs(parsed.query).get("code") or [""])[0]
                if code != STATE.code:
                    return self._json({"ok": False, "error": "bad code"}, 401)
            try:
                return self._json(handler({}))
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)}, 500)
        # static panel
        base = STATE.panel_dir or panel_dir()
        if not base:
            return self._json({"ok": False, "error": "panel folder not found"}, 404)
        rel = route.lstrip("/") or "index.html"
        if rel == "":
            rel = "index.html"
        target = os.path.normpath(os.path.join(base, rel))
        if not target.startswith(os.path.normpath(base)):
            return self._json({"ok": False, "error": "forbidden"}, 403)
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        inject = rel in ("index.html", "")
        return self._file(target, inject=inject)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path.rstrip("/")
        handler = ROUTES.get(route)
        if not handler:
            return self._json({"ok": False, "error": f"unknown endpoint {route}"}, 404)
        code = self.headers.get("X-OpenPath-Code") or (urllib.parse.parse_qs(parsed.query).get("code") or [""])[0]
        if code != STATE.code:
            return self._json({"ok": False, "error": "bad code"}, 401)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return self._json({"ok": False, "error": "bad json"}, 400)
        try:
            return self._json(handler(body))
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, 500)


def start(host: str = "127.0.0.1", port: int = 0, open_browser: bool = True) -> Tuple[ThreadingHTTPServer, int, str]:
    port = port or util.free_port(8765, host=host)
    httpd = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        util.open_url(url)
    return httpd, port, url
