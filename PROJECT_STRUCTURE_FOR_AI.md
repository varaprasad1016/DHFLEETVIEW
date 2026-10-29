# DHFleetView - Full Project Structure for AI

**Generated:** 2026-09-03
**Graphify:** `graphify-out/graph.json` (33270 nodes, 132401 edges) - AST-only, no LLM cost
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
│   ├── config/Keys.java              # Keys: tacho.* (enabled, tunnel.*, vu.*, card.*, forward.*)
│   ├── model/                        # Tachograph* (Configuration, DownloadJob, File, Bridge,
│   │                                 #   AuthSession, Forward, ForwardTarget, Audit) + Device...
│   ├── protocol/                     # TeltonikaProtocolDecoder.java (io239 = ignition)
│   ├── schedule/                     # TaskTachographScheduler / Recovery / Forwarder
│   ├── session/ConnectionManager     # getDeviceSession for FMC650 status
│   └── tachograph/                   # See "Tachograph module" below
├── schema/changelog-*.xml            # Liquibase: 6.16.0 + 6.17.0 add tc_tachograph_*
├── conf/traccar.xml                  # tacho.* (documented inline), cmsv9.*
├── tacho-bridge/                     # Windows bridge app (Java 17, javax.smartcardio, PC/SC)
│   └── src/main/java/com/dhfleetview/bridge/   # Main, ServerClient, *SmartCardReader
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
| `src/main/java/org/traccar/tachograph/` | Tachograph module, see below |
| `src/main/java/org/traccar/model/Tachograph*.java` | 8 models |
| `traccar-web/src/tachograph/` | Web app section: 6 tabs + stat cards |
| `tacho-bridge/.../bridge/Main.java` | Bridge: pairing, heartbeat, card relay loop |

## Tachograph module

Remote DDD download from FMC650 vehicles, company-card authentication via an office bridge, and
delivery to analysis bureaux (Convey Reporting). **Read `docs/tachograph/ARCHITECTURE.md` first.**

| Package | Responsibility |
|---|---|
| `tachograph.protocol` | Annex 1B download protocol: `VuMessage` framing, `VuDownloadSession`, `DddFileBuilder`, `DddInspector`, `TrepType`, `ContinuationMode` |
| `tachograph.tunnel` | `TachographTunnelServer` (Netty, `tacho.tunnel.port`), `TunnelConnection`, registry |
| `tachograph.device` | `Fmc650TachographClient`, `VirtualVehicleUnit` (emulator), `VuDownloadRunner` (shared) |
| `tachograph.card` | `RemoteCardService` (APDU relay + long poll), `CardApdu`, `CardIdentityReader` |
| `tachograph.forward` | `TachographForwardService`, `SftpForwarder`, `HttpsForwarder`, `SecretCipher` |
| `tachograph` | `TachographManager` (jobs), `TachographBridgeManager`, `TachographStorage`, audit |

Three things to know before changing any of it:

1. **No card cryptography anywhere.** The vehicle unit and the company card authenticate each
   other; the server relays bytes and holds no keys. Do not add key handling.
2. **The simulator shares the production code path** (`VuDownloadRunner` over a `VuChannel`).
   Keep it that way — it is what makes the module testable without hardware.
3. **`tacho.vu.continuationMode`** is the one genuinely deployment-dependent value. See
   `docs/tachograph/VU-PROTOCOL.md`.

Gotcha: the storage layer writes a zero `*Id` column as SQL NULL, so such columns must be
nullable wherever zero is meaningful (group zero = whole server). See `docs/tachograph/DATABASE.md`.

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
6. Tachograph: read `docs/tachograph/ARCHITECTURE.md` before touching that module. It is the
   largest subsystem and the one with real compliance consequences.
7. `./gradlew build` runs checkstyle (120 cols, LF, no unused imports) and must stay green.
8. Frontend uses MUI 9, where `<Grid item xs>` no longer exists. New layout code uses CSS grid.
   Run `npx eslint --fix` on anything you touch; prettier is enforced.

## Verified end to end

The tachograph module was exercised against a running server on an isolated database: user and
device creation, a vehicle download completing through the emulator, metadata extracted from the
DDD, SHA-256 matching between database, response header and bytes, the audit trail, bridge
pairing and token authentication (including rejection of bad and reused credentials), a full
company-card APDU relay round trip, and delivery queueing with retry scheduling.

Not yet verified, because each needs hardware or an account: the FMC650 trigger command syntax,
`tacho.vu.continuationMode` against a real vehicle unit, live card authentication, and a
successful transfer to a real bureau. See `docs/tachograph/TESTING.md`.

---
*Generated via `graphify update . --no-cluster` + manual tree. Give this file + `graphify-out/graph.json` to any AI for full context.*
