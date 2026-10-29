# OpenPath free container (`paas/`)

A real server for the protocols that a Cloudflare Worker cannot run, because
Workers have no UDP: **Hysteria2, TUIC, Shadowsocks (with UDP)**, and also a
non-Cloudflare exit IP for VLESS / Trojan.

Where it can run for free (checked 2026-10):

| Platform | Free allowance | Notes |
|---|---|---|
| Render | 750 instance-hours/month, no card | sleeps after 15 min idle, ~1 min cold start. Public ports are HTTP; UDP protocols will not be reachable from outside |
| GitHub Codespaces | 60 core-hours/month | OpenPath publishes a Cloudflare quick tunnel URL, so it works without any public port |
| Google Cloud Run | generous free tier | wants a billing account (card), scales to zero |
| ~~Koyeb~~ / ~~Fly.io~~ | — | free compute was closed to new users (Feb 2026 / 2024) |

## Quick start (Render)

1. Copy this `paas/` folder into a GitHub repository (call it `openpath-paas`).
2. `openpath paas render-key <your Render API key>` (dashboard → Account → API keys).
3. `openpath paas render --repo you/openpath-paas --preset vless-ws`
4. Wait for the build (a few minutes), then import the printed config.

## Quick start (Codespaces)

```bash
gh auth login                                   # or export GITHUB_TOKEN=...
openpath paas codespace --repo you/openpath-paas --preset hysteria2
```
OpenPath starts the codespace, the container opens a Cloudflare quick tunnel
and writes its URL to `tunnels/<codespace-name>.txt` in the same repository;
OpenPath polls that file and prints your ready-to-import config.

## Environment variables

| Variable | Meaning |
|---|---|
| `OPENPATH_PRESET` | `vless-ws`, `vless-xhttp`, `trojan-ws`, `shadowsocks`, `hysteria2`, `tuic` |
| `OPENPATH_PORT` | listening port (Render gives you `$PORT`) |
| `OPENPATH_UUID` | VLESS / TUIC user id |
| `OPENPATH_PASSWORD` | Trojan / Shadowsocks / Hysteria2 / TUIC password |
| `OPENPATH_METHOD` | Shadowsocks method |
| `OPENPATH_PATH` | WebSocket / XHTTP path |
| `OPENPATH_OBFS_PASSWORD` | Hysteria2 salamander obfuscation password |
| `OPENPATH_SNI` | certificate name (use a plausible public name) |
| `OPENPATH_TUNNEL` | `1` = also start a cloudflared quick tunnel |

The container generates a self-signed certificate, so clients must accept an
insecure certificate (`allowInsecure` / `skip-cert-verify`) unless you put a
real domain in front of it.

## Local test

```bash
docker build -t openpath-paas .
docker run --rm -p 8443:443 -e OPENPATH_PRESET=hysteria2 -e OPENPATH_PASSWORD=secret openpath-paas
```
