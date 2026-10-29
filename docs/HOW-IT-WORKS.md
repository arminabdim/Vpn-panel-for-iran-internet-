# How OpenPath works (for contributors)

## The engine

Every protocol is normalised into one Python/JS dict:

```python
{"proto","server","port","uuid","password","method","network","security",
 "sni","host","path","header_type","alpn","obfs","flow","name", ...}
```

`openpath/core/configs.py` converts that dict to and from:

* `vless://`, `vmess://`, `trojan://`, `ss://`, `hysteria2://`, `tuic://`,
  `wireguard://`, `socks://`, `http://`
* sing-box outbound / full config (TUN in, urltest + selector, bypass-ir rules)
* Clash YAML proxy / config
* Xray outbound / config
* WireGuard `.conf`
* base64 subscription documents

`panel/assets/js/engine.js` is a line-by-line port of the same logic so the
browser can generate configs with no server. The two are kept byte-identical by
`tools/crosscheck.py`, which renders 10 fixtures in both engines and diffs all
50 outputs. **Run it after touching either file.**

## The worker

`worker/src/index.js` is a template with `{{…}}` slots (`{{UUID}}`,
`{{SUB_PATH}}`, `{{PROXY_IP}}`, …). It serves:

* `GET /health`
* `GET /<subPath>` — subscription (auto-detects sing-box / Clash / Xray by
  User-Agent)
* `GET /relay?url=…` — HTTP relay for browsers
* any other path — the VLESS/Trojan WebSocket endpoint

It includes a hand-rolled SHA-224 (WebCrypto has none) for Trojan auth.

## The Google relay

`gas/Code.gs` is an Apps Script `doPost` handler. The client sends
`{"k":AUTH_KEY,"r":[{"m","u","h","b","f"}]}` with base64 bodies; the script
fetches and returns `{"ok","r":[{"s","h","b"}]}`. `openpath/core/gas.py` also
runs a local HTTP+SOCKS5 MITM proxy in front of it, with an openssl-generated
CA for HTTPS.

## The DPI proxy

`openpath/core/dpi.py`:

1. HTTP `CONNECT` / SOCKS5 handshake.
2. Read the client's first bytes; if it's a TLS ClientHello, optionally swap the
   SNI for a decoy and split the record into N chunks.
3. Send each chunk with a small delay.
4. **Fallback:** probe the upstream for ~1.5 s; on EOF/error (a killed
   connection) retry the whole request unfragmented over a fresh socket.

That fallback is load-bearing — without it, a middlebox that resets fragmented
handshakes makes sites permanently unreachable. A sweep of chunk counts
(1, 2, 3, 5, 8) × decoy on/off passes 10/10 here.

## Adding a method

1. Add an entry to `panel/assets/js/methods.js` (bilingual: title, summary,
   when, limits, steps, links).
2. Add any API route to `openpath/core/bridge.py` if it needs the bridge.
3. Add strings to `panel/assets/js/i18n.js`.
4. Extend `openpath/core/selftest.py` with an offline check.
5. Run `python3 openpath.py selftest` and `python3 tools/crosscheck.py`.

## Tests

* `python3 openpath.py selftest` — 46 offline checks (no network).
* `python3 tools/crosscheck.py` — Python/JS engine parity (50 outputs).
* `node tools/worker_runtime_test.mjs` — renders the Worker, runs it in node
  with `cloudflare:sockets` stubbed, and checks that `/health` and the
  subscription really answer in all four formats (12 checks).
* `node tools/panel_test.cjs` (needs `npm install jsdom`) — starts its own
  bridge, then drives the panel in a real DOM in **both** modes: every tab
  renders, the generated Worker is filled in and valid, import/export/QR work,
  the relay template renders, Persian switches to RTL (57 checks).
* `python3 tools/pages_build.py --out _site` — builds the Pages artifact and
  fails if the panel ever starts loading something from the internet.
* All of them run in CI on every push.
