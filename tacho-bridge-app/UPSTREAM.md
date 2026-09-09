# Tacho Bridge App — fork & upstream

This is DH FleetView's fork of the **Tacho Bridge App**
([flespi-software/Tacho-Bridge-App](https://github.com/flespi-software/Tacho-Bridge-App),
MIT, default branch `master`). It runs on the card-rack PC and proxies company-card
APDUs during remote tacho downloads.

## What we changed (the overlay — must survive every upstream sync)

| Area | Upstream (flespi) | This fork |
|------|-------------------|-----------|
| Transport | Per-card **flespi MQTT** (`rumqttc`, `mqtt.rs`, `app_connect.rs`) | A single multiplexed **WebSocket** to the DH FleetView tacho-server (`src-tauri/src/websocket.rs`, `tokio-tungstenite`) |
| Server target | flespi broker | The DH FleetView server only (host from app config → WS URL) |
| Update check | Polls `flespi-software/Tacho-Bridge-App` releases | Polls **our** releases (tags `tba-*`) and points users to `dhfleetview.co.uk` (`logger.rs`) |
| Bundle id | `com.flespi.tba.dev` | `com.dhfleetview.tachobridge` (`tauri.conf.json`) |
| Repo metadata | gurtam/flespi | this repo (`Cargo.toml`) |

PC/SC / smart-card logic (`smart_card.rs`, APDU handling) is kept as close to
upstream as possible so their fixes merge cleanly.

## Guarantee: no flespi association

`scripts/check-flespi.sh` fails if any flespi/MQTT association appears (flespi.io,
`mqtt.flespi`, `rumqttc`, the flespi releases URL, `com.flespi.*`, gurtam, or a
re-added `mqtt.rs`/`app_connect.rs`). It runs in CI on every push/PR
(`.github/workflows/tacho-bridge-guard.yml`) and should be run after every sync.
So even though upstream is a flespi app, a sync can never ship a flespi build.

## Pulling upstream updates

From the repo root, on the `tacho-bridge-app` branch, clean tree:

```bash
bash tacho-bridge-app/scripts/sync-upstream.sh          # upstream master
```

This adds the `upstream-tba` remote and does a `git subtree pull` into
`tacho-bridge-app/`. Because our transport diverges from upstream's, **review each
sync**: resolve conflicts in our favour (keep `websocket.rs` + server config, drop
MQTT), then run `scripts/check-flespi.sh` — it must pass — before building. The
first sync of the vendored folder can be conflict-heavy; later ones are cleaner.

## Building a release

Bump the version in `src-tauri/Cargo.toml` + `src-tauri/tauri.conf.json`, then push
a `tba-v*` tag. CI (`build-tacho-bridge.yml`) builds the Windows installer, runs the
guard, and deploys it to the server's download button.
