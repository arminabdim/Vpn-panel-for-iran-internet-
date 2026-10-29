# Methods compared

Statuses were last checked **2026-10-29**. `stable` = works today on most
ISPs, `beta` = works but is fragile or new, `alpha` = expect breakage.

| Method | Status | Difficulty | Cost | UDP | Speed | Survives a near-shutdown | Notes |
|---|---|---|---|---|---|---|---|
| **Cloudflare Worker** (VLESS/Trojan-WS) | stable | medium | free | no | good | no | 100 k req/day, 6 concurrent connections. Needs a working connection to deploy |
| **Cloudflare Pages** (VLESS/Trojan-WS) | stable | high | free | no | good | no | same limits, `pages.dev` domain, slower deploys |
| **CF Snippets** (vless/ss over ws+xhttp) | beta | high | free | no | good | no | actively developed in 2026; API is unofficial and can change overnight |
| **CF relay** (`/relay` HTTP proxy) | stable | low | free | no | fair | no | turn the Worker into a plain HTTP proxy for browsers |
| **WARP** (WireGuard) | stable | easy | free | yes | very good | no | clean Cloudflare IPs; some ISPs block the WARP handshake, then use wgcf fallback |
| **Google Apps Script relay** | stable | medium | free | no | fair | **yes** | the last thing working in Iran's Feb-2026 near-shutdown. Quota-based, cannot reach googlevideo.com |
| **DPI bypass — built in** | stable | easy | free | yes | full | yes | local only: TLS record split + decoy SNI, with auto fallback to plain forwarding |
| **SpoofDPI** | stable | easy | free | yes | full | yes | Go binary; needs a binary for your arch, no fragmentation tuning |
| **ByeDPI** | stable | medium | free | yes | full | yes | C, very configurable; Termux needs `clang` |
| **Xray fragment** (`freedom` packets) | beta | easy | free | yes | full | yes | serverless: no remote node at all, just a local Xray config |
| **PaaS — Render** | stable | hard | free | limited | very good | no | 750 h/mo, sleeps in 15 min; public ports are HTTP, so Hysteria2/TUIC are not reachable externally |
| **PaaS — Codespaces** | beta | hard | free | yes | good | no | 60 core-h/mo; no public port, so OpenPath publishes a cloudflared quick-tunnel URL |
| **PaaS — Deno Deploy** | alpha | medium | free | no | good | no | easy JS deploy, but no UDP and a stricter free tier |
| **DNSTT / SlipNet** | stable | hard | free | no | very slow (≈130 KB/s) | **yes** | the only thing that connected during Iran's Feb-2026 near-shutdown |
| **Tor bridges** | stable | easy | free | no | slow | partial | obfs4/snowflake; needs bridge lines, and Tor itself is often throttled |
| **Public subscriptions** | stable | easy | free | varies | varies | no | thousands of nodes, auto-tested here. **Trust nothing sensitive to them** |
| **MTProto proxy** | stable | easy | free | no | fast | partial | Telegram only, nothing else |
| **Experimental** | alpha | — | free | — | — | — | ECH, HTTP/3 tunnelling, DoH3 relays. Research only |

## Which one for which ISP

Experience in Iran (2025–2026) varies by ISP, but the pattern is stable:

* **Mobile networks (Hamrahe Aval, Irancell, Rightel)** — filter aggressively
  and use carrier-grade NAT. Cloudflare Workers work; UDP protocols (Hysteria2,
  TUIC, WireGuard) are usually blocked or throttled. **Use VLESS-WS or the
  Google relay.**
* **Home ADSL / VDSL (TCI, Shatel, Asiatech, …)** — TCP filtering is strong,
  UDP is often untouched. **Hysteria2 / TUIC on a PaaS node** is usually the
  fastest, and the built-in **DPI bypass** fixes "some HTTPS sites never load".
* **Fibre / business lines** — lighter filtering. Almost everything works;
  pick by speed.
* **During shutdowns** — nothing that needs a control-plane connection works.
  Fall back to **Google relay**, **DNS tunnelling**, and **local DPI bypass**.

## Why UDP protocols need a container

A Cloudflare Worker is a JavaScript sandbox with **no UDP sockets**. That rules
out Hysteria2, TUIC and plain WireGuard. The `paas/` folder exists exactly for
that: a free container gives you real UDP.

## Protocol-specific warnings

* **VLESS-REALITY**: reported blocked on several Iranian ISPs in late 2026 —
  don't rely on it alone.
* **ECH**: Iran does not block the ECH extension; it blocks encrypted DNS
  instead. ECH alone will not save you.
* **QUIC protocols (Hysteria2, TUIC)**: no transport customisation is possible,
  so you cannot hide them further — if UDP is filtered, they simply fail.
* **Hybrid**: DPI bypass + your Worker is the most resilient combination; the
  bypass handles the handshake, the Worker provides the clean exit.
