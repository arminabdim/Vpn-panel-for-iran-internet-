# Termux notes (Android)

## Install

```bash
pkg update && pkg install python git
bash <(curl -fsSL https://raw.githubusercontent.com/arminabdim/Vpn-panel-for-iran-internet-/main/install.sh)
```

OpenPath lands in `~/openpath` and the panel opens on `http://127.0.0.1:8765`.

## Keeping it alive

Android kills background processes. Before a long session:

```bash
termux-wake-lock                 # needs the Termux:API app
python3 ~/openpath/openpath.py panel
```

Swipe Termux **down** in the recents list and choose *Acquire wakelock* by
long-pressing the notification.

## Persian text in Termux

Persian glyphs are usually garbled (no shaping) in Termux, so **the CLI is
English-only** and prints Persian only when the terminal supports it. The
**panel** renders Persian properly in your browser — use the فارسی button.

## Common fixes

* `curl: command not found` → `pkg install curl`
* `Permission denied` on scripts → `termux-setup-storage` and keep everything
  under `~/`
* Port 8765 in use → `python3 ~/openpath/openpath.py panel --port 9000`
* Battery drain → the panel itself is idle; drain comes from the client app's
  VPN service, not from OpenPath.

## Using the DPI bypass on Android

Start it from the panel (DPI tab), then in v2rayNG/MahsaNG:
*Settings → Chain proxy / Prepend proxy → HTTP `127.0.0.1:8081`*.

Or set the Android system proxy (Wi-Fi → modify network → advanced) to
`127.0.0.1` port `8081`.

## No Termux?

Use the panel in **standalone mode**: any static server (or GitHub Pages) can
serve `panel/`. You can still generate configs, QR codes, worker templates and
read the guides — you just can't deploy from the browser without the Python
bridge.
