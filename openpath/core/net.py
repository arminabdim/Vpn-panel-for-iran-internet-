"""
Latency / reachability tests.

Two different things are measured, because they answer different questions:

    tcping   TCP connect time to server:port  - tells you whether the *address*
             is reachable and how far away the edge is. Works from anywhere.
    rtt      a real HTTP request sent THROUGH a proxy (the local desync proxy,
             the Apps Script relay proxy, or a config tested with a local
             sing-box/xray). Tells you whether it actually carries traffic.

Both are best-effort: unreachable != blocked, it may just be a bad node.
"""

from __future__ import annotations

import concurrent.futures
import socket
import ssl
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import configs, util

TEST_URLS = [
    "https://www.gstatic.com/generate_204",
    "https://cp.cloudflare.com/generate_204",
    "https://1.1.1.1/cdn-cgi/trace",
]


def tcping(host: str, port: int, timeout: float = 4.0) -> Optional[float]:
    return util.tcp_ping(host, port, timeout)


def probe_tls(host: str, port: int = 443, sni: Optional[str] = None, timeout: float = 5.0) -> Dict[str, Any]:
    """Does a TLS handshake, and reports the certificate CN if it worked."""
    start = time.time()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=sni or host) as tls:
                cert = tls.getpeercert(binary_form=False) or {}
                version = tls.version()
                return {"ok": True, "ms": (time.time() - start) * 1000, "tls": version, "sni": sni or host}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:80], "ms": None}


def through_proxy(proxy: str, url: str = TEST_URLS[0], timeout: float = 8.0) -> Optional[float]:
    """Full request through an HTTP proxy (e.g. the local desync/gas proxy)."""
    return util.http_ping(url, timeout=timeout, proxy=proxy)


def test_config(cfg: Dict[str, Any], timeout: float = 4.0, probe_url: Optional[str] = None) -> Dict[str, Any]:
    c = configs.normalize(cfg)
    result = {"name": c["name"], "proto": c["proto"], "server": c["server"], "port": c["port"]}
    ms = tcping(c["server"], c["port"], timeout)
    result["tcping"] = round(ms, 1) if ms else None
    if ms and c["security"] in ("tls", "reality"):
        tls = probe_tls(c["server"], c["port"], c["sni"] or c["server"], timeout + 1)
        result["tls"] = tls.get("tls") if tls.get("ok") else None
        result["tls_error"] = tls.get("error") if not tls.get("ok") else None
    return result


def test_many(cfgs: List[Dict[str, Any]], workers: int = 24, timeout: float = 4.0) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(test_config, c, timeout): c for c in cfgs}
        for fut in concurrent.futures.as_completed(futures):
            try:
                out.append(fut.result())
            except Exception:
                continue
    out.sort(key=lambda r: (r.get("tcping") is None, r.get("tcping") or 99999))
    return out


def speed_test(proxy: Optional[str] = None, size: int = 1_000_000, timeout: int = 25) -> Dict[str, Any]:
    """Rough download throughput through a local HTTP proxy (or direct)."""
    url = f"https://speed.cloudflare.com/__down?bytes={size}"
    start = time.time()
    try:
        status, _h, body = util.http_request(url, timeout=timeout, proxy=proxy, retries=0)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    elapsed = max(0.001, time.time() - start)
    if status >= 400 or not body:
        return {"ok": False, "error": f"HTTP {status}"}
    return {"ok": True, "bytes": len(body), "seconds": round(elapsed, 2), "mbps": round(len(body) * 8 / elapsed / 1_000_000, 2)}


def format_table(results: List[Dict[str, Any]]) -> str:
    head = f"{'#':>3}  {'node':<34} {'proto':<10} {'tcping':>9}  {'tls':<8} note"
    lines = [head, "-" * max(len(head), 78)]
    for i, r in enumerate(results, 1):
        ping = f"{r['tcping']:.0f} ms" if r.get("tcping") else "  --"
        tls = r.get("tls") or (r.get("tls_error") or "")[:8]
        name = (r.get("name") or "")[:34]
        lines.append(f"{i:>3}  {name:<34} {r.get('proto',''):<10} {ping:>9}  {tls:<8}")
    return "\n".join(lines)
