"""
Small, dependency-free helpers: HTTP, files, colours, terminal shaping, arch
detection, GitHub release downloads.

Everything has to work on a phone inside Termux, so: standard library only,
no hard failures on missing optional pieces, and ASCII-only terminal output
by default (Persian text is only printed if a shaper is available).
"""

from __future__ import annotations

import http.client
import json
import os
import platform
import random
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

UA = (
    "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Mobile Safari/537.36"
)

APP_NAME = "openpath"
DEFAULT_TIMEOUT = 20


# --------------------------------------------------------------------------- #
# paths & storage
# --------------------------------------------------------------------------- #
def base_dir() -> str:
    """Directory where OpenPath keeps its state (configs, worker code, certs)."""
    env = os.environ.get("OPENPATH_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    home = os.path.expanduser("~")
    return os.path.join(home, ".openpath")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def state_path(name: str) -> str:
    return os.path.join(ensure_dir(base_dir()), name)


def load_json(name: str, default: Any = None) -> Any:
    p = state_path(name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(name: str, data: Any) -> str:
    p = state_path(name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return p


STATE_FILE = "state.json"


def get_state() -> Dict[str, Any]:
    return load_json(STATE_FILE, {}) or {}


def set_state(**kwargs: Any) -> Dict[str, Any]:
    st = get_state()
    st.update(kwargs)
    save_json(STATE_FILE, st)
    return st


def get_key(key: str, default: Any = None) -> Any:
    return get_state().get(key, default)


def set_key(key: str, value: Any) -> Any:
    return set_state(**{key: value})[key]


# --------------------------------------------------------------------------- #
# colours & printing
# --------------------------------------------------------------------------- #
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def color_enabled() -> bool:
    return _USE_COLOR


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def red(t: str) -> str:
    return _c("31", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def blue(t: str) -> str:
    return _c("34", t)


def cyan(t: str) -> str:
    return _c("36", t)


def magenta(t: str) -> str:
    return _c("35", t)


def bold(t: str) -> str:
    return _c("1", t)


def dim(t: str) -> str:
    return _c("2", t)


def ok(msg: str) -> None:
    print(green("[OK]   ") + msg)


def warn(msg: str) -> None:
    print(yellow("[WARN] ") + msg)


def err(msg: str) -> None:
    print(red("[ERR]  ") + msg)


def info(msg: str) -> None:
    print(cyan("[INFO] ") + msg)


def step(msg: str) -> None:
    print(blue("==>    ") + msg)


def rule(title: str = "") -> None:
    width = 58
    if title:
        print(dim("─" * 4 + f" {title} " + "─" * max(0, width - len(title) - 6)))
    else:
        print(dim("─" * width))


# --------------------------------------------------------------------------- #
# Persian text shaping (optional). Broken glyphs in Termux are a real problem,
# so Persian is *never* printed unless a shaper is installed.
# --------------------------------------------------------------------------- #
_SHAPER: Optional[Callable[[str], str]] = None
_SHAPER_CHECKED = False


def _build_shaper() -> Optional[Callable[[str], str]]:
    try:
        import arabic_reshaper  # type: ignore

        from bidi.algorithm import get_display  # type: ignore

        def shape(text: str) -> str:
            return get_display(arabic_reshaper.reshape(text))

        return shape
    except Exception:
        return None


def shape(text: str) -> str:
    """Return `text` shaped+reordered for terminal display, or ASCII fallback."""
    global _SHAPER, _SHAPER_CHECKED
    if not _SHAPER_CHECKED:
        _SHAPER = _build_shaper()
        _SHAPER_CHECKED = True
    if _SHAPER is not None:
        try:
            return _SHAPER(text)
        except Exception:
            return text
    return text


def persian_supported() -> bool:
    global _SHAPER, _SHAPER_CHECKED
    if not _SHAPER_CHECKED:
        _SHAPER = _build_shaper()
        _SHAPER_CHECKED = True
    return _SHAPER is not None


def fa(fa_text: str, en_text: str) -> str:
    """Print Persian when the terminal can shape it, otherwise English."""
    return shape(fa_text) if persian_supported() else en_text


# --------------------------------------------------------------------------- #
# input
# --------------------------------------------------------------------------- #
def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        if secret:
            import getpass

            value = getpass.getpass(f"{prompt}{suffix}: ")
        else:
            value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return value or default


def ask_choice(prompt: str, options: List[Tuple[str, str]], default: str = "1") -> str:
    """Numbered menu. `options` = [(key, label), ...]"""
    for i, (_key, label) in enumerate(options, 1):
        print(f"  {bold(str(i))}) {label}")
    while True:
        value = ask(prompt, default)
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1][0]
        if value in [k for k, _ in options]:
            return value
        err("Invalid choice, try again.")


def ask_yes(prompt: str, default: bool = True) -> bool:
    value = ask(prompt + (" [Y/n]" if default else " [y/N]"), "y" if default else "n").lower()
    return value.startswith("y") if value else default


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def build_opener(proxy: Optional[str] = None, insecure: bool = False) -> urllib.request.OpenerDirector:
    handlers: List[Any] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def http_request(
    url: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    proxy: Optional[str] = None,
    insecure: bool = False,
    retries: int = 2,
) -> Tuple[int, Dict[str, str], bytes]:
    """Returns (status, headers, body). Never raises for HTTP status codes."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            opener = build_opener(proxy=proxy, insecure=insecure)
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as exc:  # real HTTP error, body available
            try:
                body = exc.read()
            except Exception:
                body = b""
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, body
        except Exception as exc:  # network hiccup
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"request failed: {url} ({last})")


def get_json(url: str, **kwargs: Any) -> Any:
    status, _h, body = http_request(url, **kwargs)
    if status >= 400:
        raise RuntimeError(f"HTTP {status} for {url}")
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError(f"bad JSON from {url}: {exc}")


def download(
    url: str,
    dest: str,
    timeout: int = 120,
    proxy: Optional[str] = None,
    insecure: bool = False,
    progress: bool = True,
) -> str:
    ensure_dir(os.path.dirname(dest) or ".")
    status, headers, body = http_request(url, timeout=timeout, proxy=proxy, insecure=insecure)
    if status >= 400:
        raise RuntimeError(f"download failed ({status}): {url}")
    with open(dest, "wb") as fh:
        fh.write(body)
    size = len(body)
    if progress:
        ok(f"downloaded {os.path.basename(dest)} ({human_size(size)})")
    return dest


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


# --------------------------------------------------------------------------- #
# network helpers
# --------------------------------------------------------------------------- #
def tcp_ping(host: str, port: int, timeout: float = 3.0) -> Optional[float]:
    """TCP connect latency in ms (None = unreachable)."""
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.time() - start) * 1000
    except Exception:
        return None


def http_ping(url: str, timeout: float = 5.0, proxy: Optional[str] = None) -> Optional[float]:
    start = time.time()
    try:
        http_request(url, timeout=timeout, proxy=proxy, retries=0)
        return (time.time() - start) * 1000
    except Exception:
        return None


def public_ip(timeout: int = 10) -> Optional[str]:
    for url in ("https://api.ipify.org", "https://api64.ipify.org", "https://ifconfig.me/ip"):
        try:
            _s, _h, body = http_request(url, timeout=timeout, retries=0)
            value = body.decode().strip()
            if value and len(value) < 64:
                return value
        except Exception:
            continue
    return None


def free_port(preferred: int = 0, host: str = "127.0.0.1") -> int:
    if preferred:
        try:
            with socket.socket() as s:
                s.bind((host, preferred))
                return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def is_ip(value: str) -> bool:
    v = value or ""
    if ":" in v:
        return bool(re.fullmatch(r"[0-9a-fA-F:]+", v))
    return bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", v))


def resolve(host: str, prefer_ipv4: bool = True) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return []
    addrs = [i[4][0] for i in infos]
    if prefer_ipv4:
        addrs.sort(key=lambda a: 0 if ":" not in a else 1)
    out = []
    for a in addrs:
        if a not in out:
            out.append(a)
    return out


# --------------------------------------------------------------------------- #
# system / arch
# --------------------------------------------------------------------------- #
def arch() -> str:
    m = platform.machine().lower()
    if m in ("aarch64", "arm64", "armv8l"):
        return "arm64"
    if m in ("armv7l", "armv6l", "arm"):
        return "arm"
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("i386", "i686", "x86"):
        return "386"
    return m or "unknown"


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "") or os.path.exists("/data/data/com.termux/files/usr/bin")


def which(name: str) -> Optional[str]:
    return shutil.which(name)


def run(cmd: List[str], check: bool = False, capture: bool = True, timeout: int = 600) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or ""), (proc.stderr or "")
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def open_url(url: str) -> bool:
    """Best effort: open in the Android browser (termux-open) or desktop."""
    for cmd in (["termux-open-url", url], ["xdg-open", url], ["open", url]):
        if which(cmd[0]):
            code, _o, _e = run(cmd, capture=False)
            return code == 0
    return False


GH_API = "https://api.github.com"


def github_release_assets(repo: str, tag: str = "latest", timeout: int = 30) -> List[Dict[str, Any]]:
    url = f"{GH_API}/repos/{repo}/releases/{tag}"
    data = get_json(url, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    return list(data.get("assets") or [])


def pick_asset(assets: List[Dict[str, Any]], must: Iterable[str] = (), avoid: Iterable[str] = ("sha256", "sig", "sbom", "amd64", "x86_64", "386", "darwin", "windows", ".exe", ".deb", ".rpm")) -> Optional[Dict[str, Any]]:
    """Pick a linux binary matching the device arch."""
    want = arch()
    cands = []
    for a in assets:
        name = (a.get("name") or "").lower()
        if any(x in name for x in avoid):
            continue
        if must and not all(m.lower() in name for m in must):
            continue
        score = 0
        if want == "arm64" and any(k in name for k in ("arm64", "aarch64")):
            score = 3
        elif want == "arm" and "arm" in name:
            score = 3
        elif want in name:
            score = 3
        elif "linux" in name or name.endswith(".tar.gz") or "." not in name:
            score = 1
        cands.append((score, a))
    cands.sort(key=lambda x: -x[0])
    return cands[0][1] if cands and cands[0][0] > 0 else None


def prompt_input(prompt: str, default: str = "") -> str:
    return ask(prompt, default)


def clip(text: str) -> bool:
    """Copy to clipboard when possible (termux-clipboard-set / xclip)."""
    for cmd, args in (
        (["termux-clipboard-set"], None),
        (["xclip", "-selection", "clipboard"], None),
        (["xsel", "--clipboard", "--input"], None),
    ):
        if which(cmd[0]):
            try:
                proc = subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=10)
                return proc.returncode == 0
            except Exception:
                return False
    return False


def spinner(stop_event: threading.Event, text: str = "working") -> threading.Thread:
    frames = "|/-\\"

    def loop() -> None:
        i = 0
        while not stop_event.is_set():
            sys.stdout.write(f"\r{cyan(text + ' ' + frames[i % 4])}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.15)
        sys.stdout.write("\r" + " " * (len(text) + 6) + "\r")
        sys.stdout.flush()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def rand_hex(n: int) -> str:
    import secrets

    return secrets.token_hex(n)


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()) or "openpath"


def write_text(path: str, content: str, mode: int = 0o600) -> str:
    ensure_dir(os.path.dirname(os.path.abspath(path)) or ".")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    try:
        os.chmod(path, mode)
    except Exception:
        pass
    return path


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
