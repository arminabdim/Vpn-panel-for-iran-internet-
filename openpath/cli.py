"""
OpenPath command line interface.

Built to be usable on a phone with a hardware keyboard in one hand: short
commands, numbered menus, and everything important reachable from the main
menu. Output is ASCII by default because Persian glyphs break in Termux unless
a shaper is installed (`pip install arabic-reshaper python-bidi` switches the
Persian hints on automatically).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

from .core import cf as cf_mod
from .core import configs, util
from .core import dpi as dpi_mod
from .core import gas as gas_mod
from .core import net as net_mod
from .core import paas as paas_mod
from .core import sub as sub_mod
from .core import warp as warp_mod
from .core import bridge as bridge_mod
from .core.selftest import run_selftest

BANNER = r"""
   ___                    ____  _   _
  / _ \ _ __   ___ _ __  |  _ \| | | |
 | | | | '_ \ / _ \ '_ \ | |_) | |_| |
 | |_| | |_) |  __/ | | ||  __/|  _  |
  \___/| .__/ \___|_| |_||_|   |_| |_|
       |_|     free internet, no server
"""

MENU = [
    ("panel", "Open the web panel (does the work for you)"),
    ("cf", "Cloudflare Worker  - free VLESS/Trojan node, no server"),
    ("warp", "Cloudflare WARP / WARP+  - unlimited WireGuard"),
    ("gas", "Google Apps Script relay  - the Esfand fallback"),
    ("dpi", "Local DPI bypass  - no server, no root"),
    ("sub", "Public configs: collect, merge, convert, serve"),
    ("paas", "Free containers (Render / Codespaces) - UDP protocols"),
    ("make", "Build a config by hand (any protocol)"),
    ("test", "Latency / reachability test"),
    ("doctor", "Check the environment"),
    ("selftest", "Run the offline self test"),
    ("help", "Command reference"),
    ("guide", "The plain-language guide"),
]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _print_configs(cfgs: List[Dict[str, Any]], title: str = "Configs") -> None:
    if not cfgs:
        util.warn("no configs")
        return
    util.rule(title)
    for i, c in enumerate(cfgs, 1):
        print(f"  {util.bold(str(i))}) {c['name']}  [{c['proto']} {c['server']}:{c['port']}]")
    print()


def _offer_export(cfgs: List[Dict[str, Any]], default_fmt: str = "b64") -> None:
    """Ask what to do with freshly built configs."""
    if not sys.stdin.isatty():
        # piped / scripted run: print the links and leave.
        util.rule("Share links")
        for c in cfgs:
            print(configs.to_uri(c))
        print()
        util.rule("Base64 subscription")
        print(base64.b64encode(configs.subscription(cfgs).encode()).decode())
        return
    while True:
        print()
        print("  " + util.bold("What next?"))
        print("    1) print share links            5) sing-box JSON (MahsaNG)")
        print("    2) base64 subscription          6) Clash / Mihomo YAML")
        print("    3) Xray JSON (v2rayNG)          7) save to file")
        print("    4) copy all to clipboard        0) done")
        choice = util.ask("Choose", "1")
        if choice == "0" or choice == "":
            return
        if choice == "1":
            util.rule("Share links")
            for c in cfgs:
                print(configs.to_uri(c))
        elif choice == "2":
            util.rule("Base64 subscription")
            print(base64.b64encode(configs.subscription(cfgs).encode()).decode())
        elif choice == "3":
            util.rule("Xray JSON")
            print(json.dumps(configs.xray_config(cfgs), indent=2, ensure_ascii=False))
        elif choice == "4":
            text = configs.subscription(cfgs)
            if util.clip(text):
                util.ok("copied to clipboard")
            else:
                util.warn("no clipboard tool found (termux: pkg install termux-api)")
        elif choice == "5":
            util.rule("sing-box JSON")
            print(json.dumps(configs.singbox_config(cfgs), indent=2, ensure_ascii=False))
        elif choice == "6":
            util.rule("Clash YAML")
            print(configs.clash_config(cfgs))
        elif choice == "7":
            path = util.ask("File path", os.path.join(util.base_dir(), "openpath-configs.json"))
            util.write_text(path, json.dumps([configs.normalize(c) for c in cfgs], indent=2, ensure_ascii=False), mode=0o644)
            util.ok(f"saved: {path}")
        else:
            util.err("unknown option")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_panel(args: argparse.Namespace) -> int:
    port = int(args.port or 0)
    httpd, real_port, url = bridge_mod.start(host=args.host, port=port, open_browser=not args.no_open)
    util.rule("OpenPath panel")
    util.ok(f"panel URL : {util.bold(url)}")
    util.ok(f"code      : {util.bold(bridge_mod.STATE.code)}")
    print()
    print("  Open the URL above in the phone browser. The page you get is the same")
    print("  panel that lives on GitHub Pages, but this copy is served from your own")
    print("  device, so it can talk to Cloudflare, start proxies and run tests.")
    print()
    print(f"  GitHub Pages (standalone, no bridge):")
    print("      https://arminabdim.github.io/Vpn-panel-for-iran-internet/")
    print()
    print("  " + util.dim("Ctrl+C to stop the panel."))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        util.info("stopped")
    return 0


def cmd_cf(args: argparse.Namespace) -> int:
    if args.cf_cmd == "token":
        cf_mod.set_token(args.token)
        util.ok("Cloudflare token saved")
        return 0
    if args.cf_cmd == "list":
        for d in cf_mod.deployments():
            print(f"  - {d.get('script')}  {d.get('url')}  ({d.get('created')})")
        return 0
    if args.cf_cmd == "accounts":
        for a in cf_mod.accounts():
            print(f"  {a['id']}  {a.get('name')}")
        return 0
    if args.cf_cmd == "code":
        settings = cf_mod.default_settings(args.name)
        path = args.out or os.path.join(util.base_dir(), "worker.js")
        util.write_text(path, cf_mod.render_worker(settings), mode=0o644)
        util.ok(f"worker written to {path}")
        util.info("Deploy it: Workers & Pages -> Create Worker -> paste, or `openpath cf deploy`")
        return 0
    if args.cf_cmd == "delete":
        ok = cf_mod.delete_worker(args.script)
        util.ok("deleted") if ok else util.err("delete failed")
        return 0
    if args.cf_cmd == "deploy":
        if args.token:
            cf_mod.set_token(args.token)
        if not cf_mod.token():
            util.rule("Cloudflare API token")
            print("  Create one here (free account):")
            print("  https://dash.cloudflare.com/profile/api-tokens -> Create Custom Token")
            print("    Permissions:  Account / Workers Scripts / Edit")
            print("                  Account / Account Settings / Read")
            print()
            tok = util.ask("Paste your API token", secret=True)
            if not tok:
                util.err("a token is required for automatic deployment")
                return 1
            cf_mod.set_token(tok)

        settings = cf_mod.default_settings(args.name or "OpenPath")
        if args.uuid:
            settings["uuid"] = args.uuid
        if args.path:
            settings["ws_path"] = args.path if args.path.startswith("/") else "/" + args.path
        if args.no_trojan:
            settings["trojan_password"] = ""
        script_name = args.script or f"openpath-{util.rand_hex(3)}"
        util.step(f"deploying worker '{script_name}' ...")
        try:
            script = cf_mod.render_worker(settings)
            info = cf_mod.deploy(script_name, script, args.account)
        except Exception as exc:
            util.err(str(exc))
            return 1
        cf_mod.save_deployment(info, settings)
        host = (info.get("url") or "").replace("https://", "").replace("http://", "").strip("/")
        if not host:
            util.warn("deployed, but Cloudflare did not return a URL - check the dashboard")
            return 1
        cfgs = cf_mod.worker_configs(host, settings, clean_ip=args.clean_ip or "")
        sub_url = cf_mod.subscription_url(host, settings["sub_path"])
        util.ok(f"worker URL   : https://{host}")
        util.ok(f"subscription : {sub_url}")
        print()
        _print_configs(cfgs, "Your free nodes")
        print("  " + util.bold("Import the subscription URL into MahsaNG / v2rayNG."))
        if args.qr or util.ask_yes("Show a QR code in the web panel instead of typing?", True):
            httpd, port, url = bridge_mod.start(port=0, open_browser=False)
            util.info(f"panel (with QR codes): {url}   code: {bridge_mod.STATE.code}")
        _offer_export(cfgs)
        return 0
    util.err(f"unknown cf command: {args.cf_cmd}")
    return 1


def cmd_warp(args: argparse.Namespace) -> int:
    if args.warp_cmd == "list":
        for c in warp_mod.load():
            print(f"  - {c['name']}  {c['server']}:{c['port']}")
        return 0
    if args.warp_cmd == "conf":
        profiles = warp_mod.load()
        idx = int(args.index or 1) - 1
        if not (0 <= idx < len(profiles)):
            util.err("no such profile")
            return 1
        print(warp_mod.conf(profiles[idx]))
        return 0
    # generate
    count = int(args.count or 1)
    util.step(f"registering {count} WARP account(s) ...")
    try:
        profiles = warp_mod.generate(license_key=args.license or "", count=count, verbose=True)
    except Exception as exc:
        util.err(str(exc))
        util.info("If your network blocks the WARP API, try again with the Worker or the Apps Script relay running.")
        return 1
    util.ok(f"{len(profiles)} profile(s) ready")
    for c in profiles:
        name = c["name"]
        path = os.path.join(util.base_dir(), f"{util.safe_name(name)}.conf")
        util.write_text(path, warp_mod.conf(c), mode=0o600)
        util.ok(f"{name}: {path}")
    print()
    print("  " + util.bold("Use it:"))
    print("    * MahsaNG / v2rayNG / Amnezia: import the .conf as a WireGuard profile")
    print("    * official app: 1.1.1.1 -> Settings -> Advanced -> Custom WireGuard")
    _offer_export(profiles)
    return 0


def cmd_gas(args: argparse.Namespace) -> int:
    if args.gas_cmd == "new":
        path, key = gas_mod.write_script()
        gas_mod.configure(key=key)
        print(gas_mod.deploy_instructions(path, key))
        util.ok(f"script written: {path}")
        return 0
    if args.gas_cmd == "url":
        gas_mod.configure(url=args.url)
        util.ok("relay URL saved")
        return 0
    if args.gas_cmd == "key":
        gas_mod.configure(key=args.key)
        util.ok("relay key saved")
        return 0
    if args.gas_cmd == "test":
        try:
            relay = gas_mod.Relay()
        except Exception as exc:
            util.err(str(exc))
            return 1
        ms = relay.ping()
        if ms is None:
            util.err("relay did not answer - check the URL, the key and the deployment")
            return 1
        util.ok(f"relay answered in {ms:.0f} ms")
        return 0
    if args.gas_cmd == "fetch":
        try:
            relay = gas_mod.Relay()
            _s, _h, body = relay.request("GET", args.url)
        except Exception as exc:
            util.err(str(exc))
            return 1
        sys.stdout.write(body.decode("utf-8", "replace"))
        return 0
    if args.gas_cmd == "ca":
        try:
            crt, _key = gas_mod.ensure_ca()
        except Exception as exc:
            util.err(str(exc))
            return 1
        util.ok(f"CA certificate: {crt}")
        print("  Android: Settings -> Security -> Encryption & credentials")
        print("           -> Install a certificate -> CA certificate")
        return 0
    if args.gas_cmd == "serve":
        if not gas_mod.config().get("gas_url") or not gas_mod.config().get("gas_key"):
            util.err("configure the relay first: openpath gas new  /  openpath gas url <URL>")
            return 1
        try:
            server = gas_mod.serve_forever(port=int(args.port), mitm=not args.no_mitm, verbose=args.verbose)
        except Exception as exc:
            util.err(str(exc))
            return 1
        util.rule("Apps Script relay proxy")
        util.ok(f"HTTP + SOCKS5 proxy on 127.0.0.1:{args.port}")
        print()
        print("  " + util.bold("How to use it on Android:"))
        print(f"    1) Wi-Fi settings -> modify network -> Proxy: Manual")
        print(f"       hostname 127.0.0.1   port {args.port}")
        print("    2) For HTTPS: install the local CA once")
        print("         Settings -> Security -> Install certificates -> CA certificate")
        print(f"         file: {gas_mod.ca_cert_path()}")
        print("    3) Apps that support their own proxy (Telegram, browsers):")
        print(f"       set SOCKS5/HTTP to 127.0.0.1:{args.port}")
        print()
        print("  " + util.dim("Ctrl+C to stop."))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
            util.info("stopped")
        return 0
    util.err(f"unknown gas command: {args.gas_cmd}")
    return 1


def cmd_dpi(args: argparse.Namespace) -> int:
    if args.dpi_cmd == "install":
        try:
            if args.tool == "spoofdpi":
                path = dpi_mod.install_spoofdpi(force=bool(args.force))
            else:
                path = dpi_mod.install_byedpi(force=bool(args.force))
        except Exception as exc:
            util.err(str(exc))
            return 1
        util.ok(f"installed: {path}")
        return 0
    if args.dpi_cmd == "start":
        if args.engine == "builtin":
            proxy = dpi_mod.start(
                port=int(args.port), chunks=int(args.chunks), delay=float(args.delay), fake=not args.no_fake, verbose=args.verbose
            )
            util.rule("DPI bypass proxy (built-in)")
            util.ok(f"HTTP + SOCKS5 proxy on 127.0.0.1:{args.port}")
            print(f"  segments={args.chunks}  decoy={not args.no_fake}  delay={args.delay}s")
            print()
            print("  Point v2rayNG / MahsaNG / your browser at it:")
            print(f"    Settings -> proxy / upstream -> HTTP or SOCKS5 -> 127.0.0.1:{args.port}")
            print()
            print("  " + util.dim("Ctrl+C to stop."))
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                proxy.stop()
                util.info("stopped")
            return 0
        try:
            if args.engine == "spoofdpi":
                proc = dpi_mod.run_spoofdpi(port=int(args.port))
            else:
                proc = dpi_mod.run_byedpi(port=int(args.port))
        except Exception as exc:
            util.err(str(exc))
            return 1
        util.ok(f"{args.engine} running on 127.0.0.1:{args.port} (pid {proc.pid})")
        print("  " + util.dim("Ctrl+C to stop."))
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            util.info("stopped")
        return 0
    util.err(f"unknown dpi command: {args.dpi_cmd}")
    return 1


def cmd_sub(args: argparse.Namespace) -> int:
    if args.sub_cmd == "sources":
        for s in sub_mod.sources():
            print(f"  {util.bold(s['id']):<20} {s['name']}")
            print(f"  {'':<20} {util.dim(s['url'])}")
        return 0
    if args.sub_cmd == "show":
        _print_configs(sub_mod.load(), "Saved configs")
        return 0
    if args.sub_cmd == "export":
        cfgs = sub_mod.load()
        if not cfgs:
            util.err("nothing saved yet - run: openpath sub fetch")
            return 1
        print(sub_mod.export(cfgs, args.format, args.mode))
        return 0
    if args.sub_cmd == "serve":
        cfgs = sub_mod.load()
        if not cfgs:
            util.err("nothing saved yet - run: openpath sub fetch")
            return 1
        httpd, port = sub_mod.serve(cfgs, host="0.0.0.0", port=int(args.port), mode=args.mode)
        util.ok(f"subscription served on http://127.0.0.1:{port}/sub")
        print(f"  LAN (other devices): http://<phone-ip>:{port}/sub")
        print(f"  formats: /sub?format=b64|text|clash|singbox|xray")
        print("  " + util.dim("Ctrl+C to stop."))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0
    if args.sub_cmd == "fetch":
        util.rule("Collecting public configs")
        util.warn("Public configs belong to strangers: they can see your traffic. Use them only when you must.")
        ids = args.sources.split(",") if args.sources else None
        if ids is None and not args.yes:
            print("  Available sources:")
            for s in sub_mod.sources():
                print(f"    - {s['id']:<18} {s['name']}")
            raw = util.ask("Comma separated ids (empty = all)", "")
            ids = [x.strip() for x in raw.split(",") if x.strip()] or None
        cfgs, report = sub_mod.collect(source_ids=ids, extra_urls=args.url.split(",") if args.url else None, limit_per_source=int(args.limit))
        cfgs = sub_mod.rename(cfgs)
        sub_mod.save(cfgs)
        util.ok(f"{len(cfgs)} unique configs saved")
        if args.test:
            util.step("testing reachability (this takes a few seconds) ...")
            results = net_mod.test_many(cfgs[:60])
            print(net_mod.format_table(results[:30]))
        _offer_export(cfgs)
        return 0
    util.err(f"unknown sub command: {args.sub_cmd}")
    return 1


def cmd_paas(args: argparse.Namespace) -> int:
    if args.paas_cmd == "presets":
        for key, value in paas_mod.PRESETS.items():
            print(f"  {util.bold(key):<14} {value['label']}")
        return 0
    if args.paas_cmd == "render-key":
        util.set_key("render_key", args.key)
        util.ok("Render API key saved")
        return 0
    if args.paas_cmd == "render":
        util.step("creating a Render service (this takes a few minutes) ...")
        try:
            result = paas_mod.render_deploy(
                name=args.name, repo=args.repo, branch=args.branch, region=args.region, preset=args.preset
            )
        except Exception as exc:
            util.err(str(exc))
            return 1
        util.ok(f"service: {result.get('url')}")
        settings = result["settings"]
        host = (result.get("url") or "").replace("https://", "").strip("/")
        cfgs = [paas_mod.config_for(settings, host, 443)]
        _print_configs(cfgs, "Your container node")
        _offer_export(cfgs)
        return 0
    if args.paas_cmd == "codespace":
        try:
            result = paas_mod.codespace_deploy(repo=args.repo, preset=args.preset, ref=args.ref, name=args.name)
        except Exception as exc:
            util.err(str(exc))
            return 1
        if not result.get("tunnel_url"):
            util.warn("codespace is up but the tunnel URL did not appear yet; check the repo's tunnels/ folder in a minute")
            return 1
        util.ok(f"tunnel: {result['tunnel_url']}")
        if result.get("config"):
            _offer_export([result["config"]])
        return 0
    util.err(f"unknown paas command: {args.paas_cmd}")
    return 1


def cmd_make(args: argparse.Namespace) -> int:
    if getattr(args, "link", None):
        cfgs = list(configs.parse_any(args.link))
        if not cfgs:
            util.err("could not understand that link")
            return 1
        util.rule(f"Re-export ({len(cfgs)} config(s))")
        if getattr(args, "fragment", False):
            for cfg in cfgs:
                cfg["fragment"] = True
        _print_configs(cfgs, "Imported")
        _offer_export(cfgs)
        return 0
    util.rule("Build a config")
    proto = util.ask_choice(
        "Protocol",
        [("vless", "VLESS (recommended)"), ("trojan", "Trojan"), ("vmess", "VMess"),
         ("ss", "Shadowsocks"), ("hysteria2", "Hysteria2 (UDP)"), ("tuic", "TUIC v5 (UDP)"),
         ("wireguard", "WireGuard / WARP")],
        "1",
    )
    cfg: Dict[str, Any] = {"proto": proto}
    cfg["name"] = util.ask("Node name", "OpenPath")
    cfg["server"] = util.ask("Server / host", args.host or "")
    cfg["port"] = int(util.ask("Port", "443") or 443)
    if proto in ("vless", "vmess", "tuic"):
        cfg["uuid"] = util.ask("UUID (empty = random)", "") or configs.new_uuid()
    if proto in ("trojan", "ss", "hysteria2", "tuic"):
        cfg["password"] = util.ask("Password (empty = random)", "") or configs.rand_password()
    if proto == "ss":
        cfg["method"] = util.ask("Method", "chacha20-ietf-poly1305")
    if proto == "wireguard":
        cfg["wg_private_key"] = util.ask("Your private key", "")
        cfg["wg_public_key"] = util.ask("Peer public key", "")
        cfg["wg_local_address"] = util.ask("Local address", "172.16.0.2/32")
    else:
        cfg["network"] = util.ask_choice(
            "Transport", [("ws", "WebSocket"), ("tcp", "TCP/raw"), ("grpc", "gRPC"), ("xhttp", "XHTTP"), ("httpupgrade", "HTTPUpgrade")], "1"
        )
        cfg["security"] = util.ask_choice("TLS", [("tls", "TLS on"), ("none", "TLS off (port 80)"), ("reality", "REALITY")], "1")
        if cfg["security"] != "none":
            cfg["sni"] = util.ask("SNI", cfg["server"])
            cfg["fp"] = util.ask("TLS fingerprint", "chrome")
        if cfg["network"] in ("ws", "xhttp", "httpupgrade"):
            cfg["path"] = util.ask("Path", "/openpath")
            cfg["host"] = util.ask("Host header", cfg["server"])
        if cfg["network"] == "grpc":
            cfg["serviceName"] = util.ask("gRPC service name", "GunService")
        if args.fragment:
            cfg["fragment"] = True
    cfg = configs.normalize(cfg)
    uri = configs.to_uri(cfg)
    util.rule("Result")
    print(uri)
    print()
    _offer_export([cfg])
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    if args.link:
        cfgs = [c for c in configs.parse_any(args.link)]
    elif args.file:
        cfgs = configs.parse_any(util.read_text(args.file))
    else:
        cfgs = sub_mod.load()
    if not cfgs:
        util.err("nothing to test (use --link, --file or `openpath sub fetch`)")
        return 1
    util.step(f"testing {len(cfgs)} config(s) ...")
    results = net_mod.test_many(cfgs, timeout=float(args.timeout))
    print()
    print(net_mod.format_table(results))
    alive = [r for r in results if r.get("tcping")]
    util.ok(f"{len(alive)}/{len(results)} reachable")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    util.rule("Environment")
    checks = [
        ("python >= 3.8", sys.version_info >= (3, 8), ".".join(str(x) for x in sys.version_info[:3])),
        ("Termux detected", util.is_termux(), os.environ.get("PREFIX", "-")),
        ("architecture", True, util.arch()),
        ("openssl (MITM / certs)", bool(shutil.which("openssl")), "pkg install openssl"),
        ("git", bool(shutil.which("git")), "pkg install git"),
        ("gh CLI (codespaces)", bool(shutil.which("gh")), "pkg install gh"),
        ("qrcode module (terminal QR)", _has_qrcode(), "pip install qrcode"),
        ("persian terminal support", util.persian_supported(), "pip install arabic-reshaper python-bidi"),
    ]
    for label, ok, extra in checks:
        print(f"  {'OK  ' if ok else '--  '} {label:<28} {util.dim(str(extra))}")
    print()
    util.step("network reachability")
    targets = [
        ("Cloudflare API", "https://api.cloudflare.com/client/v4/ips"),
        ("GitHub", "https://api.github.com/zen"),
        ("Google Apps Script", "https://script.google.com"),
        ("WARP register API", f"https://{warp_mod.API_HOST}/{warp_mod.API_VERSIONS[0]}/reg"),
    ]
    for label, url in targets:
        ms = util.http_ping(url, timeout=8)
        status = f"{ms:.0f} ms" if ms else "unreachable/blocked"
        print(f"  {'OK  ' if ms else 'FAIL'} {label:<28} {status}")
    print()
    ip = util.public_ip()
    print(f"  public IP: {ip or 'unknown'}")
    return 0


def _has_qrcode() -> bool:
    try:
        import qrcode  # type: ignore

        return True
    except Exception:
        return False


def cmd_qr(args: argparse.Namespace) -> int:
    text = args.link or (configs.subscription(sub_mod.load()) if args.subs else "")
    if not text:
        util.err("nothing to encode")
        return 1
    if not _has_qrcode():
        util.warn("install `pip install qrcode` for terminal QR codes, or use the web panel")
        print(text)
        return 1
    import qrcode  # type: ignore

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    passed, failed, lines = run_selftest()
    for line in lines:
        print(("  " + line) if not line.startswith("PASS") else "  " + util.green(line))
    print()
    print(f"  {util.bold(str(passed))} passed, {failed} failed")
    return 0 if failed == 0 else 1


def cmd_help(_args: argparse.Namespace) -> int:
    """Short command reference. `openpath guide` prints the long version."""
    print(BANNER)
    print()
    print("  " + util.bold("usage:") + "  openpath <command> [options]     (no command = interactive menu)")
    print()
    rows = [
        ("panel", "open the panel in your browser (--port, --host, --no-open)"),
        ("cf deploy", "build + deploy your own Cloudflare Worker node"),
        ("cf token", "save a Cloudflare API token"),
        ("cf list / code / delete", "list workers, print the code, delete one"),
        ("warp new", "generate free WireGuard (WARP) configs"),
        ("gas new", "print the Google Apps Script relay"),
        ("gas serve / test / fetch", "run / test / use the relay locally"),
        ("dpi start", "local DPI bypass on 127.0.0.1:8081 (--port, --chunks)"),
        ("sub fetch", "collect public configs, test them, keep the fast ones"),
        ("sub export / serve", "re-export for any client / share on the LAN"),
        ("paas presets", "show the container presets"),
        ("paas render / codespace", "build a free UDP node (Hysteria2, TUIC, ...)"),
        ("make", "build one config by hand (--link re-exports an existing one)"),
        ("test", "latency test (--link, --file, or your saved configs)"),
        ("qr", "print a config or link as a terminal QR code"),
        ("doctor", "what works on this device and network right now"),
        ("selftest", "run the offline checks (no network needed)"),
        ("guide", "print the plain-language guide (GUIDE.md)"),
    ]
    for name, what in rows:
        print(f"  {util.bold(name):<28} {what}")
    print()
    print("  " + util.dim("examples:"))
    print("    openpath cf token <TOKEN> && openpath cf deploy        # your own node")
    print("    openpath warp new --count 3                            # 3 WARP configs")
    print("    openpath sub fetch && openpath sub export --format singbox")
    print("    openpath make --link 'vless://...'                     # convert one link")
    print("    openpath dpi start --chunks 3                          # bypass filtering")
    print()
    print("  " + util.dim("docs: GUIDE.md (guide for everyone), docs/METHODS.md (all 18 methods),"))
    print("  " + util.dim("      docs/TROUBLESHOOTING.md, docs/TERMUX.md, README_FA.md (Persian)"))
    print()
    return 0


def cmd_guide(_args: argparse.Namespace) -> int:
    """Print the long plain-language guide."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("GUIDE.md", "README.md"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            print(util.read_text(path))
            return 0
    util.err("guide not found in the repository")
    return 1


def interactive() -> int:
    print(util.cyan(BANNER))
    print("  " + util.dim("free internet for Iran - no server, no subscription, no card"))
    print()
    if util.persian_supported():
        print("  " + util.shape("دسترسی آزاد به اینترنت، بدون سرور و بدون هزینه"))
        print()
    while True:
        util.rule("Main menu")
        for i, (key, label) in enumerate(MENU, 1):
            print(f"  {util.bold(str(i)):>2}) {label}")
        print(f"  {util.bold(' 0')}) exit")
        choice = util.ask("Choose", "1")
        if choice in ("0", "q", "exit"):
            return 0
        try:
            idx = int(choice)
            key = MENU[idx - 1][0]
        except Exception:
            util.err("invalid choice")
            continue
        if key == "panel":
            cmd_panel(argparse.Namespace(port=0, host="127.0.0.1", no_open=False))
        elif key == "cf":
            cmd_cf(argparse.Namespace(cf_cmd="deploy", token=None, name="OpenPath", uuid=None, path=None,
                                      no_trojan=False, script=None, account=None, clean_ip=None, qr=False))
        elif key == "warp":
            cmd_warp(argparse.Namespace(warp_cmd="new", count=1, license=None, index=None))
        elif key == "gas":
            cfg = gas_mod.config()
            if not cfg.get("gas_url"):
                cmd_gas(argparse.Namespace(gas_cmd="new"))
            else:
                cmd_gas(argparse.Namespace(gas_cmd="serve", port=8080, no_mitm=False, verbose=False))
        elif key == "dpi":
            cmd_dpi(argparse.Namespace(dpi_cmd="start", engine="builtin", port=8081, chunks=3, delay=0.012,
                                       no_fake=False, verbose=False, tool=None, force=False))
        elif key == "sub":
            cmd_sub(argparse.Namespace(sub_cmd="fetch", sources=None, url=None, limit=40, yes=False, test=True,
                                       format="b64", mode="global", port=0))
        elif key == "paas":
            cmd_paas(argparse.Namespace(paas_cmd="presets"))
        elif key == "make":
            cmd_make(argparse.Namespace(host=None, fragment=False))
        elif key == "test":
            cmd_test(argparse.Namespace(link=None, file=None, timeout=4))
        elif key == "doctor":
            cmd_doctor(None)
        elif key == "selftest":
            cmd_selftest(None)
        elif key == "help":
            cmd_help(None)


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openpath", description="OpenPath - free internet without a server")
    sub = parser.add_subparsers(dest="command")

    p_panel = sub.add_parser("panel", help="start the local web panel")
    p_panel.add_argument("--port", default=0)
    p_panel.add_argument("--host", default="127.0.0.1")
    p_panel.add_argument("--no-open", action="store_true")
    p_panel.set_defaults(func=cmd_panel)

    p_cf = sub.add_parser("cf", help="Cloudflare Worker nodes")
    cf_sub = p_cf.add_subparsers(dest="cf_cmd")
    d = cf_sub.add_parser("deploy")
    d.add_argument("--token"), d.add_argument("--name", default="OpenPath"), d.add_argument("--uuid")
    d.add_argument("--path"), d.add_argument("--script"), d.add_argument("--account")
    d.add_argument("--clean-ip"), d.add_argument("--no-trojan", action="store_true"), d.add_argument("--qr", action="store_true")
    d.set_defaults(func=cmd_cf, cf_cmd="deploy")
    t = cf_sub.add_parser("token")
    t.add_argument("token")
    t.set_defaults(func=cmd_cf, cf_cmd="token")
    cf_sub.add_parser("list").set_defaults(func=cmd_cf, cf_cmd="list")
    cf_sub.add_parser("accounts").set_defaults(func=cmd_cf, cf_cmd="accounts")
    c = cf_sub.add_parser("code")
    c.add_argument("--name", default="OpenPath")
    c.add_argument("--out")
    c.set_defaults(func=cmd_cf, cf_cmd="code")
    x = cf_sub.add_parser("delete")
    x.add_argument("script")
    x.set_defaults(func=cmd_cf, cf_cmd="delete")

    p_warp = sub.add_parser("warp", help="Cloudflare WARP")
    warp_sub = p_warp.add_subparsers(dest="warp_cmd")
    w = warp_sub.add_parser("new")
    w.add_argument("--count", default=1)
    w.add_argument("--license", default="")
    w.set_defaults(func=cmd_warp, warp_cmd="new")
    warp_sub.add_parser("list").set_defaults(func=cmd_warp, warp_cmd="list")
    wc = warp_sub.add_parser("conf")
    wc.add_argument("--index", default=1)
    wc.set_defaults(func=cmd_warp, warp_cmd="conf")

    p_gas = sub.add_parser("gas", help="Google Apps Script relay")
    gas_sub = p_gas.add_subparsers(dest="gas_cmd")
    gas_sub.add_parser("new").set_defaults(func=cmd_gas, gas_cmd="new")
    gu = gas_sub.add_parser("url")
    gu.add_argument("url")
    gu.set_defaults(func=cmd_gas, gas_cmd="url")
    gk = gas_sub.add_parser("key")
    gk.add_argument("key")
    gk.set_defaults(func=cmd_gas, gas_cmd="key")
    gas_sub.add_parser("test").set_defaults(func=cmd_gas, gas_cmd="test")
    gs = gas_sub.add_parser("serve")
    gs.add_argument("--port", default=8080)
    gs.add_argument("--no-mitm", action="store_true")
    gs.add_argument("--verbose", action="store_true")
    gs.set_defaults(func=cmd_gas, gas_cmd="serve")
    gf = gas_sub.add_parser("fetch")
    gf.add_argument("url")
    gf.set_defaults(func=cmd_gas, gas_cmd="fetch")
    gas_sub.add_parser("ca").set_defaults(func=cmd_gas, gas_cmd="ca")

    p_dpi = sub.add_parser("dpi", help="local DPI bypass")
    dpi_sub = p_dpi.add_subparsers(dest="dpi_cmd")
    ds = dpi_sub.add_parser("start")
    ds.add_argument("--engine", default="builtin", choices=["builtin", "spoofdpi", "byedpi"])
    ds.add_argument("--port", default=8081)
    ds.add_argument("--chunks", default=3)
    ds.add_argument("--delay", default=0.012)
    ds.add_argument("--no-fake", action="store_true")
    ds.add_argument("--verbose", action="store_true")
    ds.set_defaults(func=cmd_dpi, dpi_cmd="start")
    di = dpi_sub.add_parser("install")
    di.add_argument("tool", choices=["spoofdpi", "byedpi"])
    di.add_argument("--force", action="store_true")
    di.set_defaults(func=cmd_dpi, dpi_cmd="install")

    p_sub = sub.add_parser("sub", help="public subscriptions")
    sub_sub = p_sub.add_subparsers(dest="sub_cmd")
    sub_sub.add_parser("sources").set_defaults(func=cmd_sub, sub_cmd="sources")
    sub_sub.add_parser("show").set_defaults(func=cmd_sub, sub_cmd="show")
    sf = sub_sub.add_parser("fetch")
    sf.add_argument("--sources"), sf.add_argument("--url"), sf.add_argument("--limit", default=40)
    sf.add_argument("--yes", action="store_true"), sf.add_argument("--test", action="store_true")
    sf.set_defaults(func=cmd_sub, sub_cmd="fetch")
    se = sub_sub.add_parser("export")
    se.add_argument("--format", default="b64"), se.add_argument("--mode", default="global")
    se.set_defaults(func=cmd_sub, sub_cmd="export")
    ss = sub_sub.add_parser("serve")
    ss.add_argument("--port", default=0), ss.add_argument("--mode", default="global")
    ss.set_defaults(func=cmd_sub, sub_cmd="serve")

    p_paas = sub.add_parser("paas", help="free containers")
    paas_sub = p_paas.add_subparsers(dest="paas_cmd")
    paas_sub.add_parser("presets").set_defaults(func=cmd_paas, paas_cmd="presets")
    pr = paas_sub.add_parser("render")
    pr.add_argument("--repo", required=True), pr.add_argument("--name", default="openpath")
    pr.add_argument("--branch", default="main"), pr.add_argument("--region", default="frankfurt")
    pr.add_argument("--preset", default="vless-ws")
    pr.set_defaults(func=cmd_paas, paas_cmd="render")
    pk = paas_sub.add_parser("render-key")
    pk.add_argument("key")
    pk.set_defaults(func=cmd_paas, paas_cmd="render-key")
    pc = paas_sub.add_parser("codespace")
    pc.add_argument("--repo", required=True), pc.add_argument("--preset", default="vless-ws")
    pc.add_argument("--ref", default="main"), pc.add_argument("--name", default="OpenPath")
    pc.set_defaults(func=cmd_paas, paas_cmd="codespace")

    p_make = sub.add_parser("make", help="build a config by hand")
    p_make.add_argument("--host"), p_make.add_argument("--fragment", action="store_true")
    p_make.add_argument("--link", help="re-export an existing link instead of answering questions")
    p_make.set_defaults(func=cmd_make)

    p_test = sub.add_parser("test", help="latency test")
    p_test.add_argument("--link"), p_test.add_argument("--file"), p_test.add_argument("--timeout", default=4)
    p_test.set_defaults(func=cmd_test)

    p_qr = sub.add_parser("qr", help="terminal QR code")
    p_qr.add_argument("--link"), p_qr.add_argument("--subs", action="store_true")
    p_qr.set_defaults(func=cmd_qr)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    sub.add_parser("help").set_defaults(func=cmd_help)
    sub.add_parser("guide").set_defaults(func=cmd_guide)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        return interactive()
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print()
        util.info("cancelled")
        return 130
