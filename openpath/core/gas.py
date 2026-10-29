"""
Google Apps Script relay: generate the script, talk to it, and expose it to the
rest of the phone as a normal local HTTP / SOCKS5 proxy.

Why: the relay is request/response based (Apps Script cannot hold a raw TCP
tunnel open), so clients like v2rayNG cannot speak to it directly. OpenPath
therefore runs a small local proxy that

    plain HTTP  ->  forwarded to the relay as a request          (no MITM)
    HTTPS       ->  terminated locally with a generated cert     (MITM mode)
                    and forwarded the same way

so any app that can use an HTTP or SOCKS5 proxy works again with zero servers.

MITM needs `openssl` (Termux: pkg install openssl) and a CA that you install
once on the device. Without MITM the proxy still works for plain HTTP.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import util

TEMPLATE_REPO_PATH = os.path.join("gas", "Code.gs")
TEMPLATE_RAW_URL = (
    "https://raw.githubusercontent.com/arminabdim/Vpn-panel-for-iran-internet-/main/gas/Code.gs"
)
HOP_HEADERS = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "accept-encoding",
}
DEFAULT_STATE = {"gas_url": "", "gas_key": ""}


# --------------------------------------------------------------------------- #
# script generation
# --------------------------------------------------------------------------- #
def _template(root: Optional[str] = None) -> str:
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
    raise RuntimeError(f"gas/Code.gs not found. Download it from {TEMPLATE_RAW_URL}")


def render_script(auth_key: Optional[str] = None, root: Optional[str] = None) -> Tuple[str, str]:
    key = auth_key or util.rand_hex(16)
    src = _template(root).replace("{{AUTH_KEY}}", key)
    return src, key


def write_script(dest: Optional[str] = None, auth_key: Optional[str] = None, root: Optional[str] = None) -> Tuple[str, str]:
    src, key = render_script(auth_key, root)
    dest = dest or os.path.join(util.base_dir(), "Code.gs")
    util.write_text(dest, src, mode=0o644)
    return dest, key


def configure(url: str = "", key: str = "") -> Dict[str, str]:
    state = util.get_state()
    cfg = {
        "gas_url": (url or state.get("gas_url") or "").strip(),
        "gas_key": (key or state.get("gas_key") or "").strip(),
    }
    util.set_state(**cfg)
    return cfg


def config() -> Dict[str, str]:
    state = util.get_state()
    return {"gas_url": state.get("gas_url") or "", "gas_key": state.get("gas_key") or ""}


def deploy_instructions(script_path: str, key: str) -> str:
    return f"""
Google Apps Script relay - one time setup (about 3 minutes)
{'-' * 58}
1. Open https://script.google.com and sign in with any Google account.
2. New project  ->  delete the sample code.
3. Paste the whole content of:
       {script_path}
   (it already contains your secret key: {key})
4. Deploy -> New deployment -> (gear icon) Web app
       Execute as : Me
       Access     : Anyone        <-- required, otherwise it needs a Google login
5. Click Deploy, approve the permission prompt (Advanced -> Allow), and copy
   the /exec URL.
6. Back in OpenPath:
       openpath gas url https://script.google.com/macros/s/XXXXXXXX/exec
       openpath gas test
       openpath gas serve
"""


# --------------------------------------------------------------------------- #
# relay client
# --------------------------------------------------------------------------- #
class Relay:
    def __init__(self, url: str = "", key: str = "", timeout: int = 45, max_batch: int = 4) -> None:
        cfg = config()
        self.url = (url or cfg.get("gas_url") or "").strip()
        self.key = (key or cfg.get("gas_key") or "").strip()
        self.timeout = timeout
        self.max_batch = max_batch
        if not self.url:
            raise RuntimeError(
                "No Apps Script relay configured. Deploy one (openpath gas new) then:\n"
                "  openpath gas url https://script.google.com/macros/s/XXXX/exec"
            )
        if not self.key:
            raise RuntimeError("No relay key configured: openpath gas key <your-key>")

    # -- low level -------------------------------------------------------- #
    def post(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        body = json.dumps({"k": self.key, "r": requests}).encode()
        status, _h, raw = util.http_request(
            self.url,
            method="POST",
            data=body,
            headers={"Content-Type": "text/plain;charset=utf-8"},
            timeout=self.timeout,
            retries=1,
        )
        if status >= 400:
            raise RuntimeError(f"relay HTTP {status}: {raw[:200]!r}")
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception as exc:
            raise RuntimeError(f"relay returned non-JSON ({raw[:120]!r}) - wrong URL or not deployed as a web app")
        if not data.get("ok"):
            raise RuntimeError(f"relay error: {data.get('error')}")
        return list(data.get("r") or [])

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        follow: bool = True,
    ) -> Tuple[int, Dict[str, str], bytes]:
        hdrs = {k: v for k, v in (headers or {}).items() if k.lower() not in HOP_HEADERS}
        hdrs["Accept-Encoding"] = "identity"
        payload: Dict[str, Any] = {"m": method, "u": url, "h": hdrs, "f": follow}
        if body:
            payload["b"] = base64.b64encode(body).decode()
        res = self.post([payload])[0]
        if res.get("e"):
            raise RuntimeError(str(res["e"]))
        raw = base64.b64decode(res.get("b") or "")
        return int(res.get("s") or 502), dict(res.get("h") or {}), raw

    def ping(self) -> Optional[float]:
        start = time.time()
        try:
            status, _h, _b = self.request("GET", "https://www.gstatic.com/generate_204")
        except Exception:
            return None
        if status >= 500:
            return None
        return (time.time() - start) * 1000

    def get_text(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        _s, _h, body = self.request("GET", url, headers)
        return body.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# local CA / certificates (MITM)
# --------------------------------------------------------------------------- #
def ca_dir() -> str:
    return util.ensure_dir(os.path.join(util.base_dir(), "ca"))


def openssl() -> Optional[str]:
    return shutil.which("openssl")


def ensure_ca() -> Tuple[str, str]:
    """Create (once) and return (ca.crt, ca.key)."""
    d = ca_dir()
    crt, key = os.path.join(d, "ca.crt"), os.path.join(d, "ca.key")
    if os.path.exists(crt) and os.path.exists(key):
        return crt, key
    exe = openssl()
    if not exe:
        raise RuntimeError("openssl not found. In Termux: pkg install openssl")
    serial = os.path.join(d, "ca.srl")
    util.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
              "-days", "3650", "-subj", "/CN=OpenPath Local CA/O=OpenPath"])
    util.write_text(serial, "1000\n", mode=0o644)
    return crt, key


def cert_for(host: str) -> Tuple[str, str]:
    """Per-host certificate signed by our CA (cached)."""
    d = util.ensure_dir(os.path.join(ca_dir(), "hosts"))
    safe = util.safe_name(host)[:64]
    crt, key = os.path.join(d, safe + ".crt"), os.path.join(d, safe + ".key")
    if os.path.exists(crt) and os.path.exists(key):
        return crt, key
    ca_crt, ca_key = ensure_ca()
    exe = openssl()
    if not exe:
        raise RuntimeError("openssl not found. In Termux: pkg install openssl")
    csr = os.path.join(d, safe + ".csr")
    ext = os.path.join(d, safe + ".ext")
    util.write_text(ext, f"subjectAltName=DNS:{host}\nbasicConstraints=CA:FALSE\n"
                         "keyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n", mode=0o644)
    util.run([exe, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", csr, "-subj", f"/CN={host}"])
    util.run([exe, "x509", "-req", "-in", csr, "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
              "-out", crt, "-days", "825", "-sha256", "-extfile", ext])
    return crt, key


# --------------------------------------------------------------------------- #
# proxy server (HTTP + SOCKS5 on one port)
# --------------------------------------------------------------------------- #
class ProxyHandler:
    """Handles one client connection (HTTP proxy, CONNECT, or SOCKS5)."""

    def __init__(self, conn: socket.socket, addr: Tuple[str, int], relay: Relay, mitm: bool = True, verbose: bool = False) -> None:
        self.conn = conn
        self.addr = addr
        self.relay = relay
        self.mitm = mitm
        self.verbose = verbose
        self.buf = b""
        self.tls: Optional[ssl.SSLSocket] = None

    # -- io helpers -------------------------------------------------------- #
    def _read_line(self, limit: int = 65536) -> bytes:
        while b"\r\n" not in self.buf:
            chunk = self.conn.recv(4096)
            if not chunk:
                raise EOFError
            self.buf += chunk
            if len(self.buf) > limit:
                raise ValueError("request too large")
        line, _, rest = self.buf.partition(b"\r\n")
        self.buf = rest
        return line

    def _read_exactly(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.conn.recv(4096)
            if not chunk:
                raise EOFError
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def _send(self, data: bytes) -> None:
        try:
            self.conn.sendall(data)
        except Exception:
            raise EOFError

    def log(self, msg: str) -> None:
        if self.verbose:
            print(util.dim(f"    {msg}"))

    # -- dispatch ---------------------------------------------------------- #
    def serve(self) -> None:
        try:
            first = self.conn.recv(1, socket.MSG_PEEK)
            if first == b"\x05":
                self.serve_socks5()
            else:
                self.serve_http()
        except Exception:
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass

    # -- http proxy -------------------------------------------------------- #
    def serve_http(self) -> None:
        while True:
            try:
                line = self._read_line().decode("latin-1")
            except (EOFError, ValueError):
                return
            if not line:
                return
            parts = line.split()
            if len(parts) < 2:
                return
            method, target = parts[0].upper(), parts[1]
            version = parts[2] if len(parts) > 2 else "HTTP/1.1"

            headers: List[Tuple[str, str]] = []
            while True:
                raw = self._read_line()
                if raw == b"":
                    break
                if b":" not in raw:
                    continue
                k, _, v = raw.decode("latin-1").partition(":")
                headers.append((k.strip(), v.strip()))

            body = b""
            length = next((int(v) for k, v in headers if k.lower() == "content-length" and v.isdigit()), 0)
            if length:
                body = self._read_exactly(length)

            if method == "CONNECT":
                self.handle_connect(target, version)
                return

            if not target.startswith("http"):
                self._send(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                return

            self.forward(method, target, headers, body, version)

            if not any(k.lower() == "proxy-connection" and v.lower() == "keep-alive" for k, v in headers):
                if not any(k.lower() == "connection" and "keep-alive" in v.lower() for k, v in headers):
                    return

    def forward(self, method: str, url: str, headers: List[Tuple[str, str]], body: bytes, version: str) -> None:
        hdrs = {k: v for k, v in headers}
        hdrs.pop("Proxy-Connection", None)
        try:
            status, resp_headers, content = self.relay.request(method, url, hdrs, body)
        except Exception as exc:
            self.log(f"relay error: {exc}")
            self._send(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        safe_headers = [(k, v) for k, v in resp_headers.items() if k.lower() not in ("transfer-encoding", "content-length", "content-encoding", "connection")]
        out = [f"HTTP/1.1 {status} OpenPath".encode()]
        for k, v in safe_headers:
            try:
                out.append(f"{k}: {v}".encode("latin-1"))
            except Exception:
                continue
        out.append(f"Content-Length: {len(content)}".encode())
        out.append(b"Connection: keep-alive")
        out.append(b"")
        out.append(b"")
        self._send(b"\r\n".join(out[:-1]) + b"\r\n\r\n" + content)
        self.log(f"{method} {url[:70]} -> {status} ({len(content)}B)")

    def handle_connect(self, target: str, version: str) -> None:
        host, _, port = target.rpartition(":")
        port = int(port or 443)
        if not self.mitm:
            self._send(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            return
        try:
            self._send(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            crt, key = cert_for(host)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(crt, key)
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            self.conn = ctx.wrap_socket(self.conn, server_side=True)
        except Exception as exc:
            self.log(f"mitm setup failed: {exc}")
            return
        self.serve_http_tls(host, port)

    def serve_http_tls(self, host: str, port: int) -> None:
        """Read HTTP/1.1 requests off a MITM'd TLS socket."""
        while True:
            try:
                line = self._read_line().decode("latin-1")
            except (EOFError, ValueError):
                return
            if not line:
                return
            parts = line.split()
            if len(parts) < 2:
                return
            method, path = parts[0].upper(), parts[1]
            headers: List[Tuple[str, str]] = []
            while True:
                try:
                    raw = self._read_line()
                except (EOFError, ValueError):
                    return
                if raw == b"":
                    break
                if b":" not in raw:
                    continue
                k, _, v = raw.decode("latin-1").partition(":")
                headers.append((k.strip(), v.strip()))
            body = b""
            length = next((int(v) for k, v in headers if k.lower() == "content-length" and v.isdigit()), 0)
            if length:
                body = self._read_exactly(length)

            scheme = "https" if port == 443 else "http"
            url = path if path.startswith("http") else f"{scheme}://{host}" + (f":{port}" if port not in (80, 443) else "") + path
            self.forward(method, url, headers, body, "HTTP/1.1")

            if not any(k.lower() == "connection" and "keep-alive" in v.lower() for k, v in headers):
                return

    # -- socks5 ------------------------------------------------------------ #
    def serve_socks5(self) -> None:
        try:
            greeting = self._read_exactly(2)
            nmethods = greeting[1]
            self._read_exactly(nmethods)
            self._send(b"\x05\x00")
            req = self._read_exactly(4)
            if req[1] != 0x01:  # only CONNECT
                self._send(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return
            atyp = req[3]
            if atyp == 0x01:
                host = socket.inet_ntoa(self._read_exactly(4))
            elif atyp == 0x03:
                n = self._read_exactly(1)[0]
                host = self._read_exactly(n).decode("latin-1")
            elif atyp == 0x04:
                host = socket.inet_ntop(socket.AF_INET6, self._read_exactly(16))
            else:
                self._send(b"\x05\x08\x00\x01" + b"\x00" * 6)
                return
            port = int.from_bytes(self._read_exactly(2), "big")
        except Exception:
            return

        self._send(b"\x05\x00\x00\x01" + b"\x00" * 6)
        if not self.mitm:
            return
        try:
            crt, key = cert_for(host)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(crt, key)
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            self.conn = ctx.wrap_socket(self.conn, server_side=True)
        except Exception as exc:
            self.log(f"socks mitm failed: {exc}")
            return
        self.serve_http_tls(host, port)


class ProxyServer(threading.Thread):
    def __init__(self, host: str = "127.0.0.1", port: int = 8080, mitm: bool = True, verbose: bool = False, relay: Optional[Relay] = None) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.mitm = mitm
        self.verbose = verbose
        self.relay = relay or Relay()
        self.stop_flag = threading.Event()
        self.sock: Optional[socket.socket] = None

    def run(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(64)
        srv.settimeout(0.5)
        self.sock = srv
        while not self.stop_flag.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            handler = ProxyHandler(conn, addr, self.relay, mitm=self.mitm, verbose=self.verbose)
            threading.Thread(target=handler.serve, daemon=True).start()
        try:
            srv.close()
        except Exception:
            pass

    def stop(self) -> None:
        self.stop_flag.set()


def serve_forever(port: int = 8080, mitm: bool = True, verbose: bool = False, host: str = "127.0.0.1") -> ProxyServer:
    server = ProxyServer(host=host, port=port, mitm=mitm, verbose=verbose)
    server.start()
    return server


def ca_cert_path() -> str:
    return os.path.join(ca_dir(), "ca.crt")
