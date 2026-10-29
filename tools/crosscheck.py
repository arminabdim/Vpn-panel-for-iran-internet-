#!/usr/bin/env python3
"""
Cross-check the Python engine against the JavaScript engine.

Both must produce byte-identical output - the Termux CLI and the web panel are
two front ends for the same brain, and a silent drift between them is exactly
the kind of bug that ruins a config at the worst possible moment.

    python3 tools/crosscheck.py        (needs node)
"""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from openpath.core import configs  # noqa: E402

SAMPLES = [
    {"proto": "vless", "name": "CF-443", "server": "openpath-demo.workers.dev", "port": 443,
     "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f", "network": "ws", "security": "tls",
     "sni": "openpath-demo.workers.dev", "host": "openpath-demo.workers.dev", "path": "/walk", "fp": "chrome"},
    {"proto": "vless", "name": "CF-80", "server": "openpath-demo.workers.dev", "port": 80,
     "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f", "network": "ws", "security": "none", "path": "/walk"},
    {"proto": "trojan", "name": "TR", "server": "node.example.com", "port": 443,
     "password": "Str0ngPass", "network": "ws", "security": "tls", "path": "/tp"},
    {"proto": "vmess", "name": "VM", "server": "vm.example.com", "port": 8443,
     "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f", "network": "ws", "path": "/vm", "security": "tls"},
    {"proto": "ss", "name": "SS", "server": "ss.example.com", "port": 8388,
     "password": "p@ssw0rd2", "method": "2022-blake3-chacha20-poly1305"},
    {"proto": "hysteria2", "name": "HY2", "server": "hy2.example.com", "port": 8443,
     "password": "hy2pass", "obfs": "salamander", "obfs_password": "sal-pass", "insecure": True},
    {"proto": "tuic", "name": "TUIC", "server": "tuic.example.com", "port": 8443,
     "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f", "password": "tuicpass"},
    {"proto": "wireguard", "name": "WARP", "server": "engage.cloudflareclient.com", "port": 2408,
     "wg_private_key": "cE2XhN7k1bKp3HfM1sT0uGvHk7WQvYs1mGkQdJdJdJd=",
     "wg_public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=", "wg_reserved": "109,23,8"},
    {"proto": "vless", "name": "Real", "server": "r.example.com", "port": 443,
     "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f", "network": "xhttp", "security": "reality",
     "sni": "www.microsoft.com", "pbk": "abc", "sid": "0123abcd", "fp": "firefox", "path": "/x", "mode": "stream-one"},
    {"proto": "vless", "name": "Frag", "server": "f.example.com", "port": 443,
     "uuid": "b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f", "network": "ws", "security": "tls",
     "sni": "f.example.com", "path": "/f", "fragment": True, "record_fragment": True},
]


def main() -> int:
    cfgs = [configs.normalize(s) for s in SAMPLES]
    py = {
        "links": [configs.to_uri(c) for c in cfgs],
        "singbox": configs.singbox_config(cfgs),
        "xray": configs.xray_config(cfgs),
        "clash": configs.clash_config(cfgs),
        "sub": configs.subscription(cfgs),
    }
    script = """
const fs=require('fs');
eval(fs.readFileSync(process.argv[1],'utf8'));
const E=globalThis.Engine;
const cfgs=JSON.parse(process.argv[2]).map(E.normalize);
console.log(JSON.stringify({
  links:cfgs.map(E.toUri),
  singbox:E.singboxConfig(cfgs,'global',2080),
  xray:E.xrayConfig(cfgs,'global',10808),
  clash:E.clashConfig(cfgs,'global',7890),
  sub:E.subscription(cfgs)
}));
"""
    engine_path = os.path.join(ROOT, "panel", "assets", "js", "engine.js")
    proc = subprocess.run(
        ["node", "-e", script, engine_path, json.dumps(cfgs)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if proc.returncode != 0:
        print("node failed:", proc.stderr[:400])
        return 2
    js = json.loads(proc.stdout)

    def dump(obj):
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))

    problems = 0
    for i, (a, b) in enumerate(zip(py["links"], js["links"])):
        if a != b:
            problems += 1
            print(f"share link #{i} differs\n  py: {a}\n  js: {b}")
    for key in ("singbox", "xray"):
        if dump(py[key]) != dump(js[key]):
            problems += 1
            print(f"{key} config differs")
            a, b = dump(py[key]), dump(js[key])
            for pos, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"  py ...{a[max(0, pos - 60):pos + 80]}")
                    print(f"  js ...{b[max(0, pos - 60):pos + 80]}")
                    break
            else:
                print("  (length differs)", len(a), len(b))
    if py["clash"].strip() != js["clash"].strip():
        problems += 1
        print("clash yaml differs")
        for line in list(difflib.unified_diff(py["clash"].splitlines(), js["clash"].splitlines(), lineterm=""))[:20]:
            print("  " + line)
    if py["sub"] != js["sub"]:
        problems += 1
        print("subscription text differs")

    total = len(SAMPLES) * 5
    if problems:
        print(f"\nFAILED: {problems} difference(s)")
        return 1
    print(f"cross-check OK: python and javascript engines agree on {total} outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
