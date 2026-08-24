# DH FleetView

**Tracking and Live View** — a fully customised fleet tracking and video platform, built on [Traccar](https://www.traccar.org/).

DH FleetView is a complete GPS fleet-tracking and vehicle-video solution for D&H Group Limited:

- **Live tracking** — real-time GPS positions, routes, geofences, reports (Traccar server)
- **CMSV9 video suite** — live camera streams, multi-camera grid, recording playback & download, snapshots (integrated into the web UI)
- **Web app** — fully rebranded modern UI ("DH FleetView / Tracking and Live View")
- **Android app** — branded native wrapper (WebView) with matching icon, loading screen and video support

## Repository layout

| Path | What it is |
|---|---|
| `./` (root) | Traccar **server** source (Java). Runs the GPS platform, database and web server |
| `traccar-web/` | The **web application** (React + MUI + MapLibre). Contains the DH FleetView branding and the **CMSV9 video module** |
| `traccar-manager/` | The **Android app** (Flutter + WebView) — branded "DH FleetView" with the pin badge icon |
| `setup/traccar.xml` | Server configuration template (includes `web.cacheControl=no-cache` so UI updates are picked up immediately) |

## Running the server

The server is a standard Traccar install:

```bash
# build the web app first
cd traccar-web && npm install && npm run build && cd ..

# run the server (Docker)
docker run -d --name traccar \
  -p 8082:8082 \
  -v "$(pwd)/traccar-web/build:/opt/traccar/web" \
  -v "$(pwd)/setup/traccar.xml:/opt/traccar/conf/traccar.xml:ro" \
  traccar/traccar:latest
```

Then open `http://localhost:8082`.

## CMSV9 video setup

1. In the app: **Settings → Server → custom attributes**:
   - `cmsv9Url` — your CMSV9 / 808gps platform address
   - `cmsv9Account` / `cmsv9Password` — platform login
   - `cmsv9MediaPort` — media/HLS port (default `6604`)
   - `cmsv9Channels` — cameras per device (default `4`)
2. Per device: tick **Camera device** in the device form and enter the **CMSV9 Device ID**.

The video button then appears on that device's card: **Live** (single camera), **Multi** (grid of all cameras), **Reports** (recordings search/playback/download).

## Android app

`traccar-manager/` is a Flutter app wrapping the web UI. Build:

```bash
cd traccar-manager && flutter build apk --release
```

The APK is configured to load the web app from the server URL set in the app's first-run screen (default `http://10.0.2.2:8082` for the emulator).

## License

Apache License 2.0 (upstream Traccar). See `LICENSE.txt`.
