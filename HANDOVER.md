# Handover — DH FleetView / Infomac

Updated 6 October 2026. For an agent picking this up cold.
`PROJECT_STRUCTURE_FOR_AI.md` has the layout; this file is **current state and
live problems**.

---

## 1. Standing constraints (from the user, non-negotiable)

- **Never push local commit `623075c0`** to a remote without asking first.
- Keep data (DBs, files, logs, backups, deploy copies, temp) on **D:**, not C:.
- **Never print secrets**: DB passwords, the updater private key, `DVR_SMS_KEY`,
  `cmsv9.mediaSecret`, the frp token, `TRACCAR_API_TOKEN`, SMTP or Caburn
  credentials. Refer to them by name and location. Refuse to transcribe
  passwords into files.
- Do not add Traccar FMC650 forwarding config until the first FMC650 is fitted.

---

## 2. The two live blockers

### A. iOS app rejected — awaiting your reply to Apple

Submission `637517d1-2a6d-499c-ac8d-0f76a291bf8c`, build **1.0.5 (113)**,
rejected 30 Sept on three guidelines. **Two are fixed; one needs the user to
send a reply.**

| Guideline | State |
|---|---|
| **3.1.1** registration = external purchase route | **Fixed.** Server flag `registration` set to false. The Register link is gone from web and app. No rebuild needed. |
| **1.5** Support URL not a support page | **Fixed.** `https://dhfleetview.co.uk/support.html` is live. |
| **2.1** Information needed (7 business questions) | **Reply drafted**, not sent — `handover/appstore-2.1-reply.md`. |

Before the user sends it they must: confirm the £10 / £20 per-vehicle-per-month
figures (taken from `config.py` `rate_live` / `rate_tacho`), decide whether the
support contact should move from `admin@` to `support@`, optionally supply a
phone number for the page, and **change the Support URL in App Store Connect**
to the `/support.html` address.

No new build is required for any of this — all server-side or metadata, so build
113 stays in review.

**Note:** the unused `NSLocationAlwaysAndWhenInUseUsageDescription` was suspected
as the cause of the delay. **Apple did not raise it.** Still worth removing in
1.0.6 (the app has no `UIBackgroundModes` and no code requesting Always
location), but it is not blocking.

### B. FMC650 tachograph download does not exist in working form

The user has a unit ready to fit. **Tracking will work; tachograph download will
not**, and this is not a settings problem.

`TachographManager.java` **fails to compile on every branch** — `main`,
`tachograph-server`, `compliance-suite-2`, `tacho-live-fmc650`. Verified by
compiling `main` on its own:

```
:827  method cancelJob(long,long) is already defined
:504  cannot find symbol: queueForwarding(TachographFile, TachographDownloadJob)
:962  cannot find symbol: bridge
```

Cause: commit **`1a66b648` "Merge branch 'main' into tachograph-server"** resolved
a conflict by keeping both versions of `cancelJob` (they are genuinely different
implementations) and dropping two referenced members. Before it, `18c5f8bb` had
one definition.

So the feature has **never been built or deployed**, despite
`docs/tachograph/FMC650-INTEGRATION.md` reading like a working commissioning
guide. The deployed jar contains only `MockAuthenticationProvider` and
`SimulatedTachographDeviceClient`; `conf/traccar.xml` has `tacho.simulator=true`.

**The port is already done and waiting** in a worktree:
`D:\DHFleetViewData\worktrees\fmc650-merge` (branch `fmc650-tunnel-merge`,
based on `a9c1d23e`). It contains 45 tachograph files from main, 3 model classes,
the `com.hierynomus:sshj:0.40.0` dependency added to `build.gradle`, and a
**merged `Keys.java`** carrying main's 28 `tacho.*` keys plus the 5 `cmsv9.frp*`
keys from the live branch. Errors are down from dozens to the 4 above.

Repairing it means choosing between two `cancelJob` implementations and writing
`queueForwarding` and the `bridge` field from scratch, on the code path that
produces legally-required driver records. **The user was asked and chose to park
it** ("let us hold that for a while"). Do not invent that logic quietly.

When resumed: rebuild from `18c5f8bb` plus later legitimate changes, then test
against the built-in simulator (`tacho.simulator=true` runs the real Annex 1B
protocol with no vehicle) before any hardware.

**A straight `git merge main` is the wrong approach** — it produces 15 conflicts,
all in the CNMS video files, which is where the hard-won fixes live.

---

## 3. What a Teltonika unit needs for tracking (this does work)

Server side is ready: `protocols.enable = osmand,teltonika`, port **5027**
listening on `0.0.0.0`, Windows firewall off on all profiles.

1. Add the device in DH FleetView with **Identifier = the IMEI**, digits only.
   The server rejects unknown IMEIs.
2. On the unit (SMS format is `<login> <password> <command>`, so with no SMS
   password that is **two leading spaces**):

```
  setparam 2001:<APN>
  setparam 2004:dhfleetview.co.uk
  setparam 2005:5027
  setparam 2006:0
  getparam 2004
  getinfo
  cpureset
```

`2001` APN, `2004` domain, `2005` port, `2006` protocol (0 = TCP); add
`2002`/`2003` for APN credentials. **Parameter IDs vary by firmware — confirm
against the FMC650 manual or use the Configurator for a first unit.** The IMEI
appears in `tracker-server.log` on first contact.

The Python tacho-server's Path A / Path B listeners (ports 21756 / 29000,
`gprs_enabled` / `tachosync_enabled`, both `False`) are a *separate, earlier*
attempt whose own source marks the DDD framing `# ASSUMED`. Do not commission a
vehicle on those.

---

## 4. Recently resolved — do not re-investigate

- **Live video black on four cameras.** The media server names streams with the
  device number padded to **11 digits**. The old code built `"0" + terminal`,
  right only for 10-digit devices; the four `044270960xxx` cameras asked for a
  13-digit name that could never exist. Fixed in `buildLiveFlvUrl`,
  `buildPlaybackFlvUrl` and `liveStreamName` via `canonicalTerminal` (`%011d`).
  The CNMS `mediacontrol` call still sends `"0" + terminal` deliberately — CNMS
  normalises it and streams register from it.
- **Traccar wedged on H2** (1 Oct, 11½ hours): a scheduled-task thread stuck in a
  native H2 write while HTTP still answered 200. Service recovery is now
  configured (`RESET_PERIOD 86400`, restart 5s/15s/60s,
  `FAILURE_ACTIONS_ON_NONCRASH_FAILURES=TRUE`) where there was none. **Untested.**
  The real fix is migrating off H2 to the MySQL already on the box.
- **Parameter Config** (camera's own settings page) works. CNMS sends an `8300`
  order `#FRPSET:<host>,<port>,<token>`, waits ~20 s for the camera to open an
  FRP tunnel, then opens `http://<devID>.<webhost>:<webport>`. Terminal padded to
  12 digits for the order, unpadded as the subdomain. Order `8300` needs
  `content` as an object `{msg: ...}`; other orders take a flat string. **Only
  works when the camera is online** — two "failures" were offline cameras.
- **`result == 4` / `校验错误` on the CNMS WebSocket is NOT an error.** It is what
  triggers the order send. "Fixing" it would break live video.
- **The ZLMediaKit webhooks failing** (`medianotfound`, `medianoview` returning
  `errCode` where `code` is wanted) are real but **not** a cause of anything —
  that config predates the problems by months.
- **Server reboot button removed**; `POST /api/server/reboot` returns 403 instead
  of `System.exit(130)`. It was an off switch, not a reboot.

---

## 5. Environment traps

- **Server timezone is Central America Standard Time (UTC−6)** — 7 hours behind
  the user. Log timestamps do not line up with user reports. Clock *sync* is fine
  (NIST). The scheduler and all report content resolve Europe/London explicitly
  and are unaffected. Recommended: set the server to UK time, at a quiet moment.
- **Service worker updates hourly.** `UpdateController.jsx` uses
  `serviceWorkerUpdateInterval || 3600000`, then shows a toast the user must
  click. **This has wasted several test cycles.** Always test in a
  private/incognito window. Configurable without a code change via the Traccar
  server attribute `serviceWorkerUpdateInterval` (Settings → Server → Attributes).
- **Anything served from `web/` that the SPA does not route must be added to
  `navigateFallbackDenylist` in `traccar-web/vite.config.js`**, or the service
  worker answers with the app shell and the page renders blank. Currently
  `[/^\/api/, /^\/tacho/, /^\/support/]`.
- **The mobile app ships from `main`; server work is on `tacho-bridge-app`.**
  Reading the wrong branch's `Info.plist` caused a wrong diagnosis once.
- **A Traccar restart drops every logged-in session** (in memory). 401s straight
  after a restart mean log out and back in.
- `C:\DHFleetView\web\assets` accumulates orphaned build artefacts (12,779 / 309 MB
  cleared 29 Sept to `D:\DHFleetViewData\traccar\web-assets-quarantine\`). **Trap:**
  eight files in `web/` are not build output — `compliance.html`, `shifts.html`,
  `jobs.html`, `driver-shift.html`, the four under `web/tacho/`, and now
  `support.html`. A `robocopy /MIR` destroys them. Only clean inside `web\assets\`.

---

## 6. Build and deploy

```bash
# Web (no restart, zero downtime)
cd /c/DHFleetView/traccar-web && npm run build
robocopy C:\DHFleetView\traccar-web\build C:\DHFleetView\web /E     # exit <8 = OK

# Java (~20 s restart; the running JVM locks the jar)
cd /c/DHFleetView && ./gradlew.bat build -x test -x checkstyleMain -x checkstyleTest
# back up, Stop-Service traccar -Force, copy target\tracker-server.jar
#   -> C:\DHFleetView\tracker-server.jar, Start-Service traccar
```

- Jar backups `D:\DHFleetViewData\traccar\jar-backups\`
- DB backups `D:\DHFleetViewData\traccar\db-backups\`
- Traccar log `D:\DHFleetViewData\traccar\logs\tracker-server.log`
- Tacho API log `D:\DHFleetViewData\tacho\logs\api.log`
- Tacho API is a **scheduled task**: `schtasks /end /tn tacho-api` then `/run`

---

## 7. Open items

- **Caburn SIM portal rejects our login** — live endpoint answers but
  `query-status` returns `Invalid Password` for known-good SIMs, so it is the
  account not the SIM. Username is live (`DHGroup.Live`), password appears to
  still be the test account's. **Ask Caburn to confirm the API password.** Until
  then: no DVR setup SMS, no SIM activation. (The `.env` `SMS_URL` had the scheme
  twice — `https:https://` — which made every send fail with
  `UnsupportedProtocol`; that is fixed and live.)
- **Junk account id=100**, `9977b2b62d3f…@example.org`, self-registered by a bot.
  Its invoice `DH-2026-0002` has `sent_to = "Khh"` and **fails every hour,
  forever**. Delete the account or give it a real email. Self-registration is now
  off so no more can appear.
- **New camera SJ22FHK** (device `0442795001`, SIM `335339467055`, mobile
  `07940732187`, ICCID `8944303353394670558`) exists in CNMS under "DH Group
  Fleet View" (device 5767 / sim 5773 / vehicle 7184) but was **never added to DH
  FleetView** — do that via the DVR label screen, which uses the operator's own
  session.
- **CNMS `UserSvr` restarts repeatedly**, never diagnosed. `D:\CMSServer\Log` was
  not read — the user declined once; ask before reading it.
- **Invoicing module hidden from the UI** (menu item removed from
  `SettingsMenu.jsx`; restoring needs `ReceiptLongIcon`). Backend still runs.
- **Trade mark**: the user owns **Infomac Solutions**; DH FleetView is a branded
  edition built for a reseller. Advice given: register **Infomac Solutions**, not
  "DH FleetView" — descriptive and colliding with Fleetview Solutions Ltd (West
  Midlands, est. 2006, vehicle tracking and cameras) and PowerFleet's FleetView™.
  A CITMA clearance search was recommended before filing.
- **About panel** states Infomac holds the platform's proprietary and white-label
  rights, with **no upstream Traccar credit** — permitted only because upstream
  ships no `NOTICE` file (Apache 2.0 §4(d) is conditional on one). **Do not strip
  the per-file copyright headers or `LICENSE.txt`**; §4(b)/(c) still require them
  and 1,032 of 1,066 Java files carry Anton Tananaev's copyright.

---

## 8. Mistakes made here — do not repeat

- Blamed **H.265** for black video and nearly had the user reconfigure every
  camera. Jessibuca decodes H.265 over FLV. The real cause was stream naming.
- Called `result:4` on the CNMS WebSocket a fatal auth failure. It is the trigger
  for the order send; "fixing" it would have broken working video.
- **Reverted working code** (`canonicalTerminal`) while hunting a fault that was
  actually Traccar wedged on H2 — and thereby reintroduced the 11-digit bug.
  Generalised from a single camera that happened to work.
- Twice reported Parameter Config broken when the camera was simply **offline**.
- Dismissed `curl` reporting `200 (0 bytes)` on the new support page as a quirk.
  It was the service-worker fallback bug; the user found it instead.
- Read Traccar log timestamps as UK time for most of a session (section 5).

General lesson: verify against observed behaviour — logs, byte counts, process
state — before acting on a plausible theory, and never generalise from one sample.
