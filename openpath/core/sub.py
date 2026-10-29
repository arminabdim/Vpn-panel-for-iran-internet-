"""
Subscription tools: collect public configs, merge your own, de-duplicate,
convert, and serve the result over HTTP so v2rayNG / MahsaNG can import it
with a single URL.

Honest warning, printed by the CLI too: public configs are shared with
strangers. The operator can see your traffic and your IP. Use them when you
have nothing else; prefer your own Cloudflare Worker (see core/cf.py) for
anything you care about.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import configs, util

# Sources verified to exist on GitHub (checked with the API before shipping).
# `kind` hints at what the file contains; all of them are fetched the same way.
SOURCES: List[Dict[str, str]] = [
    {
        "id": "v2rayfree",
        "name": "v2rayfree (daily)",
        "url": "https://raw.githubusercontent.com/free-nodes/v2rayfree/main/sub/list.txt",
        "kind": "mixed",
        "note": "very large daily list, mostly short-lived nodes",
    },
    {
        "id": "aggregator",
        "name": "V2RayAggregator (merged)",
        "url": "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/main/sub/sub_merge_base64.txt",
        "kind": "mixed",
        "note": "community aggregator, updates every few hours",
    },
    {
        "id": "aggregator-text",
        "name": "V2RayAggregator (plain text)",
        "url": "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/main/sub/sub_merge.txt",
        "kind": "mixed",
        "note": "same list, not base64",
    },
    {
        "id": "radikal-vless",
        "name": "Radikal / VLESS",
        "url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/protocols/vless.txt",
        "kind": "vless",
        "note": "refreshed every 15 minutes",
    },
    {
        "id": "radikal-hy2",
        "name": "Radikal / Hysteria2",
        "url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/protocols/hysteria2.txt",
        "kind": "hysteria2",
        "note": "QUIC based, good on lossy mobile networks",
    },
    {
        "id": "radikal-trojan",
        "name": "Radikal / Trojan",
        "url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/protocols/trojan.txt",
        "kind": "trojan",
        "note": "refreshed every 15 minutes",
    },
    {
        "id": "radikal-ss",
        "name": "Radikal / Shadowsocks",
        "url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/protocols/shadowsocks.txt",
        "kind": "ss",
        "note": "refreshed every 15 minutes",
    },
    {
        "id": "radikal-slipnet",
        "name": "Radikal / SlipNet (DNSTT)",
        "url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/protocols/slipnet-enc.txt",
        "kind": "dnstt",
        "note": "DNS tunnel - the only thing that worked during the Feb-2026 shutdown",
    },
    {
        "id": "nirevil-bpb-ip",
        "name": "Clean Cloudflare IPs (BPB)",
        "url": "https://raw.githubusercontent.com/NiREvil/vless/main/sub/Cf-ip-bpb.txt",
        "kind": "ip-list",
        "note": "put one of these in the client's clean-IP field when your ISP throttles CF",
    },
    {
        "id": "v2rayauto",
        "name": "v2rayAuto (Iran channels)",
        "url": "https://raw.githubusercontent.com/mshojaei77/v2rayAuto/main/telegram/popular_channels_1",
        "kind": "mixed",
        "note": "mirrors of Iranian Telegram config channels",
    },
]


def sources(kind: Optional[str] = None) -> List[Dict[str, str]]:
    if not kind:
        return list(SOURCES)
    return [s for s in SOURCES if s["kind"] == kind or kind == "all"]


def fetch(url: str, timeout: int = 30) -> Tuple[List[Dict[str, Any]], str]:
    """Download one subscription and parse it. Returns (configs, error)."""
    try:
        status, _h, body = util.http_request(url, timeout=timeout, headers={"User-Agent": "v2rayNG/1.8"}, retries=1)
        if status >= 400:
            return [], f"HTTP {status}"
        text = body.decode("utf-8", "replace")
        cfgs = configs.parse_any(text)
        if not cfgs:
            return [], "no configs recognised in the response"
        return cfgs, ""
    except Exception as exc:
        return [], str(exc)


def collect(
    source_ids: Optional[List[str]] = None,
    extra_urls: Optional[List[str]] = None,
    limit_per_source: int = 60,
    timeout: int = 30,
    progress: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Fetch several sources and merge them (de-duplicated)."""
    wanted = sources()
    if source_ids:
        wanted = [s for s in wanted if s["id"] in source_ids]
    report: List[Dict[str, str]] = []
    bucket: List[Dict[str, Any]] = []
    for src in wanted:
        cfgs, error = fetch(src["url"], timeout=timeout)
        if error:
            report.append({"id": src["id"], "name": src["name"], "count": 0, "error": error})
            if progress:
                util.warn(f"{src['name']}: {error}")
            continue
        cfgs = cfgs[:limit_per_source]
        bucket.extend(cfgs)
        report.append({"id": src["id"], "name": src["name"], "count": len(cfgs), "error": ""})
        if progress:
            util.ok(f"{src['name']}: {len(cfgs)} configs")
    for url in extra_urls or []:
        cfgs, error = fetch(url, timeout=timeout)
        if error:
            report.append({"id": url, "name": url[:48], "count": 0, "error": error})
        else:
            bucket.extend(cfgs[:limit_per_source])
            report.append({"id": url, "name": url[:48], "count": len(cfgs), "error": ""})
    return configs.merge_configs(bucket), report


def rename(cfgs: Iterable[Dict[str, Any]], prefix: str = "OpenPath") -> List[Dict[str, Any]]:
    out = []
    for i, c in enumerate(cfgs, 1):
        c = configs.normalize(c)
        c["name"] = f"{prefix}-{i}-{c['proto']}"
        out.append(c)
    return out


def save(cfgs: List[Dict[str, Any]]) -> None:
    util.set_state(subscriptions=[configs.normalize(c) for c in cfgs])


def load() -> List[Dict[str, Any]]:
    return [configs.normalize(c) for c in (util.get_state().get("subscriptions") or []) if c.get("server")]


def export(cfgs: List[Dict[str, Any]], fmt: str = "b64", mode: str = "global") -> str:
    fmt = (fmt or "b64").lower()
    if fmt in ("text", "v2ray", "plain"):
        return configs.subscription(cfgs) + "\n"
    if fmt in ("b64", "base64", "sub"):
        return base64.b64encode(configs.subscription(cfgs).encode()).decode() + "\n"
    if fmt in ("clash", "yaml", "mihomo"):
        return configs.clash_config(cfgs, mode=mode)
    if fmt in ("singbox", "sing-box", "json", "sfa"):
        return json.dumps(configs.singbox_config(cfgs, mode=mode), indent=2, ensure_ascii=False)
    if fmt in ("xray",):
        return json.dumps(configs.xray_config(cfgs, mode=mode), indent=2, ensure_ascii=False)
    raise ValueError(f"unknown format: {fmt}")


# --------------------------------------------------------------------------- #
# local subscription server
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    cfgs: List[Dict[str, Any]] = []
    mode: str = "global"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        fmt = (query.get("format") or ["b64"])[0]
        mode = (query.get("mode") or [_Handler.mode])[0]
        try:
            body = export(_Handler.cfgs, fmt, mode)
        except Exception as exc:
            body = f"error: {exc}\n"
            return self._send(body.encode(), "text/plain; charset=utf-8")
        ctype = "text/plain; charset=utf-8"
        if fmt in ("clash", "yaml", "mihomo"):
            ctype = "text/yaml; charset=utf-8"
        elif fmt in ("singbox", "sing-box", "json", "sfa", "xray"):
            ctype = "application/json; charset=utf-8"
        self._send(body.encode(), ctype)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(b"", "text/plain")


def serve(cfgs: List[Dict[str, Any]], host: str = "0.0.0.0", port: int = 0, mode: str = "global") -> Tuple[ThreadingHTTPServer, int]:
    """Serve the merged list so a client can import it as a subscription URL."""
    _Handler.cfgs = [configs.normalize(c) for c in cfgs]
    _Handler.mode = mode
    port = port or util.free_port(8788, host=host)
    httpd = ThreadingHTTPServer((host, port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port
