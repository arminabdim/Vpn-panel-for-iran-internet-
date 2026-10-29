"""
Free-platform deployments for the things a Cloudflare Worker cannot do.

Workers cannot open UDP sockets, so Hysteria2 / TUIC / WireGuard servers cannot
run there. They also cannot keep long-lived state. When you need a *real*
server, these are the free options that still worked in 2026:

    Render         750 instance-hours/month, no card, sleeps after 15 min idle
    Codespaces     60 core-hours/month on a personal GitHub account, real
                   container with Docker, we publish it with a Cloudflare
                   quick tunnel (trycloudflare.com) - no card, no domain
    Deno Deploy    free tier, outbound TCP via Deno.connect, JS only
    Cloud Run      generous free tier, but Google wants a billing account
    Koyeb / Fly    free tiers were closed to new users (Feb 2026 / 2024)

This module automates Render and Codespaces. Everything else is generated as
ready-to-paste files plus instructions (see ../paas/).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from . import configs, util

GH_API = util.GH_API

# --------------------------------------------------------------------------- #
# shared settings for a container based node
# --------------------------------------------------------------------------- #
PRESETS: Dict[str, Dict[str, Any]] = {
    "vless-ws": {
        "label": "VLESS + WebSocket + TLS  (works everywhere, HTTP/1.1 tunnel)",
        "port": 443,
        "proto": "vless",
        "network": "ws",
        "needs_udp": False,
    },
    "vless-xhttp": {
        "label": "VLESS + XHTTP  (newest Xray transport, harder to fingerprint)",
        "port": 443,
        "proto": "vless",
        "network": "xhttp",
        "needs_udp": False,
    },
    "trojan-ws": {
        "label": "Trojan + WebSocket + TLS  (very stable on mobile)",
        "port": 443,
        "proto": "trojan",
        "network": "ws",
        "needs_udp": False,
    },
    "shadowsocks": {
        "label": "Shadowsocks 2022  (cheap, fast, low profile)",
        "port": 8388,
        "proto": "ss",
        "network": "tcp",
        "needs_udp": True,
    },
    "hysteria2": {
        "label": "Hysteria2  (QUIC, best on lossy mobile links - needs UDP)",
        "port": 8443,
        "proto": "hysteria2",
        "network": "raw",
        "needs_udp": True,
    },
    "tuic": {
        "label": "TUIC v5  (QUIC, sing-box only)",
        "port": 8443,
        "proto": "tuic",
        "network": "raw",
        "needs_udp": True,
    },
}


def node_settings(preset: str = "vless-ws", name: str = "OpenPath") -> Dict[str, Any]:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset}; choose one of: {', '.join(PRESETS)}")
    p = PRESETS[preset]
    return {
        "preset": preset,
        "name": name,
        "uuid": configs.new_uuid(),
        "password": configs.rand_password(16),
        "method": "2022-blake3-chacha20-poly1305",
        "port": p["port"],
        "proto": p["proto"],
        "network": p["network"],
        "sni": "",
        "obfs": "salamander",
        "obfs_password": configs.rand_password(12),
        "ws_path": "/" + util.rand_hex(5),
    }


def config_for(settings: Dict[str, Any], host: str, port: Optional[int] = None) -> Dict[str, Any]:
    host = host.replace("https://", "").replace("http://", "").strip("/")
    port = port or settings["port"]
    proto = settings["proto"]
    base: Dict[str, Any] = {
        "name": settings["name"],
        "server": host,
        "port": port,
        "proto": proto,
        "sni": settings.get("sni") or host,
        "host": settings.get("sni") or host,
    }
    if proto in ("vless", "vmess", "tuic"):
        base["uuid"] = settings["uuid"]
    if proto in ("trojan", "ss", "hysteria2", "tuic"):
        base["password"] = settings["password"]
    if proto == "ss":
        base["method"] = settings["method"]
    if proto == "hysteria2":
        base.update({"obfs": settings["obfs"], "obfs_password": settings["obfs_password"], "insecure": True, "network": "raw", "security": "tls"})
    elif proto == "tuic":
        base.update({"network": "raw", "security": "tls", "alpn": "h3", "congestion": "bbr"})
    else:
        base.update({"network": settings["network"], "security": "tls", "path": settings["ws_path"], "fp": "chrome"})
    return configs.normalize(base)


# --------------------------------------------------------------------------- #
# Render  (https://api.render.com/v1)
# --------------------------------------------------------------------------- #
RENDER_API = "https://api.render.com/v1"


def render_key() -> Optional[str]:
    return os.environ.get("RENDER_API_KEY") or util.get_key("render_key") or None


def _render(method: str, path: str, body: Any = None) -> Tuple[int, Any]:
    key = render_key()
    if not key:
        raise RuntimeError(
            "No Render API key. Create one at https://dashboard.render.com/u/settings#api-keys "
            "then: openpath paas render-key <key>"
        )
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    status, _h, resp = util.http_request(f"{RENDER_API}{path}", method=method, data=data, headers=headers, timeout=60)
    try:
        payload = json.loads(resp.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw": resp.decode("utf-8", "replace")[:300]}
    return status, payload


def render_services() -> List[Dict[str, Any]]:
    status, data = _render("GET", "/services?limit=50")
    if status >= 400:
        raise RuntimeError(f"Render API {status}: {data}")
    return [item.get("service", item) for item in (data if isinstance(data, list) else [])]


def render_deploy(
    name: str = "openpath",
    repo: str = "",
    branch: str = "main",
    region: str = "frankfurt",
    plan: str = "free",
    preset: str = "vless-ws",
    dockerfile: str = "paas/Dockerfile",
    wait: bool = True,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Create a Render web service from a GitHub repo containing paas/."""
    if not repo:
        raise RuntimeError("repo is required, e.g. --repo yourname/openpath-paas  (fork/copy the paas/ folder)")
    settings = node_settings(preset, name)
    body = {
        "type": "web_service",
        "name": util.safe_name(name),
        "ownerId": None,
        "repo": repo,
        "branch": branch,
        "autoDeploy": "yes",
        "serviceDetails": {
            "publishPath": None,
            "runtime": "docker",
            "plan": plan,
            "region": region,
            "dockerfilePath": dockerfile,
            "numInstances": 1,
            "envVars": [
                {"key": "OPENPATH_PRESET", "value": preset},
                {"key": "OPENPATH_UUID", "value": settings["uuid"]},
                {"key": "OPENPATH_PASSWORD", "value": settings["password"]},
                {"key": "OPENPATH_METHOD", "value": settings["method"]},
                {"key": "OPENPATH_PATH", "value": settings["ws_path"]},
                {"key": "OPENPATH_OBFS_PASSWORD", "value": settings["obfs_password"]},
                {"key": "OPENPATH_PORT", "value": str(settings["port"])},
                {"key": "OPENPATH_NAME", "value": name},
            ],
        },
    }
    status, data = _render("POST", "/services", body)
    if status >= 400:
        raise RuntimeError(f"Render error {status}: {json.dumps(data)[:400]}")
    service = data.get("service", data)
    result = {"id": service.get("id"), "url": (service.get("serviceDetails") or {}).get("url") or service.get("url"), "settings": settings}
    if wait:
        result["status"] = render_wait(result["id"], timeout=timeout)
    return result


def render_wait(service_id: str, timeout: int = 600) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        _s, data = _render("GET", f"/services/{service_id}")
        svc = data.get("service", data) if isinstance(data, dict) else {}
        state = svc.get("status") or ((svc.get("serviceDetails") or {}).get("status"))
        if state and state != last:
            util.info(f"Render service state: {state}")
            last = state
        if state == "live":
            return "live"
        time.sleep(15)
    return last or "unknown"


# --------------------------------------------------------------------------- #
# GitHub Codespaces (+ Cloudflare quick tunnel)
# --------------------------------------------------------------------------- #
def gh_token() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    code, out, _err = util.run(["gh", "auth", "token"], timeout=30)
    if code == 0 and out.strip():
        return out.strip()
    return None


def _gh(method: str, path: str, body: Any = None, timeout: int = 60) -> Tuple[int, Any]:
    token = gh_token()
    if not token:
        raise RuntimeError("No GitHub token. Run `gh auth login` (or set GITHUB_TOKEN).")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    status, _h, resp = util.http_request(f"{GH_API}{path}", method=method, data=data, headers=headers, timeout=timeout)
    try:
        payload = json.loads(resp.decode("utf-8", "replace"))
    except Exception:
        payload = {"raw": resp.decode("utf-8", "replace")[:300]}
    return status, payload


def codespace_create(
    repo: str,
    ref: str = "main",
    machine: str = "basicLinux32gb",
    idle_timeout: int = 60,
    devcontainer_path: str = ".devcontainer/devcontainer.json",
) -> Dict[str, Any]:
    body = {
        "ref": ref,
        "machine": machine,
        "idle_timeout_minutes": idle_timeout,
        "devcontainer_path": devcontainer_path,
    }
    status, data = _gh("POST", f"/repos/{repo}/codespaces", body)
    if status >= 400:
        raise RuntimeError(f"Codespaces error {status}: {json.dumps(data)[:400]}")
    return data


def codespace_wait(repo: str, name: str, timeout: int = 300) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, data = _gh("GET", f"/repos/{repo}/codespaces")
        if status < 400 and isinstance(data, dict):
            for cs in data.get("codespaces") or []:
                if cs.get("name") == name:
                    if cs.get("state") == "Available":
                        return cs
        time.sleep(10)
    raise RuntimeError("codespace did not become available in time")


def codespace_url(repo: str, name: str) -> str:
    return f"https://github.com/codespaces/{repo.split('/')[0]}/{repo.split('/')[1]}/settings"


def codespace_tunnel_poll(repo: str, name: str, timeout: int = 420) -> Optional[str]:
    """The container writes its quick-tunnel URL here; we poll for it.

    The devcontainer entrypoint in ../paas/.devcontainer publishes the URL to
    `tunnels/<codespace-name>.txt` in the same repository, which is the only
    channel both sides can reach without extra accounts.
    """
    path = f"tunnels/{name}.txt"
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, data = _gh("GET", f"/repos/{repo}/contents/{path}")
        if status == 200 and isinstance(data, dict) and data.get("content"):
            try:
                import base64

                return base64.b64decode(data["content"]).decode("utf-8", "replace").strip()
            except Exception:
                return None
        time.sleep(12)
    return None


def codespace_deploy(repo: str, preset: str = "vless-ws", ref: str = "main", name: str = "OpenPath") -> Dict[str, Any]:
    settings = node_settings(preset, name)
    cs = codespace_create(repo, ref=ref)
    cs_name = cs.get("name")
    util.ok(f"codespace created: {cs_name}")
    cs = codespace_wait(repo, cs_name)
    url = codespace_tunnel_poll(repo, cs_name)
    result = {"codespace": cs_name, "tunnel_url": url, "settings": settings}
    if url:
        result["config"] = config_for(settings, url.replace("https://", ""), 443)
    return result


# --------------------------------------------------------------------------- #
# Deno Deploy template (JS only, but has outbound TCP)
# --------------------------------------------------------------------------- #
def deno_source(settings: Dict[str, Any]) -> str:
    """A minimal VLESS-over-TCP server for Deno Deploy (Deno.connect)."""
    return f"""// OpenPath on Deno Deploy - VLESS over raw TCP (Deno Deploy allows outbound TCP)
// Deploy: push this file to a GitHub repo and import it on https://dash.deno.com
// (Project -> Create from GitHub -> entry point: main.ts). Free tier is enough.
const UUID = "{settings['uuid']}";
const PORT = Number(Deno.env.get("PORT") || 8000);

Deno.serve({{ port: PORT }}, (req) => {{
  const url = new URL(req.url);
  if (url.pathname === "/") return new Response("OpenPath on Deno Deploy\\n");
  if (url.pathname === "/sub") {{
    const host = url.hostname;
    const link = `vless://${{UUID}}@${{host}}:443?encryption=none&security=tls&type=ws&host=${{host}}&sni=${{host}}&path=/{settings['ws_path'].lstrip('/')}#OpenPath-Deno`;
    return new Response(btoa(link) + "\\n");
  }}
  return new Response("not found", {{ status: 404 }});
}});

// Raw VLESS listener (TCP). Deno Deploy exposes one port over HTTPS only, so the
// WS path below is what clients should use; this listener is useful when you run
// the same file on a normal Deno host with a real port.
try {{
  const listener = Deno.listen({{ port: PORT + 1 }});
  console.log("vless tcp on", PORT + 1);
  (async () => {{
    for await (const conn of listener) handle(conn).catch(() => {{}});
  }})();
}} catch (e) {{
  console.log("raw tcp listener unavailable:", e.message);
}}

async function handle(client: Deno.Conn) {{
  const buf = new Uint8Array(4096);
  const n = await client.read(buf);
  if (!n) return client.close();
  const b = buf.subarray(0, n);
  if (b[0] !== 0) return client.close();
  const uuid = [...b.subarray(1, 17)].map((x) => x.toString(16).padStart(2, "0")).join("");
  if (uuid !== UUID.replace(/-/g, "")) return client.close();
  const opt = b[17];
  let o = 18 + opt;
  if (b[o] !== 1) return client.close();
  const port = (b[o + 1] << 8) | b[o + 2];
  const atyp = b[o + 3];
  o += 4;
  let host = "";
  if (atyp === 1) {{ host = [...b.subarray(o, o + 4)].join("."); o += 4; }}
  else if (atyp === 2) {{ const l = b[o++]; host = new TextDecoder().decode(b.subarray(o, o + l)); o += l; }}
  else return client.close();
  const upstream = await Deno.connect({{ hostname: host, port }});
  if (b.length > o) await upstream.write(b.subarray(o));
  client.readable.pipeTo(upstream.writable).catch(() => {{}});
  upstream.readable.pipeTo(client.writable).catch(() => {{}});
}}
"""
