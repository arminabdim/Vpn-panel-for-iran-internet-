# OpenPath — a guide for everyone

*No jargon. If you can copy and paste, you can do this.*

---

## 1. What is this, in one minute?

Iran's internet is filtered. Filters ("DPI" boxes) look at the *first packets*
of your connection, guess where you are going, and cut it off.

Every tool here does the same thing in a different way: it makes your traffic
look like something the filter is not allowed to block — a request to a
Cloudflare server, a request to Google, or a packet so strange that the filter
gives up and lets it through.

OpenPath is **not a VPN company**. It does not sell you anything and it does
not see your traffic. It is a panel (a webpage) that helps you create your own
connection using free services — mostly Cloudflare and Google, which are free
up to very generous limits.

**Why your own?** Because public configs get blocked in days. When you create
your own node on your own Cloudflare account, it's yours: nobody shares it, so
nobody gets it blocked for you.

---

## 2. The fastest path (10 minutes, lasts months)

This is the path I recommend to everyone.

**What you need:** an email address, and a phone or computer.

### Step 1 — open the panel

On Android, install **Termux** (from F-Droid, *not* the Play Store) and type
one line:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/arminabdim/Vpn-panel-for-iran-internet-/main/install.sh)
```

On a computer with Python:

```bash
git clone https://github.com/arminabdim/Vpn-panel-for-iran-internet-.git
cd Vpn-panel-for-iran-internet-
python3 openpath.py panel
```

A page opens. That's your control room. Everything below happens there.

### Step 2 — get a free Cloudflare account

1. Go to **dash.cloudflare.com** → Sign up → free plan.
2. Confirm your email.

### Step 3 — create the key the panel needs

1. Top-right corner → **My Profile** → **API Tokens**.
2. **Create Custom Token** → *Get started*.
3. Permissions:
   * `Account` → `Workers Scripts` → **Edit**
   * `Account` → `Account Settings` → **Read**
4. Account resources: *Include → your account*.
5. **Continue to summary** → **Create Token** → copy the long string.

> ⚠️ That string is a password. Don't send it to anyone, don't put it in a
> group chat. The panel keeps it only on your device.

### Step 4 — deploy

In the panel: **Worker** tab → paste the token → **Save** → **Deploy**.

Thirty seconds later you get a **subscription link**. That's it — that's your
connection.

### Step 5 — put it in your app

* **v2rayNG / MahsaNG** (Android): `+` → *Import from clipboard / subscription*
  → paste → connect.
* **Hiddify / Nekobox / sing-box** (Windows, Mac, Linux): paste the same link.

Now open a blocked site in your browser. It should load.

---

## 3. If you don't want to sign up for anything

Two methods need no account at all:

* **WARP** (panel → *WARP* tab) — Cloudflare's own free WireGuard service.
  Press *Generate*, copy the config. Great speed; some networks block it.
* **Google relay** (panel → *GAS* tab, or *Methods*) — a relay that runs
  inside your Google account's Apps Script. Historically this has been the
  **last method still working** during near-total shutdowns, because Iran is
  reluctant to block Google entirely. Slower, but it survives.

Both are explained click-by-click inside the panel.

---

## 4. When the internet is *really* broken

During war-time conditions or full shutdowns, tunnels that need a working
connection to build a tunnel stop working. Then use what runs **on your own
device**:

### DPI bypass (panel → *DPI* tab)

It splits the first packet of every HTTPS connection into tiny pieces so the
filter can't read the destination. Press **Start**, then set your system or
browser proxy to:

```
HTTP  127.0.0.1:8081
SOCKS 127.0.0.1:1081
```

If a site stops loading, press **Start** again with *fragment* off — OpenPath
also has a safety net: if it notices the connection was killed because of the
splitting, it automatically retries the same site **without** splitting.

### Public subscriptions (panel → *Subscriptions* tab)

Thousands of strangers publish free configs, and they are collected, tested and
sorted here. **Use these only for browsing** — the person running the node can
see your traffic. Never for banking.

### DNS tunnels (DNSTT / SlipNet)

If literally nothing else connects, DNS tunnels often still do, because a
country cannot break DNS without breaking the internet for itself. Very slow
(≈130 KB/s) — enough for messaging, not for video.

---

## 5. Which method should I use?

| Situation | Use this |
|---|---|
| Normal filtered internet | **Your own Cloudflare Worker** (Step 2) |
| You can't sign up for Cloudflare | **WARP** |
| Cloudflare is filtered | **Google relay** (GAS) |
| Everything is filtered / war conditions | **Google relay**, then **DNS tunnel** |
| Sites load but HTTPS is cut | **DPI bypass** |
| You need UDP (gaming, QUIC, video calls) | **PaaS node** (Hysteria2 / TUIC) |
| You just need Telegram today | **MTProto proxy** |
| Nothing works at all | Combine: DPI bypass **+** your Worker config |

The **Methods** tab has all 18 methods with an honest status for each
(stable / beta / alpha), how hard it is, what it costs, and its limits.

---

## 6. Questions people ask

**Is it really free?**
Yes. Cloudflare's free plan, Google Apps Script's free quota, and free
container hosts. Nothing here asks for a card. The only cost is a few minutes.

**Will my data be sold?**
Not by us — there is no "us" in the middle. OpenPath runs on your device and
talks to services you logged into yourself. Public configs are the exception:
those are other people's servers, so treat them like a stranger's Wi-Fi.

**Why did my config stop working after a few days?**
Either the free quota ran out (100,000 requests/day on Cloudflare — the panel
warns you), or a shared/public node got blocked. Your own node rarely dies.

**Is it legal?**
OpenPath is a tool for accessing information and is published openly, like the
projects it builds on. How you use it is your responsibility — be careful and
follow the law where you are.

**Can I share my config with my family?**
Yes, and it's safe-ish: a small number of people on your own Worker is fine.
Don't post it publicly — that's exactly how nodes get blocked.

**My speed is bad — what now?**
Panel → **Test** tab, run the test. If latency is over ~400 ms, try WARP. If
some sites work and others don't, that's filtering, not speed — try the
PaaS node (different exit IP) or the DPI bypass.

---

## 7. If you get stuck

1. **Doctor** — `python3 openpath.py doctor`, or the *Test* tab. It tells you
   what works on your network right now.
2. **[Troubleshooting](docs/TROUBLESHOOTING.md)** — error by error.
3. Open an issue on GitHub with what you tried and what the panel said.

---

## 8. A note on staying safe

* Update your client app before you connect — old clients leak.
* Don't log into important accounts over a **public** config.
* If a "free VPN" asks you to install a certificate on your phone, say no.
* Shutdowns come with disinformation. Trust a couple of independent sources,
  not forwarded voice messages.

Stay safe. 🕊
