"""
OpenPath - canonical config model and converters.

One internal representation (a plain dict) is converted to / from every format
that Android / desktop clients understand:

    * vless://, trojan://, vmess://, ss://, hysteria2://, tuic://, wireguard://
    * sing-box outbound / full config JSON  (MahsaNG, Hiddify, NekoBox, sing-box)
    * Clash / Mihomo  YAML                  (Clash Meta, Clash Verge)
    * Xray-core JSON                        (v2rayNG, v2rayN)
    * base64 subscription list              (what every client imports)

Only the standard library is used, so it runs on a phone inside Termux with a
bare `python` and no pip install.

The same logic is mirrored in `panel/assets/js/engine.js` for the web panel.
Keep the two in sync when you change a format.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "SCHEMES",
    "DEFAULTS",
    "new_uuid",
    "rand_password",
    "normalize",
    "to_uri",
    "parse_uri",
    "parse_any",
    "to_singbox_outbound",
    "to_clash_proxy",
    "to_xray_outbound",
    "singbox_config",
    "clash_config",
    "xray_config",
    "subscription",
    "parse_subscription",
    "wireguard_conf",
    "merge_configs",
    "fingerprint_name",
]

SCHEMES = (
    "vless",
    "vmess",
    "trojan",
    "ss",
    "ssr",
    "hysteria",
    "hysteria2",
    "hy2",
    "tuic",
    "wireguard",
    "socks",
    "http",
    "https",
    "naive",
    "anytls",
    "shadowtls",
)

# Every field the engine knows about. `None` means "not set".
DEFAULTS: Dict[str, Any] = {
    # identity
    "name": "OpenPath",
    "proto": "vless",
    "server": "",
    "port": 443,
    "uuid": "",  # vless / vmess / tuic id
    "password": "",  # trojan / ss / hysteria2 / tuic
    "method": "none",  # ss encryption, vmess security
    "aid": 0,  # vmess alterId
    # transport
    "network": "ws",  # tcp | ws | grpc | xhttp | httpupgrade | h2 | quic | kcp
    "security": "tls",  # none | tls | reality
    "sni": "",
    "host": "",
    "path": "/",
    "alpn": "",
    "fp": "chrome",  # tls fingerprint (uTLS)
    "flow": "",  # xtls-rprx-vision
    "serviceName": "",  # grpc service name
    "mode": "auto",  # xhttp mode: auto|stream-one|stream-up|packet-up
    "headerType": "none",
    # reality
    "pbk": "",
    "sid": "",
    "spx": "",
    # hysteria2 / tuic
    "obfs": "",  # salamander
    "obfs_password": "",
    "up": "",
    "down": "",
    "congestion": "bbr",
    "udp_relay_mode": "native",
    "reduce_rtt": False,
    # wireguard
    "wg_private_key": "",
    "wg_public_key": "",  # peer public key
    "wg_preshared_key": "",
    "wg_local_address": "172.16.0.2/32",
    "wg_mtu": 1280,
    "wg_reserved": "",  # comma separated decimal bytes (WARP)
    # misc
    "insecure": False,
    "udp": True,
    "sni_list": None,
    "packet_encoding": "xudp",
    # client-side anti-DPI (sing-box 1.10+ / Xray 1.8+)
    "fragment": False,
    "fragment_size": "10-30",
    "fragment_sleep": "10-20",
    "record_fragment": False,
    "tag": "",
    "extra": {},  # free-form, copied into some outputs
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def new_uuid() -> str:
    """RFC-4122-ish random UUID (v4)."""
    b = bytearray(secrets.token_bytes(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def rand_password(n: int = 16) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _clean_int(v: Any, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _b64e(data: bytes, urlsafe: bool = False, pad: bool = True) -> str:
    fn = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    out = fn(data).decode()
    return out if pad else out.rstrip("=")


def _b64d(text: str, urlsafe: bool = False) -> bytes:
    text = text.strip()
    pad = "=" * (-len(text) % 4)
    fn = base64.urlsafe_b64decode if urlsafe else base64.b64decode
    try:
        return fn(text + pad)
    except Exception:
        # last resort: try the other alphabet / no padding
        try:
            return base64.b64decode(text + pad)
        except Exception:
            return b""


def _is_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value or ""))


def _coerce_uuid(value: str) -> str:
    """Accept a 32-hex string or a UUID with dashes; always return dashed form."""
    v = (value or "").strip()
    if _is_uuid(v):
        return v
    if re.fullmatch(r"[0-9a-fA-F]{32}", v):
        h = v.lower()
        return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    return ""


def normalize(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fill defaults, coerce types, auto-derive missing values."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg or {}).items() if v is not None})

    out["proto"] = (out["proto"] or "vless").lower().strip()
    if out["proto"] == "hy2":
        out["proto"] = "hysteria2"
    out["server"] = (out["server"] or "").strip()
    out["port"] = _clean_int(out["port"], 443)
    if not out["port"]:
        out["port"] = 443

    out["uuid"] = _coerce_uuid(out["uuid"])
    if out["proto"] in ("vless", "vmess", "tuic") and not out["uuid"]:
        out["uuid"] = new_uuid()

    if out["proto"] in ("trojan", "shadowsocks", "ss", "hysteria2", "hysteria") and not out["password"]:
        out["password"] = rand_password()
    if out["proto"] == "ss":
        out["proto"] = "ss"

    # transport sanity
    net = (out["network"] or "ws").lower()
    if out["proto"] in ("hysteria2", "hysteria", "tuic", "wireguard"):
        net = "raw" if out["proto"] in ("hysteria2", "hysteria") else net
    out["network"] = net

    sec = (out["security"] or "tls").lower()
    if sec == "none" and out["proto"] in ("vless", "trojan", "vmess") and net in ("ws", "grpc", "xhttp"):
        pass  # allowed: plain ws behind a TLS-terminating CDN
    out["security"] = sec

    if not out["sni"]:
        out["sni"] = out["host"] or ("" if _is_ip(out["server"]) else out["server"])
    if not out["host"] and net in ("ws", "xhttp", "httpupgrade", "h2"):
        out["host"] = out["server"]
    if not out["path"] and net in ("ws", "xhttp", "httpupgrade", "h2"):
        out["path"] = "/"
    if out["path"] and not out["path"].startswith("/") and net in ("ws", "xhttp", "httpupgrade", "h2"):
        out["path"] = "/" + out["path"]

    out["name"] = str(out["name"] or "OpenPath")[:64]
    if not out["tag"]:
        out["tag"] = out["name"]
    out["insecure"] = bool(out["insecure"])
    out["udp"] = bool(out["udp"])
    return out


def _is_ip(value: str) -> bool:
    v = value or ""
    if ":" in v:
        return bool(re.fullmatch(r"[0-9a-fA-F:]+", v))
    return bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", v))


def _esc(value: str) -> str:
    return urllib.parse.quote(value or "", safe="")


def _unesc(value: str) -> str:
    return urllib.parse.unquote(value or "")


def _display_name(cfg: Dict[str, Any]) -> str:
    """Human friendly, terminal-safe (ASCII only) node name."""
    name = (cfg.get("name") or "").strip()
    return name or f"{cfg.get('proto')}-{cfg.get('server')}"


def fingerprint_name(cfg: Dict[str, Any]) -> str:
    return cfg.get("fp") or "chrome"


# --------------------------------------------------------------------------- #
# URI builders
# --------------------------------------------------------------------------- #
def _vless_uri(c: Dict[str, Any]) -> str:
    q: Dict[str, str] = {
        "encryption": "none",
        "security": c["security"],
        "type": c["network"],
    }
    if c["network"] != "tcp":
        if c["host"]:
            q["host"] = c["host"]
        if c["path"]:
            q["path"] = c["path"]
    if c["security"] in ("tls", "reality"):
        if c["sni"]:
            q["sni"] = c["sni"]
        if c["fp"]:
            q["fp"] = c["fp"]
        if c["alpn"]:
            q["alpn"] = c["alpn"]
    if c["security"] == "reality":
        q["pbk"] = c["pbk"]
        q["sid"] = c["sid"]
        if c["spx"]:
            q["spx"] = c["spx"]
    if c["flow"]:
        q["flow"] = c["flow"]
    if c["network"] == "grpc" and c["serviceName"]:
        q["serviceName"] = c["serviceName"]
    if c["network"] == "xhttp":
        q["mode"] = c["mode"] or "auto"
    if c["network"] == "ws" and c["packet_encoding"]:
        q["packetEncoding"] = c["packet_encoding"]
    q["headerType"] = c["headerType"] or "none"
    user = f"{c['uuid']}@{c['server']}:{c['port']}"
    return "vless://" + user + "?" + urllib.parse.urlencode(q) + "#" + urllib.parse.quote(_display_name(c), safe="")


def _trojan_uri(c: Dict[str, Any]) -> str:
    q: Dict[str, str] = {"security": c["security"] or "tls", "type": c["network"]}
    if c["network"] not in ("tcp", "raw"):
        if c["host"]:
            q["host"] = c["host"]
        if c["path"]:
            q["path"] = c["path"]
    if c["sni"]:
        q["sni"] = c["sni"]
    if c["alpn"]:
        q["alpn"] = c["alpn"]
    if c["fp"]:
        q["fp"] = c["fp"]
    if c["network"] == "grpc" and c["serviceName"]:
        q["serviceName"] = c["serviceName"]
    user = f"{urllib.parse.quote(c['password'], safe='')}@{c['server']}:{c['port']}"
    return "trojan://" + user + "?" + urllib.parse.urlencode(q) + "#" + urllib.parse.quote(_display_name(c), safe="")


def _vmess_uri(c: Dict[str, Any]) -> str:
    obj = {
        "v": "2",
        "ps": _display_name(c),
        "add": c["server"],
        "port": str(c["port"]),
        "id": c["uuid"],
        "aid": str(c.get("aid", 0)),
        "scy": c.get("method") or "none",
        "net": c["network"],
        "type": c.get("headerType") or "none",
        "host": c.get("host", ""),
        "path": c.get("path", ""),
        "tls": "tls" if c["security"] in ("tls", "reality") else "",
        "sni": c.get("sni", ""),
        "alpn": c.get("alpn", ""),
        "fp": c.get("fp", ""),
    }
    if c["network"] == "grpc":
        obj["path"] = c.get("serviceName") or c.get("path") or ""
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
    return "vmess://" + _b64e(raw)


def _ss_uri(c: Dict[str, Any]) -> str:
    method = c.get("method") or "chacha20-ietf-poly1305"
    userinfo = _b64e(f"{method}:{c['password']}".encode(), pad=False)
    plug = ""
    if c.get("obfs") and c["obfs"] not in ("plain", "none", ""):
        opts = ""
        if c.get("host"):
            opts = f"obfs-host={c['host']}"
        plug = f"?plugin={urllib.parse.quote(c['obfs'])}{(';' + urllib.parse.quote(opts)) if opts else ''}"
    return f"ss://{userinfo}@{c['server']}:{c['port']}{plug}#" + urllib.parse.quote(_display_name(c), safe="")


def _hy2_uri(c: Dict[str, Any]) -> str:
    q: Dict[str, str] = {}
    if c.get("sni"):
        q["sni"] = c["sni"]
    if c.get("obfs"):
        q["obfs"] = c["obfs"]
        if c.get("obfs_password"):
            q["obfs-password"] = c["obfs_password"]
    if c.get("insecure"):
        q["insecure"] = "1"
    if c.get("up"):
        q["up"] = c["up"]
    if c.get("down"):
        q["down"] = c["down"]
    if c.get("alpn"):
        q["alpn"] = c["alpn"]
    port_part = f":{c['port']}" if c["port"] else ""
    base = f"hysteria2://{urllib.parse.quote(c['password'], safe='')}@{c['server']}{port_part}"
    uri = base + (("?" + urllib.parse.urlencode(q)) if q else "/")
    return uri + "#" + urllib.parse.quote(_display_name(c), safe="")


def _tuic_uri(c: Dict[str, Any]) -> str:
    q: Dict[str, str] = {}
    if c.get("sni"):
        q["sni"] = c["sni"]
    if c.get("alpn"):
        q["alpn"] = c["alpn"]
    if c.get("congestion"):
        q["congestion_control"] = c["congestion"]
    if c.get("udp_relay_mode"):
        q["udp_relay_mode"] = c["udp_relay_mode"]
    if c.get("insecure"):
        q["allow_insecure"] = "1"
    if c.get("reduce_rtt"):
        q["reduce_rtt"] = "1"
    user = f"{c['uuid']}:{urllib.parse.quote(c['password'], safe='')}"
    return (
        f"tuic://{user}@{c['server']}:{c['port']}"
        + ("?" + urllib.parse.urlencode(q) if q else "")
        + "#" + urllib.parse.quote(_display_name(c), safe="")
    )


def _wireguard_uri(c: Dict[str, Any]) -> str:
    """Unofficial but widely understood `wireguard://` share link (sing-box style)."""
    q: Dict[str, str] = {
        "address": c.get("wg_local_address") or "172.16.0.2/32",
        "publickey": c.get("wg_public_key") or "",
        "privatekey": c.get("wg_private_key") or "",
    }
    if c.get("wg_preshared_key"):
        q["presharedkey"] = c["wg_preshared_key"]
    if c.get("wg_mtu"):
        q["mtu"] = str(c["wg_mtu"])
    if c.get("wg_reserved"):
        q["reserved"] = c["wg_reserved"]
    if c.get("udp") is False:
        q["udp"] = "0"
    return "wireguard://" + f"{c['server']}:{c['port']}" + "?" + urllib.parse.urlencode(q) + "#" + urllib.parse.quote(
        _display_name(c), safe=""
    )


def to_uri(cfg: Dict[str, Any]) -> str:
    c = normalize(cfg)
    p = c["proto"]
    if p == "vless":
        return _vless_uri(c)
    if p == "trojan":
        return _trojan_uri(c)
    if p == "vmess":
        return _vmess_uri(c)
    if p in ("ss", "shadowsocks"):
        c["proto"] = "ss"
        return _ss_uri(c)
    if p in ("hysteria2", "hysteria", "hy2"):
        c["proto"] = "hysteria2"
        return _hy2_uri(c)
    if p == "tuic":
        return _tuic_uri(c)
    if p == "wireguard":
        return _wireguard_uri(c)
    if p in ("socks", "http", "https"):
        user = ""
        if c.get("uuid") or c.get("password"):
            user = urllib.parse.quote(f"{c.get('uuid') or ''}:{c.get('password') or ''}", safe="") + "@"
        return f"{p}://{user}{c['server']}:{c['port']}#" + urllib.parse.quote(_display_name(c), safe="")
    raise ValueError(f"unsupported protocol for URI export: {p}")


# --------------------------------------------------------------------------- #
# URI parsers
# --------------------------------------------------------------------------- #
def _q(uri: str) -> Dict[str, str]:
    if "?" not in uri:
        return {}
    raw = uri.split("?", 1)[1]
    raw = raw.split("#", 1)[0]
    return {k: v for k, v in urllib.parse.parse_qsl(raw, keep_blank_values=True)}


def _frag(uri: str) -> str:
    if "#" not in uri:
        return ""
    return _unesc(uri.split("#", 1)[1])


def _hostport(netloc: str) -> tuple:
    netloc = netloc.strip()
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    if netloc.startswith("["):  # ipv6
        host, _, port = netloc.partition("]")
        return host + "]", (port.lstrip(":") or "443")
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        return host, (port or "443")
    return netloc, "443"


def _parse_vless(uri: str) -> Dict[str, Any]:
    body = uri[len("vless://"):]
    userinfo, _, rest = body.rpartition("@")
    host, port = _hostport(rest.split("?", 1)[0].split("#", 1)[0])
    q = _q(uri)
    return {
        "proto": "vless",
        "name": _frag(uri) or "vless",
        "uuid": _coerce_uuid(userinfo) or userinfo,
        "server": host,
        "port": _clean_int(port, 443),
        "network": q.get("type", "tcp"),
        "security": q.get("security", "none"),
        "sni": q.get("sni", ""),
        "host": q.get("host", ""),
        "path": q.get("path", ""),
        "alpn": q.get("alpn", ""),
        "fp": q.get("fp", "chrome"),
        "flow": q.get("flow", ""),
        "pbk": q.get("pbk", ""),
        "sid": q.get("sid", ""),
        "spx": q.get("spx", ""),
        "serviceName": q.get("serviceName", ""),
        "mode": q.get("mode", "auto"),
        "headerType": q.get("headerType", "none"),
        "packet_encoding": q.get("packetEncoding", "xudp"),
    }


def _parse_trojan(uri: str) -> Dict[str, Any]:
    body = uri[len("trojan://"):]
    userinfo, _, rest = body.rpartition("@")
    host, port = _hostport(rest.split("?", 1)[0].split("#", 1)[0])
    q = _q(uri)
    return {
        "proto": "trojan",
        "name": _frag(uri) or "trojan",
        "password": _unesc(userinfo),
        "server": host,
        "port": _clean_int(port, 443),
        "network": q.get("type", "tcp"),
        "security": q.get("security", "tls"),
        "sni": q.get("sni", ""),
        "host": q.get("host", ""),
        "path": q.get("path", ""),
        "alpn": q.get("alpn", ""),
        "fp": q.get("fp", "chrome"),
        "serviceName": q.get("serviceName", ""),
    }


def _parse_vmess(uri: str) -> Dict[str, Any]:
    payload = uri[len("vmess://"):]
    obj = None
    decoded = _b64d(payload)
    if decoded:
        try:
            obj = json.loads(decoded.decode("utf-8", "replace"))
        except Exception:
            obj = None
    if obj is None:
        # some generators emit plain (url-encoded) JSON
        try:
            obj = json.loads(_unesc(payload))
        except Exception:
            return {}
    return {
        "proto": "vmess",
        "name": obj.get("ps") or "vmess",
        "server": obj.get("add", ""),
        "port": _clean_int(obj.get("port"), 443),
        "uuid": _coerce_uuid(obj.get("id", "")),
        "aid": _clean_int(obj.get("aid"), 0),
        "method": obj.get("scy") or "none",
        "network": obj.get("net") or "tcp",
        "host": obj.get("host", ""),
        "path": obj.get("path", ""),
        "security": "tls" if str(obj.get("tls", "")).lower() == "tls" else "none",
        "sni": obj.get("sni", ""),
        "alpn": obj.get("alpn", ""),
        "fp": obj.get("fp", ""),
        "headerType": obj.get("type") or "none",
        "serviceName": obj.get("path", "") if obj.get("net") == "grpc" else "",
    }


def _parse_ss(uri: str) -> Dict[str, Any]:
    payload = uri[len("ss://"):]
    payload = payload.split("#", 1)[0]
    plugin = ""
    if "?plugin=" in payload or "&plugin=" in payload:
        marker = "?plugin=" if "?plugin=" in payload else "&plugin="
        payload, _, plug = payload.partition(marker)
        plugin = _unesc(plug)
    host, port, method, password = "", 443, "chacha20-ietf-poly1305", ""
    if "@" in payload:
        userinfo, _, hp = payload.rpartition("@")
        host, port = _hostport(hp)
        dec = _b64d(_unesc(userinfo)).decode("utf-8", "replace")
        if ":" in dec:
            method, _, password = dec.partition(":")
        else:
            method, password = "chacha20-ietf-poly1305", dec
    else:
        dec = _b64d(payload).decode("utf-8", "replace")
        if "@" in dec:
            creds, _, hp = dec.rpartition("@")
            host, port = _hostport(hp)
            method, _, password = creds.partition(":")
        else:
            return {}
    obfs = ""
    obfs_host = ""
    if plugin:
        name, _, opts = plugin.partition(";")
        obfs = name
        for pair in opts.split(";"):
            k, _, v = pair.partition("=")
            if k in ("obfs-host", "host"):
                obfs_host = v
    return {
        "proto": "ss",
        "name": _frag(uri) or "ss",
        "server": host,
        "port": _clean_int(port, 443),
        "method": method,
        "password": password,
        "obfs": obfs,
        "host": obfs_host,
        "network": "tcp",
        "security": "none",
    }


def _parse_hy2(uri: str) -> Dict[str, Any]:
    prefix = "hysteria2://" if uri.startswith("hysteria2://") else ("hy2://" if uri.startswith("hy2://") else "hysteria://")
    body = uri[len(prefix):]
    userinfo, _, rest = body.rpartition("@")
    rest = rest.split("#", 1)[0]
    host, port = _hostport(rest.split("?", 1)[0])
    q = _q(uri)
    return {
        "proto": "hysteria2",
        "name": _frag(uri) or "hysteria2",
        "password": _unesc(userinfo),
        "server": host,
        "port": _clean_int(port, 443),
        "sni": q.get("sni", ""),
        "obfs": q.get("obfs", ""),
        "obfs_password": q.get("obfs-password", ""),
        "insecure": q.get("insecure") in ("1", "true"),
        "up": q.get("up", ""),
        "down": q.get("down", ""),
        "alpn": q.get("alpn", ""),
        "network": "raw",
        "security": "tls",
    }


def _parse_tuic(uri: str) -> Dict[str, Any]:
    body = uri[len("tuic://"):]
    userinfo, _, rest = body.rpartition("@")
    host, port = _hostport(rest.split("?", 1)[0].split("#", 1)[0])
    q = _q(uri)
    uuid, _, password = userinfo.partition(":")
    return {
        "proto": "tuic",
        "name": _frag(uri) or "tuic",
        "uuid": _coerce_uuid(uuid) or uuid,
        "password": _unesc(password),
        "server": host,
        "port": _clean_int(port, 443),
        "sni": q.get("sni", ""),
        "alpn": q.get("alpn", ""),
        "congestion": q.get("congestion_control", "bbr"),
        "udp_relay_mode": q.get("udp_relay_mode", "native"),
        "insecure": q.get("allow_insecure") in ("1", "true"),
        "reduce_rtt": q.get("reduce_rtt") in ("1", "true"),
        "network": "raw",
        "security": "tls",
    }


def _parse_wireguard(uri: str) -> Dict[str, Any]:
    body = uri[len("wireguard://"):]
    netloc = body.split("?", 1)[0]
    host, port = _hostport(netloc)
    q = _q(uri)
    return {
        "proto": "wireguard",
        "name": _frag(uri) or "wireguard",
        "server": host,
        "port": _clean_int(port, 51820),
        "wg_public_key": q.get("publickey", ""),
        "wg_private_key": q.get("privatekey", ""),
        "wg_preshared_key": q.get("presharedkey", ""),
        "wg_local_address": q.get("address", "172.16.0.2/32"),
        "wg_mtu": _clean_int(q.get("mtu"), 1280),
        "wg_reserved": q.get("reserved", ""),
        "network": "raw",
        "security": "none",
    }


def _parse_socksish(uri: str, proto: str) -> Dict[str, Any]:
    body = uri.split("://", 1)[1]
    userinfo = ""
    if "@" in body:
        userinfo, _, body = body.rpartition("@")
    host, port = _hostport(body.split("#", 1)[0])
    user, _, pwd = _unesc(userinfo).partition(":")
    return {
        "proto": proto,
        "name": _frag(uri) or proto,
        "server": host,
        "port": _clean_int(port, 1080),
        "uuid": user,
        "password": pwd,
        "network": "tcp",
        "security": "none",
    }


_PARSERS = {
    "vless": _parse_vless,
    "trojan": _parse_trojan,
    "vmess": _parse_vmess,
    "ss": _parse_ss,
    "shadowsocks": _parse_ss,
    "hysteria2": _parse_hy2,
    "hysteria": _parse_hy2,
    "hy2": _parse_hy2,
    "tuic": _parse_tuic,
    "wireguard": _parse_wireguard,
}


def parse_uri(uri: str) -> Optional[Dict[str, Any]]:
    """Parse one share link into the canonical dict. Returns None on failure."""
    if not uri or "://" not in uri:
        return None
    uri = uri.strip()
    scheme = uri.split("://", 1)[0].lower()
    try:
        if scheme in _PARSERS:
            cfg = _PARSERS[scheme](uri)
        elif scheme in ("socks", "socks5", "http", "https"):
            cfg = _parse_socksish(uri, "socks" if scheme.startswith("socks") else scheme)
        else:
            return None
    except Exception:
        return None
    if not cfg or not cfg.get("server"):
        return None
    cfg["_raw"] = uri
    return normalize(cfg)


def parse_any(text: str) -> List[Dict[str, Any]]:
    """Parse a blob that may contain links, base64 and/or JSON."""
    out: List[Dict[str, Any]] = []
    text = (text or "").strip()
    # JSON (sing-box / clash export) first
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            obj = None
        if isinstance(obj, dict) and "outbounds" in obj:
            for ob in obj["outbounds"]:
                if ob.get("type") in ("selector", "urltest", "direct", "block", "dns"):
                    continue
                cfg = _from_singbox(ob)
                if cfg:
                    out.append(cfg)
            if out:
                return out
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line:
            continue
        cfg = parse_uri(line)
        if cfg:
            out.append(cfg)
            continue
        # maybe the whole blob is base64
        decoded = _b64d(line).decode("utf-8", "replace")
        if decoded and decoded != line:
            for sub in re.split(r"[\r\n]+", decoded):
                cfg = parse_uri(sub.strip())
                if cfg:
                    out.append(cfg)
    return out


def _from_singbox(ob: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = ob.get("type")
    base = {"name": ob.get("tag", t), "server": ob.get("server", ""), "port": ob.get("server_port", 0)}
    try:
        if t == "vless":
            tr = ob.get("transport", {}) or {}
            tls = ob.get("tls", {}) or {}
            base.update(
                {
                    "proto": "vless",
                    "uuid": ob.get("uuid", ""),
                    "network": tr.get("type", "tcp"),
                    "path": tr.get("path", ""),
                    "host": (tr.get("headers") or {}).get("Host", ""),
                    "serviceName": tr.get("service_name", ""),
                    "security": "reality" if tls.get("reality", {}).get("enabled") else ("tls" if tls.get("enabled") else "none"),
                    "sni": tls.get("server_name", ""),
                    "alpn": ",".join(tls.get("alpn", []) or []),
                    "fp": (tls.get("utls") or {}).get("fingerprint", ""),
                    "flow": ob.get("flow", ""),
                    "pbk": (tls.get("reality") or {}).get("public_key", ""),
                    "sid": (tls.get("reality") or {}).get("short_id", ""),
                    "packet_encoding": ob.get("packet_encoding", "xudp"),
                }
            )
        elif t == "trojan":
            tr = ob.get("transport", {}) or {}
            tls = ob.get("tls", {}) or {}
            base.update(
                {
                    "proto": "trojan",
                    "password": ob.get("password", ""),
                    "network": tr.get("type", "tcp"),
                    "path": tr.get("path", ""),
                    "host": (tr.get("headers") or {}).get("Host", ""),
                    "security": "tls" if tls.get("enabled") else "none",
                    "sni": tls.get("server_name", ""),
                }
            )
        elif t == "vmess":
            tr = ob.get("transport", {}) or {}
            tls = ob.get("tls", {}) or {}
            base.update(
                {
                    "proto": "vmess",
                    "uuid": ob.get("uuid", ""),
                    "aid": ob.get("alter_id", 0),
                    "method": ob.get("security", "none"),
                    "network": tr.get("type", "tcp"),
                    "path": tr.get("path", ""),
                    "host": (tr.get("headers") or {}).get("Host", ""),
                    "security": "tls" if tls.get("enabled") else "none",
                    "sni": tls.get("server_name", ""),
                }
            )
        elif t == "shadowsocks":
            base.update(
                {"proto": "ss", "method": ob.get("method", ""), "password": ob.get("password", ""), "network": "tcp", "security": "none"}
            )
        elif t == "hysteria2":
            obfs = ob.get("obfs", {}) or {}
            tls = ob.get("tls", {}) or {}
            base.update(
                {
                    "proto": "hysteria2",
                    "password": ob.get("password", ""),
                    "obfs": obfs.get("type", ""),
                    "obfs_password": obfs.get("password", ""),
                    "up": ob.get("up_mbps", "") and str(ob["up_mbps"]),
                    "down": ob.get("down_mbps", "") and str(ob["down_mbps"]),
                    "sni": tls.get("server_name", ""),
                    "insecure": bool(tls.get("insecure")),
                    "network": "raw",
                    "security": "tls",
                }
            )
        elif t == "tuic":
            tls = ob.get("tls", {}) or {}
            base.update(
                {
                    "proto": "tuic",
                    "uuid": ob.get("uuid", ""),
                    "password": ob.get("password", ""),
                    "congestion": (ob.get("congestion_control") or "bbr"),
                    "udp_relay_mode": ob.get("udp_relay_mode", "native"),
                    "sni": tls.get("server_name", ""),
                    "alpn": ",".join(tls.get("alpn", []) or []),
                    "insecure": bool(tls.get("insecure")),
                    "network": "raw",
                    "security": "tls",
                }
            )
        elif t == "wireguard":
            peers = ob.get("peers") or [{}]
            base.update(
                {
                    "proto": "wireguard",
                    "wg_private_key": ob.get("private_key", ""),
                    "wg_public_key": (peers[0] or {}).get("public_key", ""),
                    "wg_preshared_key": (peers[0] or {}).get("pre_shared_key", ""),
                    "wg_local_address": ",".join(ob.get("local_address", []) or ["172.16.0.2/32"]),
                    "wg_mtu": ob.get("mtu", 1280),
                    "wg_reserved": ",".join(str(x) for x in (peers[0] or {}).get("reserved", []) or []),
                    "network": "raw",
                    "security": "none",
                }
            )
        elif t in ("socks", "http"):
            base.update({"proto": t, "uuid": (ob.get("username") or ""), "password": ob.get("password", ""), "network": "tcp", "security": "none"})
        else:
            return None
    except Exception:
        return None
    return normalize(base)


# --------------------------------------------------------------------------- #
# sing-box
# --------------------------------------------------------------------------- #
def _tls_obj(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if c["security"] == "none":
        return None
    tls: Dict[str, Any] = {"enabled": True, "server_name": c["sni"] or None, "insecure": bool(c["insecure"])}
    if c["alpn"]:
        tls["alpn"] = [x.strip() for x in c["alpn"].split(",") if x.strip()]
    if c["fp"]:
        tls["utls"] = {"enabled": True, "fingerprint": c["fp"]}
    if c["security"] == "reality":
        tls["reality"] = {"enabled": True, "public_key": c["pbk"], "short_id": c["sid"]}
    if c.get("fragment"):
        # ClientHello fragmentation: defeats SNI based DPI without any server.
        tls["fragment"] = {"enabled": True, "size": c.get("fragment_size") or "10-30", "sleep": c.get("fragment_sleep") or "10-20"}
        tls["fragment_fallback_delay"] = "500ms"
    if c.get("record_fragment"):
        tls["record_fragment"] = True
    return {k: v for k, v in tls.items() if v is not None}


def _transport_obj(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    net = c["network"]
    if net in ("tcp", "raw", ""):
        return None
    if net == "ws":
        tr: Dict[str, Any] = {"type": "ws", "path": c["path"] or "/"}
        headers: Dict[str, str] = {}
        if c["host"]:
            headers["Host"] = c["host"]
        if headers:
            tr["headers"] = headers
        return tr
    if net == "httpupgrade":
        tr = {"type": "httpupgrade", "path": c["path"] or "/"}
        if c["host"]:
            tr["host"] = c["host"]
        return tr
    if net == "grpc":
        return {"type": "grpc", "service_name": c.get("serviceName") or c.get("path", "").lstrip("/") or "GunService"}
    if net == "xhttp":
        tr = {"type": "http", "path": c["path"] or "/"}
        if c["host"]:
            tr["host"] = [c["host"]]
        return tr
    if net == "h2":
        return {"type": "http", "path": c["path"] or "/", "host": [c["host"]] if c["host"] else None}
    if net == "quic":
        return {"type": "quic"}
    return None


def to_singbox_outbound(cfg: Dict[str, Any], tag: Optional[str] = None) -> Dict[str, Any]:
    c = normalize(cfg)
    t = tag or c["tag"] or c["name"]
    p = c["proto"]
    tls = _tls_obj(c)
    tr = _transport_obj(c)
    out: Dict[str, Any] = {"type": p, "tag": t}

    if p == "vless":
        out.update({"server": c["server"], "server_port": c["port"], "uuid": c["uuid"]})
        if c["flow"] and c["security"] != "none":
            out["flow"] = c["flow"]
        if c["packet_encoding"]:
            out["packet_encoding"] = c["packet_encoding"]
    elif p == "vmess":
        out.update(
            {
                "server": c["server"],
                "server_port": c["port"],
                "uuid": c["uuid"],
                "security": c["method"] or "none",
                "alter_id": c.get("aid", 0),
            }
        )
    elif p == "trojan":
        out.update({"server": c["server"], "server_port": c["port"], "password": c["password"]})
    elif p == "ss":
        out.update(
            {"server": c["server"], "server_port": c["port"], "method": c["method"] or "chacha20-ietf-poly1305", "password": c["password"]}
        )
    elif p == "hysteria2":
        out.update({"server": c["server"], "server_port": c["port"], "password": c["password"]})
        if c["obfs"]:
            out["obfs"] = {"type": c["obfs"], "password": c.get("obfs_password") or ""}
        if c["up"]:
            out["up_mbps"] = _clean_int(c["up"], 0) or None
        if c["down"]:
            out["down_mbps"] = _clean_int(c["down"], 0) or None
        tls = tls or {"enabled": True, "server_name": c["sni"] or c["server"], "insecure": bool(c["insecure"])}
        if c["alpn"]:
            tls["alpn"] = [x.strip() for x in c["alpn"].split(",") if x.strip()]
        out["tls"] = tls
        return {k: v for k, v in out.items() if v is not None}
    elif p == "tuic":
        out.update(
            {
                "server": c["server"],
                "server_port": c["port"],
                "uuid": c["uuid"],
                "password": c["password"],
                "congestion_control": c["congestion"] or "bbr",
                "udp_relay_mode": c["udp_relay_mode"] or "native",
                "zero_rtt_handshake": bool(c.get("reduce_rtt")),
            }
        )
        tls = tls or {"enabled": True, "server_name": c["sni"] or c["server"], "insecure": bool(c["insecure"])}
        if not tls.get("alpn"):
            tls["alpn"] = ["h3"]
        out["tls"] = tls
        return {k: v for k, v in out.items() if v is not None}
    elif p == "wireguard":
        peers = [
            {
                "server": c["server"],
                "server_port": c["port"],
                "public_key": c["wg_public_key"],
                "allowed_ips": ["0.0.0.0/0", "::/0"],
                "persistent_keepalive_interval": 25,
            }
        ]
        if c["wg_preshared_key"]:
            peers[0]["pre_shared_key"] = c["wg_preshared_key"]
        if c["wg_reserved"]:
            try:
                peers[0]["reserved"] = [int(x) for x in str(c["wg_reserved"]).split(",") if x.strip() != ""]
            except Exception:
                pass
        out.update(
            {
                "local_address": [x.strip() for x in c["wg_local_address"].split(",") if x.strip()],
                "private_key": c["wg_private_key"],
                "peers": peers,
                "mtu": c["wg_mtu"] or 1280,
            }
        )
        return {k: v for k, v in out.items() if v is not None}
    elif p in ("socks", "http"):
        out.update({"server": c["server"], "server_port": c["port"], "version": "5" if p == "socks" else "1.1"})
        if c.get("uuid") or c.get("password"):
            out["username"] = c.get("uuid") or ""
            out["password"] = c.get("password") or ""
        return out
    else:
        raise ValueError(f"sing-box export not implemented for: {p}")

    if tls:
        out["tls"] = tls
    if tr:
        out["transport"] = tr
    return out


def singbox_config(cfgs: Iterable[Dict[str, Any]], mode: str = "global", port: int = 2080) -> Dict[str, Any]:
    """Full sing-box client config (works in MahsaNG / Hiddify / NekoBox)."""
    cfgs = [normalize(c) for c in cfgs]
    tags: List[str] = []
    outbounds: List[Dict[str, Any]] = []
    for i, c in enumerate(cfgs, 1):
        tag = f"{c['proto']}-{i}"
        tags.append(tag)
        outbounds.append(to_singbox_outbound(c, tag=tag))

    outbound_section: List[Dict[str, Any]] = []
    if tags:
        outbound_section.append({"type": "selector", "tag": "select", "outbounds": ["auto"] + tags, "default": "auto"})
        outbound_section.append({"type": "urltest", "tag": "auto", "outbounds": list(tags), "url": "https://www.gstatic.com/generate_204", "interval": "5m", "tolerance": 100})
    outbound_section += outbounds
    outbound_section.append({"type": "direct", "tag": "direct"})
    outbound_section.append({"type": "block", "tag": "block"})
    outbound_section.append({"type": "dns", "tag": "dns-out"})

    if mode == "bypass-ir":
        rules = [
            {"action": "sniff"},
            {"protocol": "dns", "action": "hijack-dns"},
            {"ip_is_private": True, "outbound": "direct"},
            {"rule_set": ["geosite-category-ir"], "outbound": "direct"},
            {"geoip": ["ir"], "outbound": "direct"},
        ]
        rule_sets = [
            {
                "tag": "geosite-category-ir",
                "type": "remote",
                "format": "binary",
                "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ir.srs",
                "download_detour": "select",
            }
        ]
    else:
        rules = [
            {"action": "sniff"},
            {"protocol": "dns", "action": "hijack-dns"},
            {"ip_is_private": True, "outbound": "direct"},
        ]
        rule_sets = []

    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": [
                {"tag": "remote", "address": "https://1.1.1.1/dns-query", "detour": "select"},
                {"tag": "local", "address": "223.5.5.5", "detour": "direct"},
            ],
            "rules": [{"rule_set": ["geosite-category-ir"], "server": "local"}] if mode == "bypass-ir" else [],
            "final": "remote",
            "strategy": "prefer_ipv4",
        },
        "inbounds": [
            {"type": "tun", "tag": "tun-in", "interface_name": "tun0", "stack": "mixed", "mtu": 9000, "sniff": True,
             "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"], "auto_route": True, "strict_route": True,
             "endpoint_independent_nat": True, "platform": {"http_proxy": {"enabled": True, "server": "127.0.0.1", "server_port": port}}},
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": port, "sniff": True},
        ],
        "outbounds": outbound_section,
        "route": {"rules": rules, "rule_set": rule_sets, "final": "select", "auto_detect_interface": True},
        "experimental": {"cache_file": {"enabled": True}, "clash_api": {"external_controller": "127.0.0.1:9090", "store_selected": True}},
    }


# --------------------------------------------------------------------------- #
# Clash / Mihomo
# --------------------------------------------------------------------------- #
def to_clash_proxy(cfg: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    c = normalize(cfg)
    base: Dict[str, Any] = {"name": name or c["name"], "type": c["proto"], "server": c["server"], "port": c["port"]}
    p = c["proto"]
    if p == "vless":
        base.update({"uuid": c["uuid"], "tls": c["security"] != "none", "udp": c["udp"]})
        if c["network"] == "ws":
            base["network"] = "ws"
            base["ws-opts"] = {"path": c["path"] or "/"}
            if c["host"]:
                base["ws-opts"]["headers"] = {"Host": c["host"]}
        elif c["network"] == "grpc":
            base["network"] = "grpc"
            base["grpc-opts"] = {"grpc-service-name": c.get("serviceName") or "GunService"}
        if c["security"] == "reality":
            base["reality-opts"] = {"public-key": c["pbk"], "short-id": c["sid"]}
        if c["sni"]:
            base["servername"] = c["sni"]
        if c["fp"]:
            base["client-fingerprint"] = c["fp"]
        if c["flow"]:
            base["flow"] = c["flow"]
        if c["security"] == "none" and c["network"] not in ("ws", "grpc"):
            base["tls"] = False
    elif p == "trojan":
        base.update({"password": c["password"], "udp": c["udp"]})
        if c["network"] == "ws":
            base["network"] = "ws"
            base["ws-opts"] = {"path": c["path"] or "/"}
            if c["host"]:
                base["ws-opts"]["headers"] = {"Host": c["host"]}
        if c["sni"]:
            base["sni"] = c["sni"]
        if c["alpn"]:
            base["alpn"] = [x.strip() for x in c["alpn"].split(",") if x.strip()]
    elif p == "vmess":
        base.update({"uuid": c["uuid"], "cipher": c["method"] or "none", "alterId": c.get("aid", 0), "udp": c["udp"]})
        if c["network"] == "ws":
            base["network"] = "ws"
            base["ws-opts"] = {"path": c["path"] or "/"}
            if c["host"]:
                base["ws-opts"]["headers"] = {"Host": c["host"]}
        if c["security"] in ("tls", "reality"):
            base["tls"] = True
        if c["sni"]:
            base["servername"] = c["sni"]
    elif p == "ss":
        base.update({"cipher": c["method"] or "chacha20-ietf-poly1305", "password": c["password"], "udp": c["udp"]})
        if c["obfs"] and c["obfs"] != "plain":
            base["plugin"] = "obfs"
            base["plugin-opts"] = {"mode": c["obfs"], "host": c["host"] or "bing.com"}
    elif p == "hysteria2":
        base.update({"password": c["password"], "udp": True})
        if c["obfs"]:
            base["obfs"] = c["obfs"]
            base["obfs-password"] = c["obfs_password"]
        if c["up"]:
            base["up"] = f"{c['up']} Mbps"
        if c["down"]:
            base["down"] = f"{c['down']} Mbps"
        if c["sni"]:
            base["sni"] = c["sni"]
        if c["insecure"]:
            base["skip-cert-verify"] = True
    elif p == "tuic":
        base.update(
            {
                "uuid": c["uuid"],
                "password": c["password"],
                "congestion-controller": c["congestion"] or "bbr",
                "udp-relay-mode": c["udp_relay_mode"] or "native",
                "reduce-rtt": bool(c["reduce_rtt"]),
                "request-timeout": 8000,
                "heartbeat-interval": 5000,
            }
        )
        if c["sni"]:
            base["sni"] = c["sni"]
        if c["alpn"]:
            base["alpn"] = [x.strip() for x in c["alpn"].split(",") if x.strip()]
        else:
            base["alpn"] = ["h3"]
        if c["insecure"]:
            base["skip-cert-verify"] = True
    elif p == "wireguard":
        base.update(
            {
                "private-key": c["wg_private_key"],
                "public-key": c["wg_public_key"],
                "ip": c["wg_local_address"],
                "mtu": c["wg_mtu"] or 1280,
                "udp": True,
                "persistent-keepalive": 25,
            }
        )
        if c["wg_preshared_key"]:
            base["preshared-key"] = c["wg_preshared_key"]
        if c["wg_reserved"]:
            try:
                base["reserved"] = [int(x) for x in str(c["wg_reserved"]).split(",") if x.strip()]
            except Exception:
                pass
    elif p in ("socks", "http"):
        base["udp"] = c["udp"]
        if c.get("uuid") or c.get("password"):
            base["username"] = c.get("uuid") or ""
            base["password"] = c.get("password") or ""
    if c["insecure"] and p not in ("hysteria2", "tuic"):
        base["skip-cert-verify"] = True
    return {k: v for k, v in base.items() if v not in (None, "", [])}


def _yaml_dump(obj: Any, indent: int = 0) -> str:
    """Tiny YAML emitter (enough for Clash configs)."""
    sp = "  " * indent
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if v is None or v == [] or v == {}:
                continue
            if isinstance(v, (dict, list)):
                if not v:
                    continue
                lines.append(f"{sp}{k}:")
                lines.append(_yaml_dump(v, indent + 1))
            else:
                lines.append(f"{sp}{k}: {_yaml_scalar(v)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        lines = []
        for item in obj:
            if isinstance(item, (dict, list)):
                inner = _yaml_dump(item, indent + 1).lstrip()
                lines.append(f"{sp}- {inner}")
            else:
                lines.append(f"{sp}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{sp}{_yaml_scalar(obj)}"


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "":
        return '""'
    if re.search(r"[:#{}\[\],&*?|<>=!%@`\"']", s) or s.strip() != s or s.lower() in ("yes", "no", "on", "off", "true", "false", "null"):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def clash_config(cfgs: Iterable[Dict[str, Any]], mode: str = "global", port: int = 7890) -> str:
    cfgs = [normalize(c) for c in cfgs]
    proxies = [to_clash_proxy(c) for c in cfgs]
    names = [p["name"] for p in proxies]
    groups = [
        {"name": "PROXY", "type": "select", "proxies": ["AUTO"] + names},
        {"name": "AUTO", "type": "url-test", "proxies": names, "url": "https://www.gstatic.com/generate_204", "interval": 300, "tolerance": 50},
    ]
    if mode == "bypass-ir":
        rules = ["GEOIP,IR,DIRECT,no-resolve", "GEOSITE,category-ir,DIRECT", "MATCH,PROXY"]
    else:
        rules = ["MATCH,PROXY"]
    doc = {
        "mixed-port": port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": True,
        "dns": {"enable": True, "enhanced-mode": "fake-ip", "nameserver": ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"], "fake-ip-range": "198.18.0.1/16"},
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": rules,
    }
    return _yaml_dump(doc) + "\n"


# --------------------------------------------------------------------------- #
# Xray-core
# --------------------------------------------------------------------------- #
def to_xray_outbound(cfg: Dict[str, Any], tag: Optional[str] = None) -> Dict[str, Any]:
    c = normalize(cfg)
    t = tag or c["tag"] or c["name"]
    p = c["proto"]
    net = c["network"]
    stream: Dict[str, Any] = {"network": net}
    if net == "ws":
        stream["wsSettings"] = {"path": c["path"] or "/"}
        if c["host"]:
            stream["wsSettings"]["headers"] = {"Host": c["host"]}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": c.get("serviceName") or "GunService"}
    elif net == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": c["path"] or "/", "host": c["host"] or c["server"]}
    elif net == "xhttp":
        stream["xhttpSettings"] = {"path": c["path"] or "/", "host": c["host"] or c["server"], "mode": c["mode"] or "auto"}
    elif net == "h2":
        stream["httpSettings"] = {"path": c["path"] or "/", "host": [c["host"]] if c["host"] else []}
    elif net == "tcp" and c["headerType"] == "http":
        stream["tcpSettings"] = {"header": {"type": "http", "request": {"path": [c["path"] or "/"], "headers": {"Host": [c["host"] or c["server"]]}}}}

    if c["security"] == "tls":
        tls: Dict[str, Any] = {"serverName": c["sni"] or c["host"] or c["server"]}
        if c["alpn"]:
            tls["alpn"] = [x.strip() for x in c["alpn"].split(",") if x.strip()]
        if c["fp"]:
            tls["fingerprint"] = c["fp"]
        if c["insecure"]:
            tls["allowInsecure"] = True
        stream["security"] = "tls"
        stream["tlsSettings"] = tls
    elif c["security"] == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "serverName": c["sni"] or c["server"],
            "publicKey": c["pbk"],
            "shortId": c["sid"],
            "fingerprint": c["fp"] or "chrome",
            "spiderX": c.get("spx") or "/",
        }
    else:
        stream["security"] = "none"

    if p == "vless":
        ob = {"protocol": "vless", "settings": {"vnext": [{"address": c["server"], "port": c["port"], "users": [{"id": c["uuid"], "encryption": "none"}]}]}}
        if c["flow"]:
            ob["settings"]["vnext"][0]["users"][0]["flow"] = c["flow"]
    elif p == "vmess":
        ob = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {"address": c["server"], "port": c["port"], "users": [{"id": c["uuid"], "alterId": c.get("aid", 0), "security": c["method"] or "none"}]}
                ]
            },
        }
    elif p == "trojan":
        ob = {"protocol": "trojan", "settings": {"servers": [{"address": c["server"], "port": c["port"], "password": c["password"]}]}}
    elif p == "ss":
        ob = {
            "protocol": "shadowsocks",
            "settings": {"servers": [{"address": c["server"], "port": c["port"], "method": c["method"] or "chacha20-ietf-poly1305", "password": c["password"]}]},
        }
    elif p in ("socks", "http"):
        users = []
        if c.get("uuid") or c.get("password"):
            users = [{"user": c.get("uuid") or "", "pass": c.get("password") or ""}]
        ob = {"protocol": p, "settings": {"servers": [{"address": c["server"], "port": c["port"], "users": users}]}, "streamSettings": stream, "tag": t}
        return ob
    else:
        raise ValueError(f"Xray export not available for: {p} (use sing-box instead)")

    ob["streamSettings"] = stream
    ob["tag"] = t
    return ob


def xray_config(cfgs: Iterable[Dict[str, Any]], mode: str = "global", port: int = 10808) -> Dict[str, Any]:
    cfgs = [normalize(c) for c in cfgs]
    outbounds: List[Dict[str, Any]] = []
    usable = []
    for i, c in enumerate(cfgs, 1):
        if c["proto"] not in ("vless", "vmess", "trojan", "ss", "socks", "http"):
            continue  # Xray has no hysteria2/tuic
        tag = f"proxy-{i}"
        usable.append(tag)
        outbounds.append(to_xray_outbound(c, tag=tag))
    outbounds += [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}]
    return {
        "log": {"loglevel": "warning"},
        "dns": {"servers": ["https+local://1.1.1.1/dns-query", "localhost"]},
        "inbounds": [
            {"tag": "socks-in", "port": port, "listen": "127.0.0.1", "protocol": "socks", "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
             "settings": {"auth": "noauth", "udp": True}},
            {"tag": "http-in", "port": port + 1, "listen": "127.0.0.1", "protocol": "http", "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}},
        ],
        "outbounds": outbounds,
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}] if mode == "bypass-ir" else [], "balancers": [{"tag": "leastping", "selector": usable}]} if usable else {"domainStrategy": "IPIfNonMatch"},
    }


def xray_fragment_config(
    packets: str = "tlshello",
    length: str = "100-200",
    interval: str = "10-20",
    socks_port: int = 10808,
    http_port: int = 10809,
    ipv4_only: bool = True,
) -> Dict[str, Any]:
    """No-server DPI bypass: Xray `freedom` outbound with packet fragmentation.

    Every byte still goes out through your own ISP - there is no exit server -
    but the TLS ClientHello is split so the DPI box cannot read the SNI.
    Import as a *custom / raw JSON config* in NekoBox, v2rayN or Hiddify.
    (On Android, ByeByeDPI or the built-in `openpath dpi` proxy does the same
    thing without needing a JSON import.)
    """
    return {
        "log": {"loglevel": "warning"},
        "dns": {"servers": ["https+local://1.1.1.1/dns-query", "localhost"]},
        "inbounds": [
            {
                "tag": "socks-in",
                "port": socks_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
                "settings": {"auth": "noauth", "udp": True},
            },
            {
                "tag": "http-in",
                "port": http_port,
                "listen": "127.0.0.1",
                "protocol": "http",
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
                "settings": {"allowTransparent": True},
            },
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "tag": "direct",
                "settings": {
                    "domainStrategy": "UseIPv4" if ipv4_only else "AsIs",
                    "fragment": {"packets": packets, "length": length, "interval": interval},
                },
            },
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}],
        },
    }


# --------------------------------------------------------------------------- #
# subscriptions
# --------------------------------------------------------------------------- #
def subscription(cfgs: Iterable[Dict[str, Any]]) -> str:
    """Plain-text list (one URI per line). Clients accept it directly; the
    base64 wrapper is produced by `bridge`/`sub` when serving over HTTP."""
    return "\n".join(to_uri(c) for c in (normalize(c) for c in cfgs) if c.get("server"))


def sub_base64(cfgs: Iterable[Dict[str, Any]]) -> str:
    return _b64e(subscription(cfgs).encode())


def parse_subscription(text: str) -> List[Dict[str, Any]]:
    """Accepts: base64 blob, plain list of URIs, YAML (best-effort), JSON."""
    return parse_any(text)


def merge_configs(*groups: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Concatenate + de-duplicate by canonical URI."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for group in groups:
        for c in group:
            try:
                key = to_uri(c)
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(normalize(c))
    return out


# --------------------------------------------------------------------------- #
# WireGuard text config (WARP / Amnezia)
# --------------------------------------------------------------------------- #
def wireguard_conf(cfg: Dict[str, Any], dns: str = "1.1.1.1, 1.0.0.1", endpoint: Optional[str] = None) -> str:
    c = normalize(cfg)
    ep = endpoint or f"{c['server']}:{c['port']}"
    lines = [
        "[Interface]",
        f"PrivateKey = {c['wg_private_key']}",
        f"Address = {c['wg_local_address']}",
        f"DNS = {dns}",
        f"MTU = {c['wg_mtu'] or 1280}",
        "",
        "[Peer]",
        f"PublicKey = {c['wg_public_key']}",
        f"Endpoint = {ep}",
        "AllowedIPs = 0.0.0.0/0, ::/0",
        "PersistentKeepalive = 25",
    ]
    if c["wg_preshared_key"]:
        lines.insert(6, f"PresharedKey = {c['wg_preshared_key']}")
    if c["wg_reserved"]:
        try:
            r = [int(x) for x in str(c["wg_reserved"]).split(",") if x.strip() != ""]
            if len(r) == 3:
                lines.insert(6, f"Reserved = {r[0]}, {r[1]}, {r[2]}")
        except Exception:
            pass
    return "\n".join(lines) + "\n"
