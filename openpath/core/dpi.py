"""
Local DPI bypass - no server, no root, no data plan.

Iranian ISPs filter with DPI boxes that read the TLS ClientHello (SNI) and the
plain HTTP Host header. The counter-measures that do NOT need raw sockets (so
they work in Termux / on a non-rooted phone) are:

    split     send the ClientHello as several small TCP segments
    tlsrec    re-frame it as several TLS records (RFC allows this)
    fake      open a throw-away connection and send a decoy ClientHello with a
              random SNI first, then the real one
    delay     tiny pause between segments (defeats reassembly timeouts)

OpenPath exposes all of them as a local HTTP + SOCKS5 proxy, so you can point
v2rayNG / MahsaNG / a browser at 127.0.0.1:PORT and let it do the rest. It can
also install and drive the well known binaries (SpoofDPI, ByeDPI) if you prefer
those.
"""

from __future__ import annotations

import os
import random
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import util

TLS_HANDSHAKE = 0x16
DECOY_SNIS = [
    "www.microsoft.com",
    "www.apple.com",
    "www.wikipedia.org",
    "assets.msn.com",
    "update.googleapis.com",
]


# --------------------------------------------------------------------------- #
# ClientHello surgery
# --------------------------------------------------------------------------- #
def split_records(data: bytes, chunks: int = 3) -> List[bytes]:
    """Re-frame one TLS record as `chunks` records (payload is unchanged)."""
    if len(data) < 6 or data[0] != TLS_HANDSHAKE:
        return [data]
    total = struct.unpack(">H", data[3:5])[0]
    payload = data[5 : 5 + total]
    rest = data[5 + total :]
    if len(payload) < 2 or chunks < 2:
        return [data]
    step = max(1, len(payload) // chunks)
    parts = [payload[i : i + step] for i in range(0, len(payload), step)]
    out = []
    for part in parts:
        out.append(bytes([TLS_HANDSHAKE, data[1], data[2]]) + struct.pack(">H", len(part)) + part)
    if rest:
        out.append(rest)
    return out


def sni_of(data: bytes) -> Optional[str]:
    """Best-effort SNI extraction (no full ASN.1 parser needed)."""
    if not data or data[0] != TLS_HANDSHAKE:
        return None
    idx = data.find(b"\x00\x00", 5)  # extension list marker, rough but effective
    if idx < 0:
        return None
    blob = data[5:]
    pos = blob.find(b"\x00\x00")
    if pos < 0:
        return None
    i = blob.find(bytes.fromhex("0000"), pos)
    # walk the extensions looking for type 0x0000 (server_name)
    ext_blob = blob[i + 2 :] if i >= 0 else b""
    # simpler: search for readable ascii hostnames preceded by the SNI header
    try:
        p = blob.index(b"\x00\x00")
        # extension list length is 2 bytes at p+2
        ext = blob[p + 4 :]
        while len(ext) > 4:
            etype = int.from_bytes(ext[0:2], "big")
            elen = int.from_bytes(ext[2:4], "big")
            body = ext[4 : 4 + elen]
            if etype == 0 and len(body) > 5:
                slen = int.from_bytes(body[3:5], "big")
                return body[5 : 5 + slen].decode("latin-1")
            ext = ext[4 + elen :]
    except Exception:
        return None
    return None


def replace_sni(data: bytes, new_host: str) -> bytes:
    """Swap the SNI value in place (same length, so no length fixups)."""
    host = sni_of(data)
    if not host:
        return data
    old = host.encode()
    new = new_host.encode()
    if len(new) != len(old):
        # pad/truncate with a subdomain trick: keep the same byte length
        new = (new_host + "." + "a" * max(0, len(old) - len(new_host) - 1))[: len(old)].encode()
    return data.replace(old, new, 1)


# --------------------------------------------------------------------------- #
# proxy
# --------------------------------------------------------------------------- #
class DesyncProxy(threading.Thread):
    """HTTP + SOCKS5 proxy that applies DPI evasion on the first packet."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8081,
        chunks: int = 3,
        delay: float = 0.012,
        fake: bool = True,
        sni_spoof: bool = False,
        verbose: bool = False,
        auto_fallback: bool = True,
        probe_timeout: float = 1.5,
    ) -> None:
        super().__init__(daemon=True)
        self.host, self.port = host, port
        self.chunks, self.delay, self.fake = chunks, delay, fake
        self.sni_spoof = sni_spoof
        self.verbose = verbose
        # Some middleboxes (corporate/sandbox TLS inspectors, and occasionally
        # an ISP's own gear) reject a fragmented ClientHello outright. When
        # `auto_fallback` is on we notice the instant RST/FIN and silently
        # retry the same connection without fragmentation, so the user never
        # sees a broken page - they only lose the DPI trick on that host.
        self.auto_fallback = auto_fallback
        self.probe_timeout = probe_timeout
        self.stop_flag = threading.Event()

    # -- server loop -------------------------------------------------------- #
    def run(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(64)
        srv.settimeout(0.5)
        while not self.stop_flag.is_set():
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        try:
            srv.close()
        except Exception:
            pass

    def stop(self) -> None:
        self.stop_flag.set()

    # -- per connection ----------------------------------------------------- #
    def _client(self, conn: socket.socket) -> None:
        buf = b""
        try:
            first = conn.recv(1, socket.MSG_PEEK)
            if first == b"\x05":
                target = self._socks_handshake(conn)
            else:
                target = self._http_connect(conn)
            if not target:
                return
            self._bridge(conn, target, buf)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _read_line(self, conn: socket.socket, buf: bytearray) -> bytes:
        while b"\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                raise EOFError
            buf.extend(chunk)
        line, _, rest = bytes(buf).partition(b"\r\n")
        buf.clear()
        buf.extend(rest)
        return line

    def _http_connect(self, conn: socket.socket) -> Optional[Tuple[str, int]]:
        buf = bytearray()
        line = self._read_line(conn, buf).decode("latin-1")
        parts = line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            try:
                conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            except Exception:
                pass
            return None
        while True:
            raw = self._read_line(conn, buf)
            if raw == b"":
                break
        host, _, port = parts[1].rpartition(":")
        conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        return host, int(port or 443)

    def _socks_handshake(self, conn: socket.socket) -> Optional[Tuple[str, int]]:
        def readn(n: int) -> bytes:
            data = b""
            while len(data) < n:
                chunk = conn.recv(n - len(data))
                if not chunk:
                    raise EOFError
                data += chunk
            return data

        readn(2)
        n = readn(1)[0]
        readn(n)
        conn.sendall(b"\x05\x00")
        head = readn(4)
        atyp = head[3]
        if atyp == 0x01:
            host = socket.inet_ntoa(readn(4))
        elif atyp == 0x03:
            ln = readn(1)[0]
            host = readn(ln).decode("latin-1")
        elif atyp == 0x04:
            host = socket.inet_ntop(socket.AF_INET6, readn(16))
        else:
            return None
        port = int.from_bytes(readn(2), "big")
        conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
        return host, port

    # -- the actual trick --------------------------------------------------- #
    def _bridge(self, conn: socket.socket, target: Tuple[str, int], _buf: bytes) -> None:
        host, port = target
        upstream = socket.create_connection((host, port), timeout=20)
        upstream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        if port in (443, 8443, 2053, 2083, 2087) or self.sni_spoof:
            # wait briefly for the ClientHello, then re-frame it
            conn.settimeout(1.5)
            try:
                data = conn.recv(8192)
            except socket.timeout:
                data = b""
            conn.settimeout(None)
            if data:
                if self.fake:
                    self._send_decoy(host, port, data)
                parts = split_records(data, self.chunks)
                fragmenting = len(parts) > 1 and self.chunks > 1
                send_error = False
                for i, part in enumerate(parts):
                    try:
                        upstream.sendall(part)
                    except Exception:
                        # the path (or a middlebox) killed it mid-handshake
                        send_error = True
                        break
                    if self.delay and i < len(parts) - 1:
                        time.sleep(self.delay)

                if fragmenting and self.auto_fallback:
                    # Ask the path once, briefly, whether it survived the
                    # fragments. "dead" (or a failed send) means we redo the
                    # handshake in one piece so the page still loads. The
                    # client socket is untouched until we know, which is what
                    # makes the retry possible at all.
                    if send_error or self._probe(upstream, conn) == "dead":
                        fresh = self._plain_retry(host, port, data)
                        if fresh:
                            self._pipe(conn, fresh)
                        else:
                            try:
                                conn.close()
                            except Exception:
                                pass
                    else:
                        self._pipe(conn, upstream)
                    return

                if send_error:
                    return
                if self.verbose:
                    util.dim(f"    desync {host}:{port} segments={len(parts)} decoy={self.fake}")
        self._pipe(conn, upstream)

    def _probe(self, upstream: socket.socket, conn: socket.socket) -> str:
        """'"ok"' if the path looks alive, '"dead"' if it closed on us."""
        try:
            upstream.settimeout(self.probe_timeout)
            first = upstream.recv(1)
        except socket.timeout:
            return "ok"  # silent but open - keep going and hope for the best
        except Exception:
            return "dead"
        finally:
            try:
                upstream.settimeout(None)
            except Exception:
                pass
        if first == b"":
            return "dead"
        try:
            conn.sendall(first)  # forward the byte we just consumed
        except Exception:
            return "dead"
        return "ok"

    def _plain_retry(self, host: str, port: int, data: bytes) -> Optional[socket.socket]:
        """Re-open the connection and send the very same bytes in one write."""
        try:
            fresh = socket.create_connection((host, port), timeout=20)
            fresh.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            fresh.sendall(data)
            if self.verbose:
                util.dim(f"    {host}:{port} fragmented handshake rejected -> retried plainly")
            return fresh
        except Exception:
            return None

    def _send_decoy(self, host: str, port: int, data: bytes) -> None:
        if data[0] != TLS_HANDSHAKE:
            return
        decoy = replace_sni(data, random.choice(DECOY_SNIS))
        try:
            sock = socket.create_connection((host, port), timeout=3)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.sendall(decoy)
            try:
                sock.settimeout(0.4)
                sock.recv(1024)
            except Exception:
                pass
            sock.close()
        except Exception:
            pass

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket, counter: Optional[List[int]] = None) -> None:
        def copy(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(65535)
                    if not data:
                        break
                    if counter is not None:
                        counter[0] += len(data)
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass

        t = threading.Thread(target=copy, args=(a, b), daemon=True)
        t.start()
        copy(b, a)  # upstream -> client (counted for the fallback check)
        try:
            a.close()
            b.close()
        except Exception:
            pass


def start(
    port: int = 8081,
    chunks: int = 3,
    delay: float = 0.012,
    fake: bool = True,
    sni_spoof: bool = False,
    host: str = "127.0.0.1",
    verbose: bool = False,
    auto_fallback: bool = True,
) -> DesyncProxy:
    proxy = DesyncProxy(
        host=host,
        port=port,
        chunks=chunks,
        delay=delay,
        fake=fake,
        sni_spoof=sni_spoof,
        verbose=verbose,
        auto_fallback=auto_fallback,
    )
    proxy.start()
    return proxy


# --------------------------------------------------------------------------- #
# external binaries
# --------------------------------------------------------------------------- #
def spoofdpi_path() -> Optional[str]:
    found = shutil.which("spoof-dpi") or shutil.which("spoofdpi")
    if found:
        return found
    cached = os.path.join(util.base_dir(), "bin", "spoof-dpi")
    return cached if os.path.exists(cached) else None


def install_spoofdpi(force: bool = False) -> str:
    path = spoofdpi_path()
    if path and not force:
        return path
    dest = os.path.join(util.base_dir(), "bin", "spoof-dpi")
    util.ensure_dir(os.path.dirname(dest))
    assets = util.github_release_assets("xvzc/SpoofDPI")
    asset = util.pick_asset(assets, avoid=("sha256", "sig", "sum", ".deb", ".rpm", ".exe", "darwin", "windows"))
    if not asset:
        raise RuntimeError("no SpoofDPI build matched this device; use the built-in desync proxy instead")
    util.download(asset["browser_download_url"], dest, timeout=180)
    os.chmod(dest, 0o755)
    return dest


def run_spoofdpi(port: int = 8081, dns: str = "1.1.1.1", extra: Optional[List[str]] = None) -> subprocess.Popen:
    binary = spoofdpi_path() or install_spoofdpi()
    cmd = [binary, "--addr", f"127.0.0.1:{port}", "--dns-addr", dns, "--enable-doh"]
    if extra:
        cmd += extra
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def byedpi_path() -> Optional[str]:
    found = shutil.which("ciadpi") or shutil.which("byedpi")
    if found:
        return found
    cached = os.path.join(util.base_dir(), "bin", "ciadpi")
    return cached if os.path.exists(cached) else None


def install_byedpi(force: bool = False) -> str:
    """Build hufrea/byedpi from source (needs clang/make: pkg install clang make git)."""
    path = byedpi_path()
    if path and not force:
        return path
    for tool in ("git", "make", "clang"):
        if not shutil.which(tool) and not shutil.which("cc"):
            raise RuntimeError(f"{tool} not found. In Termux: pkg install git make clang")
    work = os.path.join(util.base_dir(), "src", "byedpi")
    if os.path.exists(work):
        util.run(["git", "-C", work, "pull", "--ff-only"])
    else:
        util.ensure_dir(os.path.dirname(work))
        util.run(["git", "clone", "--depth", "1", "https://github.com/hufrea/byedpi.git", work])
    code, out, errout = util.run(["make"], timeout=900)
    if code != 0:
        raise RuntimeError(f"build failed: {errout[-500:]}")
    built = os.path.join(work, "ciadpi")
    if not os.path.exists(built):
        raise RuntimeError("ciadpi binary not produced")
    dest = os.path.join(util.base_dir(), "bin", "ciadpi")
    util.ensure_dir(os.path.dirname(dest))
    shutil.copy(built, dest)
    os.chmod(dest, 0o755)
    return dest


def run_byedpi(port: int = 8081, args: Optional[List[str]] = None) -> subprocess.Popen:
    binary = byedpi_path() or install_byedpi()
    cmd = [binary, "-i", "127.0.0.1", "-p", str(port)] + (args or ["-f", "-1", "-s", "1", "-d", "1", "-A", "r,s"])
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
