# OpenPath

**A free panel that builds working proxy configs for Iran — no server, no subscription fee, no VPN company.**

OpenPath is a collection of *generators and relays* that run entirely on free
infrastructure: Cloudflare's free tier, your own Google account's Apps Script
quota, free container hosts, and — for the hard days — a local DPI bypass that
runs on your phone or laptop. It is inspired by
[BPB-Worker-Panel](https://github.com/bia-pain-bache/BPB-Worker-Panel) and
[MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN), but
it does not depend on anyone else's panel staying online: **you create your own
node, so it works when other panels are blocked.**

> Nothing here is a VPN service. OpenPath does not sell, resell, or proxy your
> traffic for you — it hands you the tools to make your own. Please use it
> responsibly and in accordance with the law.

---

## The one command (Termux / Android)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/arminabdim/Vpn-panel-for-iran-internet-/main/install.sh)
```

That's it. It needs `python3` and `git` (Termux: `pkg install python git`), it
installs into `~/openpath`, and it opens a panel in your browser at
`http://127.0.0.1:8765`. Everything after that is clicking.

Prefer no download at all?

```bash
python3 -m http.server 8765 --directory .   # any static copy of panel/
```
Open `http://127.0.0.1:8765` — the panel still works in **standalone mode**
(generating configs, QR codes, templates and guides), and it will offer to
start the Python bridge if you want the automated parts.

---

## What's inside

| Part | What it does | Needs |
|---|---|---|
| **Panel** (`panel/`) | A real GUI in your browser: 18 documented methods, config builder, QR codes, latency tests, user guide. Works offline. | a browser |
| **Engine** (`openpath/core/configs.py` + `panel/assets/js/engine.js`) | One link format in → VLESS / VMess / Trojan / Shadowsocks / Hysteria2 / TUIC / WireGuard out, as URI, sing-box, Clash, Xray or a base64 subscription. The Python and the JavaScript engine emit **byte-identical** output (50 outputs, cross-checked in CI). | — |
| **Cloudflare Worker** (`worker/`) | Your own VLESS/Trojan node on `*.workers.dev`, deployed straight from the panel with an API token — no wrangler, no Node. | free Cloudflare account |
| **WARP** (`openpath/core/warp.py`) | Registers a WireGuard WARP account in pure Python (no wgcf) and prints configs with clean, unblocked Cloudflare exit IPs. | — |
| **Google relay** (`gas/Code.gs`) | An HTTP/SOCKS5 relay that lives inside Apps Script. Historically the **last thing still working** during Iran's near-total shutdowns. | a Google account |
| **DPI bypass** (`openpath/core/dpi.py`) | Local TLS-record fragmentation with a decoy ClientHello, plus a plain-forwarding fallback that detects a killed connection and retries, so a site never becomes unreachable because of the bypass. | your device |
| **PaaS** (`paas/`) | A Dockerfile that turns a free Render service or GitHub Codespace into a Hysteria2 / TUIC / Shadowsocks node — the protocols Workers cannot run. | free container host |
| **Subscription tools** (`openpath/core/sub.py`) | Collect public configs, deduplicate, latency-test, and re-export for any client. | internet |

### The 18 methods

Cloudflare Worker · Cloudflare Pages · CF Snippets · CF relay · WARP ·
Google Apps Script relay · built-in DPI bypass · SpoofDPI · ByeDPI ·
Xray fragment · Render · Codespaces · Deno Deploy · DNSTT/SlipNet ·
Tor bridges · public subscriptions · MTProto · (experimental slot)

Each one is documented in the panel with **status, difficulty, cost, when to
use it, its limits, and click-by-click steps** — in English and Persian.

---

## Getting a working config in 5 minutes

**Option A — your own Cloudflare node (recommended, most durable)**

1. Sign up at [dash.cloudflare.com](https://dash.cloudflare.com) (free).
2. Create an API token: *My Profile → API Tokens → Create Custom Token* →
   permissions `Workers Scripts: Edit`, `Account Settings: Read`.
3. In the panel: **Worker** tab → paste the token → **Deploy**.
4. Copy the subscription link it prints into **v2rayNG** or **MahsaNG**.

**Option B — nothing to sign up for**

Panel → **Methods** → *Google Apps Script relay* (or *WARP*) → follow the
steps. The WARP tab generates a WireGuard config with no account at all.

**Option C — when everything is filtered**

Panel → **DPI** tab → Start. Then point your client at
`127.0.0.1:8081` (HTTP) / `1081` (SOCKS) as a chain proxy, or just set the
system proxy to it.

---

## Clients

* **v2rayNG / MahsaNG (Android)** — use the *subscription* link from the
  panel; both understand sing-box flavoured subscriptions, Clash YAML and
  single URIs. For Hysteria2 and TUIC you need **MahsaNG** or any sing-box
  client (v2rayNG cannot run them).
* **sing-box / Hiddify / Nekobox / Clash** — paste the subscription URL,
  or import the generated JSON directly.
* **Desktop** — the panel's **Test** tab runs a latency/speed check before you
  commit to a config.

---

## Repository layout

```
openpath.py              zero-install entry point (python3 openpath.py …)
openpath/
  cli.py                 the whole command line + an interactive menu
  core/
    configs.py           protocol engine (canonical dict <-> every format)
    cf.py                Cloudflare Workers deploy without wrangler
    warp.py              pure-Python WARP registration
    gas.py               Google Apps Script relay client
    dpi.py               local DPI desync proxy (+ fallback)
    sub.py               subscription collection / dedupe / export
    net.py               tcping, TLS probe, speed test
    paas.py              Render / Codespaces / Deno automation
    bridge.py            local API the panel talks to
    selftest.py          46 offline checks
    util.py              state, colours, helpers
worker/src/index.js      the Cloudflare Worker (templated)
gas/Code.gs              the Apps Script relay
paas/                    Dockerfile + entrypoint + Codespaces glue
panel/                   the browser panel (no build step, no CDN)
tools/crosscheck.py      Python <-> JavaScript engine parity gate
```

## Command line

```bash
python3 openpath.py                 # interactive menu
python3 openpath.py panel           # open the panel
python3 openpath.py worker          # build + deploy a Cloudflare Worker
python3 openpath.py warp new        # generate WARP configs
python3 openpath.py gas new         # print the Apps Script relay
python3 openpath.py dpi start       # local DPI bypass on :8081
python3 openpath.py sub fetch       # collect + test public configs
python3 openpath.py test            # latency / TLS probe
python3 openpath.py doctor          # what works on this network right now
python3 openpath.py selftest        # 46 offline checks
```

## Verifying it yourself

```bash
python3 openpath.py selftest      # → 46 passed, 0 failed
python3 tools/crosscheck.py       # → python and javascript engines agree
```

Both run in CI on every push (`.github/workflows/test.yml`).

---

## Documents

* **[Guide for everyone](GUIDE.md)** — plain language, no jargon, what to do
  when nothing works.
* **[Methods compared](docs/METHODS.md)** — every method, its limits, and
  which one works on which ISP.
* **[Troubleshooting](docs/TROUBLESHOOTING.md)** — error by error.
* **[Termux notes](docs/TERMUX.md)** — phones, battery, keeping it alive.
* **[How it works](docs/HOW-IT-WORKS.md)** — the internals, for contributors.
* [راهنمای فارسی](README_FA.md)

## Safety notes

* OpenPath keeps everything on your device: no telemetry, no analytics, no
  third-party scripts in the panel, no external fonts or CDNs.
* A **public** config is somebody else's computer. Use it for browsing, never
  for banking or passwords — that is what your own Worker node is for.
* The Cloudflare free tier allows 100,000 requests/day; the panel warns you
  and offers WARP or the relay as a fallback when you approach it.

## Licence

MIT. Do whatever you like with it — just don't sell other people's access and
call it free.
