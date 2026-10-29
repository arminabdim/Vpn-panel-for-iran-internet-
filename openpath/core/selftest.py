"""
Offline self test. Everything here runs without network access so it is safe to
execute on a phone right after installing:

    openpath selftest
"""

from __future__ import annotations

import base64
import json
import struct
from typing import Any, Dict, List, Tuple

from . import cf as cf_mod
from . import configs, dpi as dpi_mod, gas as gas_mod, util
from . import warp as warp_mod


def _check(results: List[str], name: str, condition: bool, detail: str = "") -> bool:
    results.append(("PASS" if condition else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not condition else ""))
    return condition


def run_selftest() -> Tuple[int, int, List[str]]:
    results: List[str] = []
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if _check(results, name, condition, detail):
            passed += 1
        else:
            failed += 1

    # ------------------------------------------------------------------ #
    # 1. canonical model + link round-trip
    # ------------------------------------------------------------------ #
    samples: List[Dict[str, Any]] = [
        {
            "proto": "vless",
            "name": "CF-443",
            "server": "openpath-demo.workers.dev",
            "port": 443,
            "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f",
            "network": "ws",
            "security": "tls",
            "sni": "openpath-demo.workers.dev",
            "host": "openpath-demo.workers.dev",
            "path": "/walk",
            "fp": "chrome",
        },
        {
            "proto": "trojan",
            "name": "TR",
            "server": "node.example.com",
            "port": 443,
            "password": "Str0ngPass",
            "network": "ws",
            "security": "tls",
            "path": "/tp",
        },
        {
            "proto": "vmess",
            "name": "VM",
            "server": "vm.example.com",
            "port": 8443,
            "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f",
            "network": "ws",
            "path": "/vm",
            "security": "tls",
        },
        {
            "proto": "ss",
            "name": "SS",
            "server": "ss.example.com",
            "port": 8388,
            "password": "p@ssw0rd",
            "method": "2022-blake3-chacha20-poly1305",
        },
        {
            "proto": "hysteria2",
            "name": "HY2",
            "server": "hy2.example.com",
            "port": 8443,
            "password": "hy2pass",
            "obfs": "salamander",
            "obfs_password": "salamander-pass",
            "insecure": True,
        },
        {
            "proto": "tuic",
            "name": "TUIC",
            "server": "tuic.example.com",
            "port": 8443,
            "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f",
            "password": "tuicpass",
        },
        {
            "proto": "wireguard",
            "name": "WARP",
            "server": "engage.cloudflareclient.com",
            "port": 2408,
            "wg_private_key": "cE2XhN7k1bKp3HfM1sT0uGvHk7WQvYs1mGkQdJdJdJd=",
            "wg_public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
            "wg_reserved": "109,23,8",
        },
    ]

    for sample in samples:
        proto = sample["proto"]
        try:
            uri = configs.to_uri(sample)
        except Exception as exc:
            check(f"to_uri({proto})", False, str(exc))
            continue
        check(f"to_uri({proto}) starts with scheme", uri.startswith(proto + "://") or (proto == "ss" and uri.startswith("ss://")), uri[:40])
        parsed = configs.parse_uri(uri)
        check(f"parse_uri({proto}) round-trip", parsed is not None and parsed["server"] == sample["server"], str(parsed)[:120])
        if parsed:
            again = configs.to_uri(parsed)
            check(f"re-emit({proto}) stable", again == uri, f"{again[:80]} != {uri[:80]}")

    # ------------------------------------------------------------------ #
    # 2. exports
    # ------------------------------------------------------------------ #
    cfgs = [configs.normalize(s) for s in samples]
    try:
        sb = configs.singbox_config(cfgs)
        check("sing-box config has outbounds", len(sb["outbounds"]) >= len(cfgs) + 3)
        check("sing-box selector present", sb["outbounds"][0]["type"] == "selector")
        check("sing-box json serialisable", bool(json.dumps(sb)))
    except Exception as exc:
        check("sing-box config", False, str(exc))

    try:
        yaml_text = configs.clash_config(cfgs)
        check("clash yaml has proxies", "proxies:" in yaml_text and "proxy-groups:" in yaml_text)
    except Exception as exc:
        check("clash yaml", False, str(exc))

    try:
        xray = configs.xray_config(cfgs)
        check("xray json has outbounds", len(xray["outbounds"]) >= 4)
        check("xray json serialisable", bool(json.dumps(xray)))
    except Exception as exc:
        check("xray config", False, str(exc))

    try:
        frag = configs.xray_fragment_config()
        check("xray fragment settings", frag["outbounds"][0]["settings"]["fragment"]["packets"] == "tlshello")
    except Exception as exc:
        check("xray fragment config", False, str(exc))

    # fragment flag reaches the sing-box tls block
    try:
        frag_cfg = configs.normalize({**samples[0], "fragment": True})
        ob = configs.to_singbox_outbound(frag_cfg)
        check("sing-box tls fragment field", ob.get("tls", {}).get("fragment", {}).get("enabled") is True)
    except Exception as exc:
        check("sing-box fragment", False, str(exc))

    # ------------------------------------------------------------------ #
    # 3. subscriptions
    # ------------------------------------------------------------------ #
    text = configs.subscription(cfgs)
    check("subscription has one line per config", len(text.strip().splitlines()) == len(cfgs))
    decoded = configs.parse_any(base64.b64encode(text.encode()).decode())
    check("base64 subscription round-trip", len(decoded) == len(cfgs), f"{len(decoded)} != {len(cfgs)}")
    merged = configs.merge_configs(cfgs, cfgs)
    check("merge de-duplicates", len(merged) == len(cfgs))

    # ------------------------------------------------------------------ #
    # 4. worker template
    # ------------------------------------------------------------------ #
    try:
        settings = cf_mod.default_settings()
        src = cf_mod.render_worker(settings)
        check("worker renders without placeholders", "{{" not in src)
        check("worker embeds uuid", settings["uuid"] in src)
        check("worker has ws path", settings["ws_path"] in src)
    except Exception as exc:
        check("worker template", False, str(exc))

    # ------------------------------------------------------------------ #
    # 5. gas template
    # ------------------------------------------------------------------ #
    try:
        code, key = gas_mod.render_script("TESTKEY123")
        check("gas script has key", "TESTKEY123" in code and "{{" not in code)
    except Exception as exc:
        check("gas template", False, str(exc))

    # ------------------------------------------------------------------ #
    # 6. crypto
    # ------------------------------------------------------------------ #
    a = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
    check(
        "x25519 RFC7748 vector",
        warp_mod.x25519(warp_mod._clamp(a), bytes([9]) + bytes(31)).hex()
        == "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a",
    )
    priv, pub = warp_mod.generate_keypair()
    check("warp keypair length", len(base64.b64decode(priv)) == 32 and len(base64.b64decode(pub)) == 32)

    # ------------------------------------------------------------------ #
    # 7. DPI fragmentation keeps the bytes intact
    # ------------------------------------------------------------------ #
    payload = bytes(range(64))
    record = bytes([0x16, 0x03, 0x01]) + struct.pack(">H", len(payload)) + payload
    parts = dpi_mod.split_records(record, 4)
    joined = b"".join(parts)
    rebuilt = b""
    for part in parts:
        if part and part[0] == 0x16 and len(part) >= 5:
            ln = struct.unpack(">H", part[3:5])[0]
            rebuilt += part[5 : 5 + ln]
    check("tls split preserves payload", rebuilt == payload, f"{rebuilt.hex()[:40]} vs {payload.hex()[:40]}")
    check("tls split produces segments", len(parts) == 4)

    # ------------------------------------------------------------------ #
    # 8. wireguard text config
    # ------------------------------------------------------------------ #
    try:
        wg = configs.normalize(samples[-1])
        conf = configs.wireguard_conf(wg)
        check("wireguard conf has peer", "[Peer]" in conf and "engage.cloudflareclient.com" in conf)
        check("wireguard conf reserved", "Reserved = 109, 23, 8" in conf)
    except Exception as exc:
        check("wireguard conf", False, str(exc))

    # ------------------------------------------------------------------ #
    # 9. misc helpers
    # ------------------------------------------------------------------ #
    check("uuid format", len(configs.new_uuid()) == 36 and configs.new_uuid().count("-") == 4)
    check("safe_name", util.safe_name("my worker!") == "my-worker-")
    check("human_size", util.human_size(2048).endswith("KB"))
    check("is_ip", util.is_ip("1.1.1.1") and not util.is_ip("workers.dev"))

    return passed, failed, results
