# Tacho Bridge App — fork & upstream

This is DH FleetView's fork of the **Tacho Bridge App**
([flespi-software/Tacho-Bridge-App](https://github.com/flespi-software/Tacho-Bridge-App),
MIT, default branch `master`). It runs on the PC with the company card readers or the
Lisle card rack and answers company-card authentication during remote tacho downloads.

Current base: upstream **v0.8.0-rc.16**, built as **0.8.0-rc.16-dh.1**.

## How it fits together (since 0.8)

Upstream's code is kept **as it is** — its MQTT v5 protocol
(`communication_protocol.md`), the PC/SC card sessions, the Lisle card rack on the
COM port, server sign-in, the tray and the self-updater. Instead of rewriting the
transport (the pre-0.8 fork used a WebSocket, which the 0.8 rack code can't sit on),
the DH FleetView **tacho server speaks upstream's protocol**:
`tachograph-server/app/services/bridge_server.py` listens on
`dhfleetview.co.uk:8883` (TLS) and checks every connection against a bridge
sign-in created on the Tachograph page.

## What we change (the overlay — `scripts/apply-overlay.py`)

| Area | Upstream (flespi) | This fork |
|------|-------------------|-----------|
| Server | none by default; user types a flespi host | `dhfleetview.co.uk:8883` by default (`config.rs` `DEFAULT_SERVER_HOST`) |
| Encryption | plain TCP | TLS on port 8883 with the Windows trust store (`mqtt.rs` `MQTT_TLS_PORT`, rumqttc `use-native-tls`) |
| Updates | GitHub releases of flespi | `https://dhfleetview.co.uk/tacho/bridge/latest.json` (+ `latest-beta.json`), signed with **our** key |
| Bundle | `com.flespi.tba.dev`, "tba" | `com.dhfleetview.tachobridge`, "DH FleetView Tacho Bridge", NSIS only |
| Wording / metadata | flespi token, gurtam repo | DH FleetView sign-in, this repo |

The updater's private key is `D:\DHFleetViewData\tacho\bridge\signing\updater.key`
on the server — **never commit it**. Its public half is in `tauri.conf.json`.

## Guarantee: no flespi association

`scripts/check-flespi.sh` fails on any flespi/gurtam reference in the app source or
build config, and if the server address, TLS, update feed or bundle id stop being
ours. It runs in CI on every push/PR (`.github/workflows/tacho-bridge-guard.yml`),
in `build-local.sh`, and must pass after every sync.

## Pulling upstream updates

From the repo root, on the `tacho-bridge-app` branch, clean tree:

```bash
bash tacho-bridge-app/scripts/sync-upstream.sh          # upstream master
```

Take upstream's side of any conflict, then re-apply the overlay:

```bash
python tacho-bridge-app/scripts/apply-overlay.py tacho-bridge-app 0.8.x-dh.1 "$(cat D:/DHFleetViewData/tacho/bridge/signing/updater.key.pub)"
bash tacho-bridge-app/scripts/check-flespi.sh
```

If upstream changes `communication_protocol.md`, check `bridge_server.py` still
matches it.

## Building and publishing a release

On the server (everything stays on D:):

```bash
bash tacho-bridge-app/scripts/build-local.sh
cd C:/tachograph-server && .venv/Scripts/python -m scripts.publish_bridge_release \
  D:/tools/wt-tba/tacho-bridge-app/src-tauri/target/release/bundle/nsis --notes "..."
```

Publishing updates the Tachograph page's **Download Tacho Bridge App** button and
the in-app updater. Or push a `tba-v*` tag and let `build-tacho-bridge.yml` build and
deploy (needs the signing-key and SSH secrets).

## Card racks

The app detects Lisle racks, links them and reports their cards to the server.
The rack's own serial command protocol is built **by the server** and is not
public, so the tacho server tracks racks but doesn't drive them yet. Cards in PC/SC
readers work end to end.
