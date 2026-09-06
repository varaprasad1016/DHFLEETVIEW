# Tacho Bridge App — installer drop location

The Tachograph page's **Download Tacho Bridge App (Windows)** button serves the
file at:

    C:\DHFleetView\media\tacho-bridge\TachoBridgeSetup.exe

Until that file exists, the download endpoint returns a friendly "not available
yet" message. Drop the built, code-signed installer here (exact name
`TachoBridgeSetup.exe`) and the button works immediately — no server restart.

## Building the installer (not buildable on this server)

The app is the forked **Tacho Bridge App** (Rust + Tauri + Vue). Build it on a
workstation with the Rust/Tauri toolchain:

1. Clone `github.com/flespi-software/Tacho-Bridge-App` (MIT), pin a commit.
2. Apply the transport fork per `docs/tachograph/` / the tacho-server
   `docs/tba-modifications.md`: replace the flespi MQTT transport with a
   WebSocket client to this server; add `server_address`, `tba_id`, `card_ids`
   config; 30 s heartbeat. Keep all PC/SC card logic untouched (that is what
   reads the company cards from the reader / card rack).
3. Build it with **GitHub Actions** instead of a local toolchain: copy
   `build-tacho-bridge.yml` (in this folder) into the fork at
   `.github/workflows/build-tacho-bridge.yml`, then push a tag like `v1.0.0`.
   The Windows runner compiles the Tauri app and publishes the `.exe`/`.msi` as
   a GitHub Release asset. (Locally it would be `npm ci && npm run tauri build`.)
4. Download the installer from the release, rename to `TachoBridgeSetup.exe`, and
   copy it here — or enable the optional `deploy-to-server` job in the workflow
   to push it here automatically on every build.
