# DHFleetView - Full Project Structure for AI

**Generated:** 2026-08-31
**Graphify:** `graphify-out/graph.json` (25886 nodes, 104223 edges, 47MB) - AST-only, no LLM cost
**Root:** `C:\DHFleetView` (also `C:/DHFleetView` on WSL)

## Quick Start for Future AI

```bash
# 1. Query the knowledge graph (preferred over grep)
graphify query "how does tachograph download work"
graphify path "TachographManager" "TachographStorage"
graphify explain "FMC650"

# 2. Update graph after code changes (AST-only, no API cost)
graphify update .

# 3. Full rebuild with clustering (requires GEMINI_API_KEY)
graphify update . --no-cluster  # current graph is AST-only
```

**Graphify Plugin:** Installed via `graphify opencode install` + `@javargasm/opencode-graphify` (global `~/.config/opencode/opencode.json`). Available as `/graphify` TUI and 12 native tools in OpenCode.

## Repository Layout

```
DHFleetView/                          # Traccar server (Java, Gradle, tracker-server.jar)
├── src/main/java/org/traccar/       # Server source (protocols, models, storage, tachograph)
│   ├── api/resource/                 # REST: TachographResource.java (+ 30 others)
│   ├── config/Keys.java              # Keys: tacho.enabled, tacho.storagePath, tacho.simulator, etc.
│   ├── model/                        # Tachograph* + Device, Group, Position
│   ├── protocol/                     # TeltonikaProtocolDecoder.java (io239 = ignition)
│   ├── schedule/                     # TaskTachographScheduler, TaskTachographRecovery
│   ├── session/ConnectionManager     # getDeviceSession for FMC650 status
│   └── tachograph/                   # TachographManager, Storage, DeviceClient, AuthProvider
├── schema/changelog-*.xml            # Liquibase: changelog-6.16.0.xml adds tc_tachograph_*
├── conf/traccar.xml                  # tacho.enabled=true, tacho.simulator=true, cmsv9.*
├── tacho-bridge/                     # Windows bridge app (Java, javax.smartcardio, PC/SC)
│   └── src/main/java/com/dhfleetview/bridge/
├── traccar-web/                      # Web app (React 19 + MUI 9 + MapLibre, Vite)
│   ├── src/
│   │   ├── common/util/vehicleStatus.js  # NEW: ignition -> running/idling/parked/stopped
│   │   ├── main/                     # MainPage.jsx, DeviceList/Row, FleetDashboard, useFilter
│   │   ├── map/                      # MapMarkers, preloadImages, MapPositionMarkers
│   │   ├── settings/DevicePage.jsx   # Icon gallery (22 categories)
│   │   └── resources/l10n/en.json
│   ├── build/                        # Vite outDir (not tracked, !traccar-web/build in .gitignore)
│   └── package.json                  # 6.15.2, vite, pwa
├── traccar-manager/                  # Flutter WebView wrapper (Android + iOS)
│   ├── lib/main_screen.dart          # kDefaultUrl = https://dhfleetview.co.uk
│   ├── pubspec.yaml                  # 1.0.3+4
│   └── android/                      # Gradle KTS, signing via environment/dhfleetview.keystore
├── web/                              # Built web assets (tracked, 399 files, index-DtiGTNxw.js)
├── docs/tachograph/                  # 8 markdown files (ARCHITECTURE, FMC650-INTEGRATION, etc.)
├── graphify-out/                     # Knowledge graph (tracked)
│   ├── graph.json (47MB, 25886 nodes)
│   ├── manifest.json
│   └── cache/ast/
├── .github/workflows/
│   ├── build-mobile.yml              # Builds AAB/APK + publish to Play (com.dhgroup.fleetview)
│   ├── gradle.yml / release.yml
│   └── traccar-manager/.github/...
├── deploy/, docker/, setup/traccar.xml, templates/, tools/
└── PROJECT_STRUCTURE_FOR_AI.md       # This file
```

## Key Domains

| Path | Purpose |
|------|---------|
| `traccar-web/src/common/util/vehicleStatus.js` | Ignition fallback (ignition, ign, io239, io1, di1, din1, acc) + getVehicleStatus |
| `traccar-web/src/main/MainPage.jsx` | Fleet list default on mobile (fleetView), filter chips |
| `traccar-web/src/main/FleetDashboard.jsx` | Clickable stats (running/idling/parked/stopped/offline) |
| `traccar-web/src/main/DeviceRow.jsx` | Avatar gray (ign OFF) / green (running) via vehicleStatus |
| `src/main/java/org/traccar/tachograph/` | TachographManager (690 lines), Storage, Simulator |
| `src/main/java/org/traccar/model/Tachograph*.java` | 5 models (Configuration, DownloadJob, File, Bridge, AuthSession) |
| `tacho-bridge/src/main/java/com/dhfleetview/bridge/Main.java` | Bridge heartbeat + pairing |

## Build & Deploy

```bash
# Web
cd traccar-web && npm run build && cp -r build/* ../web/  # web kept for jar

# Server (Java 21)
./gradlew build --no-daemon

# Mobile (requires Flutter 3.47.1, keystore env)
# GitHub Actions: tag v* -> build-mobile.yml -> Play Store draft
git tag v1.0.3 && git push origin v1.0.3  # -> production draft 1.0.3 (4) committed via API

# Graphify
graphify update . --no-cluster  # AST-only
graphify query "question"       # BFS traversal
```

## Secrets & Config

- `conf/traccar.xml`: database.url=./data/database (H2), tacho.* keys, cmsv9.*
- `environment/dhfleetview.keystore` (gitignored) + `environment/key.properties`
- GitHub Secrets: `KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_PASSWORD`, `SERVICE_ACCOUNT_JSON` (dh-fleet-view@nifty-artwork-463114-t6.iam.gserviceaccount.com)
- Service Account JSON: `C:\Users\Administrator\Downloads\nifty-artwork-463114-t6-63b983cc60ee.json` (delete after use)

## Recent Commits

- `eefc76e` Bump to 1.0.3+4 - versionCode 3 already used in Closed Testing
- `d1042a2` Hotfix: mobile white-screen - handle null persisted filter
- `8393156` Fleet list on login: ignition-based statuses, icon library, Teltonika support
- `f4ddd85` Tachograph MVP: FMC650 remote DDD download platform

## For Next AI

1. Read `graphify-out/graph.json` stats before broad grep - use `graphify query`.
2. After editing code, run `graphify update .` to keep graph current.
3. Check `traccar-web/src/common/util/vehicleStatus.js` for ignition logic before touching fleet status.
4. Mobile default URL is `https://dhfleetview.co.uk` - dev URLs auto-migrated.
5. Play Store package `com.dhgroup.fleetview`, version in `traccar-manager/pubspec.yaml`.

---
*Generated via `graphify update . --no-cluster` + manual tree. Give this file + `graphify-out/graph.json` to any AI for full context.*
