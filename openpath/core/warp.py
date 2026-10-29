"""
Cloudflare WARP / WARP+ account registration - pure Python, no binaries.

Generates WireGuard profiles you can import into MahsaNG, v2rayNG (WireGuard),
Amnezia, Hiddify, sing-box, or the official 1.1.1.1 app.

Why this exists: WARP is the only "free, unlimited, no server" option that
survives a lot of Iranian filtering pressure, and it is the standard way to get
a non-Iranian exit IP without paying for anything. Registration needs a
Curve25519 key pair, which we implement here in ~30 lines so that Termux users
with a bare `python` are not blocked on downloading a Go binary.

Fallback: if the pure-Python registration is rejected by Cloudflare (they
change the API version from time to time) we try the official-ish `wgcf`
binary from ViRb3/wgcf.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from . import configs, util

# --------------------------------------------------------------------------- #
# X25519 (RFC 7748) - standard library only
# --------------------------------------------------------------------------- #
P = 2**255 - 19
A24 = 121665


def _clamp(key: bytes) -> bytes:
    k = bytearray(key)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return bytes(k)


def _invert(z: int) -> int:
    return pow(z, P - 2, P)


def _bytes_to_int(b: bytes) -> int:
    return int.from_bytes(b, "little")


def _int_to_bytes(x: int) -> bytes:
    return (x % P).to_bytes(32, "little")


def x25519(scalar: bytes, point: bytes) -> bytes:
    """Montgomery ladder (RFC 7748 section 5)."""
    k = _clamp(scalar)
    u = bytearray(point)
    u[31] &= 0x7F  # clear the MSB of the final byte
    x1 = _bytes_to_int(bytes(u))
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for t in range(254, -1, -1):
        k_t = (k[t // 8] >> (t % 8)) & 1
        if swap ^ k_t:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = k_t
        A = (x2 + z2) % P
        AA = (A * A) % P
        B = (x2 - z2) % P
        BB = (B * B) % P
        E = (AA - BB) % P
        C = (x3 + z3) % P
        D = (x3 - z3) % P
        DA = (D * A) % P
        CB = (C * B) % P
        x3 = pow(DA + CB, 2, P)
        z3 = (x1 * pow(DA - CB, 2, P)) % P
        x2 = (AA * BB) % P
        z2 = (E * (AA + A24 * E)) % P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return _int_to_bytes((x2 * _invert(z2)) % P)


def generate_keypair() -> Tuple[str, str]:
    """Returns (private_key_b64, public_key_b64)."""
    import secrets

    priv = _clamp(secrets.token_bytes(32))
    pub = x25519(priv, b"\x09" + b"\x00" * 31)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
API_HOST = "api.cloudflareclient.com"
API_VERSIONS = ("v0a400", "v0a884", "v0a745", "v0a985")
UA = "okhttp/3.12.1"
CLIENT_VERSION = "a-6.30-2237"


def _tos() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def register(license_key: str = "", device: str = "Android", verbose: bool = False) -> Dict[str, Any]:
    """Register a fresh WARP account. Returns the parsed account dict."""
    priv, pub = generate_keypair()
    payload = {
        "install_id": "",
        "tos": _tos(),
        "key": pub,
        "fcm_token": "",
        "referrer": "",
        "warp_enabled": False,
        "type": device,
        "locale": "en_US",
    }
    last_error = ""
    for version in API_VERSIONS:
        url = f"https://{API_HOST}/{version}/reg"
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": UA,
            "Host": API_HOST,
            "CF-Client-Version": CLIENT_VERSION,
            "Accept-Encoding": "gzip",
            "Connection": "Keep-Alive",
        }
        try:
            status, _h, body = util.http_request(
                url, method="POST", data=json.dumps(payload).encode(), headers=headers, timeout=30, retries=1
            )
        except Exception as exc:
            last_error = str(exc)
            continue
        if verbose:
            util.info(f"WARP {version}: HTTP {status}")
        if status >= 400:
            last_error = f"HTTP {status}: {body[:200]!r}"
            continue
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except Exception as exc:
            last_error = f"bad json: {exc}"
            continue
        if not data.get("success") or not data.get("result"):
            last_error = json.dumps(data.get("errors") or data)[:200]
            continue

        result = data["result"]
        result["_private_key"] = priv
        result["_api_version"] = version
        if license_key:
            ok_up, msg = upgrade(result, license_key)
            result["_license_result"] = msg
            result["_license_ok"] = ok_up
        return result

    # ---- fallback: wgcf binary --------------------------------------------
    util.warn(f"pure-Python registration failed ({last_error}); trying wgcf binary ...")
    try:
        return register_with_wgcf(license_key=license_key)
    except Exception as exc:
        raise RuntimeError(f"WARP registration failed: {last_error} / wgcf: {exc}")


def upgrade(result: Dict[str, Any], license_key: str) -> Tuple[bool, str]:
    """Apply a WARP+ licence key to a freshly registered account."""
    acc_id = result.get("id")
    token = result.get("token")
    version = result.get("_api_version") or API_VERSIONS[0]
    if not acc_id or not token:
        return False, "account id/token missing"
    url = f"https://{API_HOST}/{version}/reg/{acc_id}/account"
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": UA,
        "Host": API_HOST,
        "Authorization": f"Bearer {token}",
        "CF-Client-Version": CLIENT_VERSION,
    }
    try:
        status, _h, body = util.http_request(
            url, method="PATCH", data=json.dumps({"license": license_key}).encode(), headers=headers, timeout=30
        )
    except Exception as exc:
        return False, str(exc)
    if status >= 400:
        return False, f"HTTP {status}: {body[:160]!r}"
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return False, "bad json"
    ok_up = bool(data.get("success"))
    return ok_up, "WARP+ activated" if ok_up else json.dumps(data.get("errors") or data)[:160]


# --------------------------------------------------------------------------- #
# wgcf binary fallback
# --------------------------------------------------------------------------- #
def wgcf_path() -> Optional[str]:
    found = shutil.which("wgcf")
    if found:
        return found
    cached = os.path.join(util.base_dir(), "bin", "wgcf")
    if os.path.exists(cached):
        return cached
    return None


def install_wgcf(force: bool = False) -> str:
    path = wgcf_path()
    if path and not force and os.path.basename(path) == "wgcf":
        return path
    dest = os.path.join(util.base_dir(), "bin", "wgcf")
    util.ensure_dir(os.path.dirname(dest))
    assets = util.github_release_assets("ViRb3/wgcf")
    asset = util.pick_asset(assets, must=(), avoid=("sha256", "sig", "sum", ".deb", ".rpm", ".exe", "darwin", "windows"))
    if not asset:
        raise RuntimeError("could not find a wgcf binary for this device")
    url = asset.get("browser_download_url")
    util.download(url, dest, timeout=180)
    os.chmod(dest, 0o755)
    return dest


def register_with_wgcf(license_key: str = "") -> Dict[str, Any]:
    import tempfile

    binary = wgcf_path() or install_wgcf()
    workdir = tempfile.mkdtemp(prefix="openpath-wgcf-")
    env = dict(os.environ)
    env["HOME"] = workdir
    if license_key:
        env["WGCF_LICENSE_KEY"] = license_key
    try:
        code, out, errout = util.run([binary, "register", "--accept-tos"], timeout=180)
        if code != 0:
            raise RuntimeError(f"wgcf register failed: {errout or out}")
        if license_key:
            util.run([binary, "update"], timeout=120)
        code, out, errout = util.run([binary, "generate"], timeout=120)
        if code != 0:
            raise RuntimeError(f"wgcf generate failed: {errout or out}")
        profile = os.path.join(os.getcwd(), "wgcf-profile.conf")
        for candidate in (os.path.join(workdir, "wgcf-profile.conf"), profile):
            if os.path.exists(candidate):
                return {"_wgcf_profile": util.read_text(candidate), "_private_key": "", "_api_version": "wgcf"}
        raise RuntimeError("wgcf produced no profile")
    finally:
        pass


# --------------------------------------------------------------------------- #
# profile building
# --------------------------------------------------------------------------- #
DEFAULT_ENDPOINT = "engage.cloudflareclient.com:2408"
DEFAULT_PEER_KEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="


def _reserved(cfg_block: Any) -> List[int]:
    """`reserved` comes back either as a list of ints or as base64 of 3 bytes."""
    if isinstance(cfg_block, list):
        try:
            return [int(x) for x in cfg_block]
        except Exception:
            return []
    if isinstance(cfg_block, str) and cfg_block:
        try:
            raw = base64.b64decode(cfg_block + "=" * (-len(cfg_block) % 4))
            return list(raw[:3])
        except Exception:
            return []
    return []


def profile_from_result(result: Dict[str, Any], name: str = "OpenPath-WARP") -> Dict[str, Any]:
    """Turn a registration result into our canonical config dict."""
    if "_wgcf_profile" in result:
        return _profile_from_wgcf_conf(result["_wgcf_profile"], name)

    cfg = (result.get("config") or {}) if isinstance(result, dict) else {}
    peers = cfg.get("peers") or [{}]
    peer = peers[0] or {}
    endpoint = ((peer.get("endpoint") or {}).get("host")) or (peer.get("endpoint") or {}).get("v4") or DEFAULT_ENDPOINT
    if ":" not in endpoint:
        endpoint = f"{endpoint}:2408"
    host, _, port = endpoint.rpartition(":")
    host = host.strip("[]")

    iface = cfg.get("interface") or {}
    addrs = iface.get("addresses") or {}
    v4 = addrs.get("v4") or "172.16.0.2"
    v6 = addrs.get("v6") or ""
    local = f"{v4}/32" + (f", {v6}/128" if v6 else "")

    reserved = _reserved(cfg.get("reserved") or (result.get("config") or {}).get("reserved"))
    account = result.get("account") or {}
    warp_plus = bool(account.get("warp_plus")) or bool(result.get("_license_ok"))

    return configs.normalize(
        {
            "proto": "wireguard",
            "name": f"{name}{'-plus' if warp_plus else ''}",
            "server": host,
            "port": int(port or 2408),
            "wg_private_key": result.get("_private_key", ""),
            "wg_public_key": peer.get("public_key") or DEFAULT_PEER_KEY,
            "wg_local_address": local,
            "wg_mtu": 1280,
            "wg_reserved": ",".join(str(x) for x in reserved),
            "network": "raw",
            "security": "none",
            "extra": {"account_type": account.get("account_type", ""), "warp_plus": warp_plus},
        }
    )


def _profile_from_wgcf_conf(text: str, name: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]").lower()
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            data[f"{section}.{k.strip().lower()}"] = v.strip()
    endpoint = data.get("peer.endpoint") or DEFAULT_ENDPOINT
    host, _, port = endpoint.rpartition(":")
    local = data.get("interface.address") or "172.16.0.2/32"
    reserved = ""
    raw = data.get("peer.reserved") or ""
    if raw:
        reserved = ",".join(x.strip() for x in raw.split(",") if x.strip() != "")
    return configs.normalize(
        {
            "proto": "wireguard",
            "name": name,
            "server": host.strip("[]"),
            "port": int(port or 2408),
            "wg_private_key": data.get("interface.private_key", ""),
            "wg_public_key": data.get("peer.public_key", DEFAULT_PEER_KEY),
            "wg_local_address": local,
            "wg_mtu": int(data.get("interface.mtu") or 1280),
            "wg_reserved": reserved,
            "network": "raw",
            "security": "none",
        }
    )


def from_conf(text: str, name: str = "WARP") -> Dict[str, Any]:
    return _profile_from_wgcf_conf(text, name)


def conf(cfg: Dict[str, Any], dns: str = "1.1.1.1, 1.0.0.1") -> str:
    return configs.wireguard_conf(cfg, dns=dns)


def generate(
    license_key: str = "",
    device: str = "Android",
    count: int = 1,
    name: str = "OpenPath-WARP",
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(max(1, count)):
        result = register(license_key=license_key, device=device, verbose=verbose)
        cfg = profile_from_result(result, name if count == 1 else f"{name}-{i + 1}")
        out.append(cfg)
        if i + 1 < count:
            time.sleep(1)
    save(out)
    return out


def load() -> List[Dict[str, Any]]:
    return [configs.normalize(c) for c in (util.get_state().get("warp_profiles") or []) if c.get("server")]


def save(profiles: List[Dict[str, Any]]) -> None:
    state = util.get_state()
    existing = [c for c in (state.get("warp_profiles") or []) if c.get("server")]
    merged = existing + [c for c in profiles]
    seen = set()
    uniq = []
    for c in merged:
        key = (c.get("server"), c.get("wg_private_key"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    util.set_state(warp_profiles=uniq[-20:])
