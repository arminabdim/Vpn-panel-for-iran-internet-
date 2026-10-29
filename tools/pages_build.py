#!/usr/bin/env python3
"""Build the static GitHub Pages artifact for the panel.

GitHub Pages publishes one folder, but the panel needs two files that live
outside `panel/` — the Worker template and the Apps Script relay — so that
standalone mode can render them client-side. This copies them in as
`templates/`, which is exactly what `panel/assets/js/app.js` looks for.

    python3 tools/pages_build.py           # builds ./_site
    python3 tools/pages_build.py --out out

It also re-runs the "no external dependencies" check, so the published page can
never quietly start loading something from a third party.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATES = (
    ("worker/src/index.js", "templates/worker.js"),
    ("gas/Code.gs", "templates/Code.gs"),
)

SKIP = {".git", "__pycache__", "_site", ".DS_Store"}
REMOTE = re.compile(r'src="https?://|href="https?://[^"]*\.(css|js)|@import ')


def build(out: str) -> int:
    site = out if os.path.isabs(out) else os.path.join(ROOT, out)
    if os.path.isdir(site):
        shutil.rmtree(site)
    # copy the panel itself
    shutil.copytree(
        os.path.join(ROOT, "panel"), site,
        ignore=shutil.ignore_patterns(*SKIP),
    )
    # ship the templates next to it
    for src, dst in TEMPLATES:
        source = os.path.join(ROOT, src)
        if not os.path.exists(source):
            print(f"  MISSING {src}")
            return 1
        target = os.path.join(site, dst)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        print(f"  + {dst}  ({os.path.getsize(source)} bytes, from {src})")

    # every slot the panel fills must exist in the templates it ships
    worker = open(os.path.join(site, "templates", "worker.js"), encoding="utf-8").read()
    for slot in ("{{UUID}}", "{{SUB_PATH}}", "{{WS_PATH}}", "{{PROXY_IP}}"):
        if slot not in worker:
            print(f"  MISSING slot {slot} in the worker template")
            return 1
    gas = open(os.path.join(site, "templates", "Code.gs"), encoding="utf-8").read()
    if "{{AUTH_KEY}}" not in gas:
        print("  MISSING slot {{AUTH_KEY}} in the relay template")
        return 1

    # the panel must not depend on the network to render
    for dirpath, dirnames, filenames in os.walk(site):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            if not name.endswith((".html", ".css", ".js")):
                continue
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            hit = REMOTE.search(text)
            if hit:
                rel = os.path.relpath(path, site)
                print(f"  EXTERNAL DEPENDENCY in {rel}: {hit.group(0)}")
                return 1

    count = sum(len(f) for _, _, f in os.walk(site))
    print(f"  built {site} ({count} files) with no external dependencies")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="build the GitHub Pages artifact")
    ap.add_argument("--out", default="_site", help="output folder (default: _site)")
    args = ap.parse_args()
    return build(args.out)


if __name__ == "__main__":
    sys.exit(main())
