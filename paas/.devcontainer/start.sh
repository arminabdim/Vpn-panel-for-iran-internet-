#!/usr/bin/env bash
# Runs after the codespace starts: install sing-box, generate a config and
# publish the Cloudflare quick tunnel URL back into the repository, so
# `openpath paas codespace` can find it.
set -euo pipefail
cd "${WORKSPACE_FOLDER:-/workspaces/$(basename "$PWD")}" 2>/dev/null || true
export OPENPATH_TUNNEL=1
export OPENPATH_PRESET="${OPENPATH_PRESET:-vless-ws}"
export OPENPATH_PORT="${OPENPATH_PORT:-443}"
export OPENPATH_UUID="${OPENPATH_UUID:-$(cat /proc/sys/kernel/random/uuid)}"
export OPENPATH_PASSWORD="${OPENPATH_PASSWORD:-$(head -c 12 /dev/urandom | base64 | tr -d '/+=' | head -c 12)}"
export OPENPATH_PATH="${OPENPATH_PATH:-/openpath}"
mkdir -p /tmp/openpath && cp -r "$(dirname "$0")/.." /tmp/openpath/paas 2>/dev/null || true
bash /tmp/openpath/paas/entrypoint.sh
