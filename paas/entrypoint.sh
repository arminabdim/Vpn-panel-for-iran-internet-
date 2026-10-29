#!/usr/bin/env bash
# OpenPath container entrypoint.
#
# Reads its whole configuration from the environment, writes a sing-box server
# config and starts it. Optionally publishes a Cloudflare quick tunnel
# (Codespaces mode) so a container with no public port is still reachable.
set -euo pipefail

PRESET="${OPENPATH_PRESET:-vless-ws}"
PORT="${OPENPATH_PORT:-${PORT:-443}}"
UUID="${OPENPATH_UUID:-}"
PASSWORD="${OPENPATH_PASSWORD:-}"
METHOD="${OPENPATH_METHOD:-2022-blake3-chacha20-poly1305}"
WSPATH="${OPENPATH_PATH:-/openpath}"
OBFS_PASS="${OPENPATH_OBFS_PASSWORD:-}"
NAME="${OPENPATH_NAME:-OpenPath}"
SNI="${OPENPATH_SNI:-}"
WORKDIR="/opt/openpath"
mkdir -p "$WORKDIR"

log() { printf '\033[36m[openpath]\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- install --
install_singbox() {
  if command -v sing-box >/dev/null 2>&1; then return; fi
  local arch
  case "$(uname -m)" in
    x86_64|amd64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    armv7l|armv6l) arch=armv7 ;;
    *) arch=amd64 ;;
  esac
  local version
  version=$(curl -fsSL "https://api.github.com/repos/SagerNet/sing-box/releases/latest" | jq -r .tag_name)
  version="${version#v}"
  log "installing sing-box ${version} (${arch})"
  local tmp=/tmp/sb.tar.gz
  curl -fsSL -o "$tmp" \
    "https://github.com/SagerNet/sing-box/releases/download/v${version}/sing-box-${version}-linux-${arch}.tar.gz"
  tar -xzf "$tmp" -C /tmp
  install -m 0755 "/tmp/sing-box-${version}-linux-${arch}/sing-box" /usr/local/bin/sing-box
  rm -rf "$tmp" "/tmp/sing-box-${version}-linux-${arch}"
}

# ------------------------------------------------------------ certificate --
ensure_cert() {
  if [ ! -f "$WORKDIR/cert.pem" ]; then
    log "generating a self-signed certificate (clients must allow insecure TLS)"
    openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout "$WORKDIR/key.pem" -out "$WORKDIR/cert.pem" \
      -days 3650 -subj "/CN=${SNI:-www.microsoft.com}" \
      -addext "subjectAltName=DNS:${SNI:-www.microsoft.com}" 2>/dev/null
  fi
}

# --------------------------------------------------------------- config ----
write_config() {
  ensure_cert
  local sni="${SNI:-www.microsoft.com}"
  {
    cat <<EOF
{
  "log": { "level": "info" },
  "inbounds": [
EOF
    case "$PRESET" in
      vless-ws)
        cat <<EOF
    {
      "type": "vless",
      "tag": "vless-ws-in",
      "listen": "0.0.0.0",
      "listen_port": ${PORT},
      "users": [ { "uuid": "${UUID}", "flow": "" } ],
      "transport": { "type": "ws", "path": "${WSPATH}", "max_early_data": 2048 },
      "tls": { "enabled": true, "server_name": "${sni}", "certificate_path": "${WORKDIR}/cert.pem", "key_path": "${WORKDIR}/key.pem" }
    }
EOF
        ;;
      vless-xhttp)
        cat <<EOF
    {
      "type": "vless",
      "tag": "vless-xhttp-in",
      "listen": "0.0.0.0",
      "listen_port": ${PORT},
      "users": [ { "uuid": "${UUID}" } ],
      "transport": { "type": "http", "path": "${WSPATH}" },
      "tls": { "enabled": true, "server_name": "${sni}", "certificate_path": "${WORKDIR}/cert.pem", "key_path": "${WORKDIR}/key.pem" }
    }
EOF
        ;;
      trojan-ws)
        cat <<EOF
    {
      "type": "trojan",
      "tag": "trojan-ws-in",
      "listen": "0.0.0.0",
      "listen_port": ${PORT},
      "users": [ { "name": "openpath", "password": "${PASSWORD}" } ],
      "transport": { "type": "ws", "path": "${WSPATH}" },
      "tls": { "enabled": true, "server_name": "${sni}", "certificate_path": "${WORKDIR}/cert.pem", "key_path": "${WORKDIR}/key.pem" }
    }
EOF
        ;;
      shadowsocks)
        cat <<EOF
    {
      "type": "shadowsocks",
      "tag": "ss-in",
      "listen": "0.0.0.0",
      "listen_port": ${PORT},
      "method": "${METHOD}",
      "password": "${PASSWORD}"
    }
EOF
        ;;
      hysteria2)
        cat <<EOF
    {
      "type": "hysteria2",
      "tag": "hy2-in",
      "listen": "0.0.0.0",
      "listen_port": ${PORT},
      "users": [ { "name": "openpath", "password": "${PASSWORD}" } ],
      "obfs": { "type": "salamander", "password": "${OBFS_PASS}" },
      "tls": { "enabled": true, "server_name": "${sni}", "certificate_path": "${WORKDIR}/cert.pem", "key_path": "${WORKDIR}/key.pem", "alpn": [ "h3" ] }
    }
EOF
        ;;
      tuic)
        cat <<EOF
    {
      "type": "tuic",
      "tag": "tuic-in",
      "listen": "0.0.0.0",
      "listen_port": ${PORT},
      "users": [ { "uuid": "${UUID}", "password": "${PASSWORD}" } ],
      "congestion_control": "bbr",
      "tls": { "enabled": true, "server_name": "${sni}", "certificate_path": "${WORKDIR}/cert.pem", "key_path": "${WORKDIR}/key.pem", "alpn": [ "h3" ] }
    }
EOF
        ;;
    esac
    cat <<EOF

  ],
  "outbounds": [
    { "type": "direct", "tag": "direct" },
    { "type": "block", "tag": "block" }
  ],
  "route": { "rules": [ { "ip_is_private": true, "outbound": "direct" } ], "final": "direct" }
}
EOF
  } > "$WORKDIR/config.json"
  log "config written for preset ${PRESET} on port ${PORT}"
}

# --------------------------------------------------- cloudflare quick tunnel --
maybe_tunnel() {
  if [ "${OPENPATH_TUNNEL:-0}" != "1" ]; then return 0; fi
  local arch
  case "$(uname -m)" in
    x86_64|amd64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    armv7l) arch=arm ;;
    *) arch=amd64 ;;
  esac
  log "starting cloudflared quick tunnel"
  curl -fsSL -o /usr/local/bin/cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}"
  chmod +x /usr/local/bin/cloudflared
  ( cloudflared tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate > "$WORKDIR/tunnel.log" 2>&1 & )
  for _ in $(seq 1 60); do
    local url
    url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$WORKDIR/tunnel.log" | head -1 || true)
    if [ -n "${url:-}" ]; then
      log "tunnel URL: $url"
      echo "$url" > "$WORKDIR/tunnel-url.txt"
      publish_url "$url"
      return 0
    fi
    sleep 2
  done
  log "tunnel URL did not appear in time (see $WORKDIR/tunnel.log)"
}

# Codespaces has no public port, so we drop the URL into the repository itself
# for `openpath paas codespace` to pick up.
publish_url() {
  local url="$1"
  [ -n "${GITHUB_TOKEN:-}" ] || { log "no GITHUB_TOKEN - skipping publish"; return 0; }
  [ -n "${GITHUB_REPOSITORY:-}" ] || { log "no GITHUB_REPOSITORY - skipping publish"; return 0; }
  [ -n "${CODESPACE_NAME:-}" ] || { log "not a codespace - skipping publish"; return 0; }
  local path="tunnels/${CODESPACE_NAME}.txt"
  local existing
  existing=$(curl -fsSL -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/contents/${path}" | jq -r .sha 2>/dev/null || echo "")
  local payload
  payload=$(jq -n --arg content "$(printf '%s' "$url" | base64 -w0)" --arg msg "openpath: tunnel url" \
    --arg sha "$existing" '{message:$msg, content:$content} | if $sha != "" then . + {sha:$sha} else . end')
  curl -fsSL -X PUT -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/contents/${path}" -d "$payload" >/dev/null \
    && log "published tunnel URL to ${path}" || log "publishing failed"
}

print_share_links() {
  local host="${OPENPATH_PUBLIC_HOST:-}"
  [ -n "$host" ] || host="$(hostname -f 2>/dev/null || echo 127.0.0.1)"
  log "node: ${NAME} (${PRESET}) on ${host}:${PORT}"
  log "remember to set the matching UUID / password in your client"
}

install_singbox
write_config
maybe_tunnel
print_share_links

exec sing-box run -c "$WORKDIR/config.json"
