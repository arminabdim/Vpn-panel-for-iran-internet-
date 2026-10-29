# Troubleshooting

Run `python3 openpath.py doctor` first — it tells you what works on your
network right now.

## "The panel won't open"
* Use `127.0.0.1:8765`, not `localhost` (some phones resolve it wrong).
* Port taken? `python3 openpath.py panel --port 9000`.
* Termux keeps killing it: `termux-wake-lock` first, and read `docs/TERMUX.md`.

## "Deploy failed: 401 / Unauthorized"
The API token is wrong or lacks permissions. It needs **`Workers Scripts: Edit`**
and **`Account Settings: Read`**, scoped to the account. Re-save it in the
panel's Worker tab.

## "Error 1027" / "429" in the client
You hit Cloudflare's free limit: **100,000 requests per day**, reset 00:00 UTC.
Wait, or switch to WARP / the Google relay until it resets.

## "The config imports but doesn't connect"
1. Panel → **Test** tab → run it. If TCP connect fails, the host/port is
   blocked — change the port (443, 8443, 2053, 2083, 2087 for TLS; 80, 8080,
   8880, 2052, 2082, 2086 for plain).
2. Make sure the UUID/password in the client matches exactly what the panel
   printed.
3. WebSocket path is case-sensitive: `/openpath` ≠ `/OpenPath`.

## "v2rayNG says unknown protocol"
v2rayNG is Xray-based and **cannot run Hysteria2 or TUIC**. Use **MahsaNG** or
another sing-box client for those. Everything else (VLESS, VMess, Trojan,
Shadowsocks, WireGuard) works in both.

## "Websites work but some HTTPS sites hang"
Classic DPI. Panel → **DPI** tab → Start, then set your client's chain proxy
(or the system proxy) to `127.0.0.1:8081`. If it gets worse, turn *fragment*
off — some middleboxes kill fragmented handshakes (OpenPath detects this and
retries without fragmentation automatically).

## "The Google relay is slow or fails on big files"
Apps Script caps responses around 9–10 MB and cannot fetch `googlevideo.com`
(so no YouTube through it). Turn **Range retries** on in the GAS tab and use it
for messaging and browsing.

## "WARP registration failed"
The API version changed. OpenPath tries four known versions and then falls back
to `wgcf`. If both fail, use the panel's WARP tab with a fresh key, or wait —
this usually breaks and gets fixed within days.

## "Everything is filtered right now"
In this order: **Google relay** → **DNS tunnel (DNSTT/SlipNet)** → **local DPI
bypass** → **public subscriptions** with the latency test. See `GUIDE.md`.

## "The DPI proxy kills some sites"
OpenPath's fallback: after sending the split packets it probes the connection
for ~1.5 s; if the middlebox reset it, the same request is retried **without**
fragmentation. If you still see failures, raise chunks to 1 (least splitting)
or disable *decoy SNI*.

## "sing-box won't start with my config"
The generated `tls.fragment` uses the object form `{enabled,size,sleep}`.
sing-box 1.12+ may expect boolean `"fragment": true` with
`fragment_fallback_delay`. Edit the JSON by hand if your client complains —
the panel's export is otherwise standard.

## "I lost my config"
Everything is stored under `~/.openpath/` (`state.json`, `warp/`, `gas/`). The
panel's Subscriptions tab can re-import any URI you saved.
