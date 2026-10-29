"""
Cloudflare Workers / Pages automation.

    * render `worker/src/index.js` with your settings
    * deploy / update / delete it through the Cloudflare REST API (no wrangler,
      no node: pure stdlib, works in Termux)
    * create the share links + subscription URL for v2rayNG / MahsaNG / ...
    * optional custom domain on a zone you already have on Cloudflare

You need one thing: an API token with
    Account  -> Workers Scripts  -> Edit
    Account  -> Account Settings -> Read
    Zone     -> Workers Routes   -> Edit   (only for custom domains)

Create it here:  https://dash.cloudflare.com/profile/api-tokens
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from . import configs, util

API = "https://api.cloudflare.com/client/v4"
TEMPLATE_REPO_PATH = os.path.join("worker", "src", "index.js")
TEMPLATE_RAW_URL = (
    "https://raw.githubusercontent.com/arminabdim/Vpn-panel-for-iran-internet-/main/worker/src/index.js"
)

DEFAULT_TLS_PORTS = [443, 8443, 2053, 2083, 2087]
DEFAULT_PLAIN_PORTS = [80, 8080, 8880, 2052, 2082, 2086]


# --------------------------------------------------------------------------- #
# token / account
# --------------------------------------------------------------------------- #
def token() -> Optional[str]:
    return os.environ.get("CF_API_TOKEN") or util.get_key("cf_token") or None


def set_token(value: str) -> None:
    util.set_key("cf_token", value.strip())
    os.environ["CF_API_TOKEN"] = value.strip()


def _headers() -> Dict[str, str]:
    tok = token()
    if not tok:
        raise RuntimeError(
            "No Cloudflare API token yet. Create one at "
            "https://dash.cloudflare.com/profile/api-tokens "
            "(permissions: Account.Workers Scripts Edit, Account Settings Read) "
            "then run: openpath cf token"
        )
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _api(method: str, path: str, body: Any = None, raw: bool = False) -> Tuple[int, Any]:
    url = f"{API}{path}"
    data = None if body is None else json.dumps(body).encode()
    status, _h, resp = util.http_request(url, method=method, data=data, headers=_headers(), timeout=60)
    try:
        payload = json.loads(resp.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw": resp.decode("utf-8", "replace")}
    if raw:
        return status, payload
    if not payload.get("success", False) and status >= 400:
        msgs = "; ".join(e.get("message", "") for e in (payload.get("errors") or [{"message": str(payload)}]))
        raise RuntimeError(f"Cloudflare API error {status}: {msgs}")
    return status, payload


def accounts() -> List[Dict[str, Any]]:
    _s, data = _api("GET", "/accounts?per_page=50")
    return list(data.get("result") or [])


def pick_account(account_id: Optional[str] = None) -> Dict[str, Any]:
    accs = accounts()
    if not accs:
        raise RuntimeError("No Cloudflare account found for this token.")
    if account_id:
        for a in accs:
            if a["id"] == account_id:
                return a
    if len(accs) == 1:
        return accs[0]
    util.rule("Choose a Cloudflare account")
    for i, a in enumerate(accs, 1):
        print(f"  {util.bold(str(i))}) {a.get('name')}  ({a['id']})")
    idx = util.ask("Account number", "1")
    try:
        return accs[int(idx) - 1]
    except Exception:
        return accs[0]


def subdomain(account_id: str) -> Optional[str]:
    try:
        _s, data = _api("GET", f"/accounts/{account_id}/workers/subdomain")
        return (data.get("result") or {}).get("subdomain")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# worker source
# --------------------------------------------------------------------------- #
def _template(root: Optional[str] = None) -> str:
    """Load the worker template from the repo, or fetch it from GitHub."""
    candidates = []
    if root:
        candidates.append(os.path.join(root, TEMPLATE_REPO_PATH))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "..", TEMPLATE_REPO_PATH))
    candidates.append(os.path.join(os.getcwd(), TEMPLATE_REPO_PATH))
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            return util.read_text(path)
    raise RuntimeError(
        "worker/src/index.js not found. Run openpath from the repository folder "
        f"(or pass root=...). You can also download it from {TEMPLATE_RAW_URL}"
    )


def render_worker(
    settings: Dict[str, Any],
    root: Optional[str] = None,
) -> str:
    """Fill the {{PLACEHOLDER}} slots of worker/src/index.js."""
    src = _template(root)
    mapping = {
        "{{UUID}}": str(settings.get("uuid") or ""),
        "{{TROJAN_PASSWORD}}": str(settings.get("trojan_password") or ""),
        "{{WS_PATH}}": str(settings.get("ws_path") or "/openpath"),
        "{{SUB_PATH}}": str(settings.get("sub_path") or "sub"),
        "{{NODE_NAME}}": str(settings.get("node_name") or "OpenPath"),
        "{{PROXY_IP}}": str(settings.get("proxy_ip") or ""),
        "{{PROXY_PORT}}": str(int(settings.get("proxy_port") or 443)),
        "{{UPSTREAM_MODE}}": str(settings.get("upstream_mode") or "direct"),
        "{{UPSTREAM_HOST}}": str(settings.get("upstream_host") or ""),
        "{{UPSTREAM_PORT}}": str(int(settings.get("upstream_port") or 1080)),
        "{{UPSTREAM_USER}}": str(settings.get("upstream_user") or ""),
        "{{UPSTREAM_PASS}}": str(settings.get("upstream_pass") or ""),
        "{{RELAY_ENABLED}}": "true" if settings.get("relay_enabled", True) else "false",
        "{{EXTRA_NODES}}": "\n".join(settings.get("extra_nodes") or []),
    }
    for key, value in mapping.items():
        src = src.replace(key, value)
    # safety: no placeholders may survive
    left = re.findall(r"\{\{[A-Z_]+\}\}", src)
    if left:
        raise RuntimeError(f"unfilled worker placeholders: {sorted(set(left))}")
    return src


def default_settings(node_name: str = "OpenPath") -> Dict[str, Any]:
    return {
        "uuid": configs.new_uuid(),
        "trojan_password": configs.rand_password(12),
        "ws_path": "/" + secrets.token_hex(4),
        "sub_path": "sub-" + secrets.token_hex(3),
        "node_name": node_name,
        "proxy_ip": "",
        "proxy_port": 443,
        "upstream_mode": "direct",
        "upstream_host": "",
        "upstream_port": 1080,
        "upstream_user": "",
        "upstream_pass": "",
        "relay_enabled": True,
        "extra_nodes": [],
    }


# --------------------------------------------------------------------------- #
# deploy
# --------------------------------------------------------------------------- #
def _multipart(metadata: Dict[str, Any], script: str) -> Tuple[bytes, str]:
    boundary = "----openpath" + secrets.token_hex(12)
    parts = []
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="metadata"\r\n'
        "Content-Type: application/json\r\n\r\n" + json.dumps(metadata) + "\r\n"
    )
    parts.append(
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="script"; filename="worker.js"\r\n'
        "Content-Type: application/javascript+module\r\n\r\n" + script + "\r\n"
    )
    parts.append(f"--{boundary}--\r\n")
    body = "".join(parts).encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


def deploy(
    script_name: str,
    script: str,
    account_id: Optional[str] = None,
    enable_subdomain: bool = True,
) -> Dict[str, Any]:
    """Upload (or replace) a Worker script. Returns info incl. its URL."""
    account = pick_account(account_id)
    acc_id = account["id"]
    body, ctype = _multipart(
        {
            "main_module": "worker.js",
            "bindings": [],
            "compatibility_date": time.strftime("%Y-%m-%d"),
            "compatibility_flags": ["nodejs_compat"],
            "observability": {"enabled": False},
        },
        script,
    )
    headers = dict(_headers())
    headers.pop("Content-Type", None)
    headers["Content-Type"] = ctype
    status, _h, resp = util.http_request(
        f"{API}/accounts/{acc_id}/workers/scripts/{script_name}",
        method="PUT",
        data=body,
        headers=headers,
        timeout=90,
    )
    try:
        payload = json.loads(resp.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw": resp.decode("utf-8", "replace")}
    if status >= 400 or not payload.get("success", False):
        msgs = "; ".join(e.get("message", "") for e in (payload.get("errors") or [{"message": str(payload)[:300]}]))
        if status == 403 and "workers" in msgs.lower():
            msgs += " (the token needs Account -> Workers Scripts -> Edit)"
        raise RuntimeError(f"deploy failed ({status}): {msgs}")

    url = None
    if enable_subdomain:
        try:
            _s, data = _api("POST", f"/accounts/{acc_id}/workers/scripts/{script_name}/subdomain", {"enabled": True})
            url = (data.get("result") or {}).get("url")
        except Exception:
            url = None
    if not url:
        sub = subdomain(acc_id)
        if sub:
            url = f"https://{script_name}.{sub}.workers.dev"
    return {"account_id": acc_id, "account_name": account.get("name"), "script": script_name, "url": url}


def list_workers(account_id: Optional[str] = None) -> List[Dict[str, Any]]:
    account = pick_account(account_id)
    _s, data = _api("GET", f"/accounts/{account['id']}/workers/scripts")
    return list(data.get("result") or [])


def delete_worker(script_name: str, account_id: Optional[str] = None) -> bool:
    account = pick_account(account_id)
    _s, data = _api("DELETE", f"/accounts/{account['id']}/workers/scripts/{script_name}")
    return bool(data.get("success"))


def add_custom_domain(script_name: str, hostname: str, zone_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
    account = pick_account(account_id)
    _s, data = _api(
        "POST",
        f"/accounts/{account['id']}/workers/scripts/{script_name}/domains",
        {"hostname": hostname, "zone_id": zone_id, "environment": "production"},
    )
    return data.get("result") or {}


def zones() -> List[Dict[str, Any]]:
    _s, data = _api("GET", "/zones?per_page=50")
    return list(data.get("result") or [])


# --------------------------------------------------------------------------- #
# configs for the deployed worker
# --------------------------------------------------------------------------- #
def worker_configs(
    host: str,
    settings: Dict[str, Any],
    ports: Optional[List[int]] = None,
    plain_ports: Optional[List[int]] = None,
    sni: Optional[str] = None,
    clean_ip: Optional[str] = None,
    name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build the client configs matching a deployed worker."""
    host = re.sub(r"^https?://", "", host).strip().rstrip("/")
    sni = sni or host
    node = name or settings.get("node_name") or "OpenPath"
    out: List[Dict[str, Any]] = []

    if settings.get("uuid"):
        for port in ports or DEFAULT_TLS_PORTS:
            out.append(
                configs.normalize(
                    {
                        "proto": "vless",
                        "name": f"{node}-{port}",
                        "server": host,
                        "port": port,
                        "uuid": settings["uuid"],
                        "network": "ws",
                        "security": "tls",
                        "sni": sni,
                        "host": sni,
                        "path": settings.get("ws_path") or "/",
                        "fp": "chrome",
                    }
                )
            )
        for port in plain_ports or DEFAULT_PLAIN_PORTS:
            out.append(
                configs.normalize(
                    {
                        "proto": "vless",
                        "name": f"{node}-{port}",
                        "server": host,
                        "port": port,
                        "uuid": settings["uuid"],
                        "network": "ws",
                        "security": "none",
                        "host": sni,
                        "path": settings.get("ws_path") or "/",
                    }
                )
            )
    if settings.get("trojan_password"):
        out.append(
            configs.normalize(
                {
                    "proto": "trojan",
                    "name": f"{node}-trojan",
                    "server": host,
                    "port": 443,
                    "password": settings["trojan_password"],
                    "network": "ws",
                    "security": "tls",
                    "sni": sni,
                    "host": sni,
                    "path": settings.get("ws_path") or "/",
                    "fp": "chrome",
                }
            )
        )
    if clean_ip:
        for c in out:
            c["_clean_ip"] = clean_ip
    return out


def subscription_url(host: str, sub_path: str, fmt: str = "b64") -> str:
    host = re.sub(r"^https?://", "", host).strip().rstrip("/")
    return f"https://{host}/{sub_path.lstrip('/')}?format={fmt}"


def save_deployment(info: Dict[str, Any], settings: Dict[str, Any]) -> None:
    state = util.get_state()
    deploys = state.get("cf_workers") or []
    deploys = [d for d in deploys if d.get("script") != info.get("script")]
    deploys.append(
        {
            "script": info.get("script"),
            "url": info.get("url"),
            "account_id": info.get("account_id"),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "settings": settings,
        }
    )
    util.set_state(cf_workers=deploys)


def deployments() -> List[Dict[str, Any]]:
    return list(util.get_state().get("cf_workers") or [])
