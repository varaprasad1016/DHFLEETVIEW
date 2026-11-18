# Handover — DH FleetView / Infomac

Updated 14 October 2026. For an agent picking this up cold.
`PROJECT_STRUCTURE_FOR_AI.md` has the layout; this file is **current state and
live problems**.

---

## 1. Standing constraints (from the user, non-negotiable)

- **Never push local commit `623075c0`** to a remote without asking first.
- Keep data (DBs, files, logs, backups, deploy copies, temp) on **D:**, not C:.
- **Never print secrets**: DB passwords, the updater private key, `DVR_SMS_KEY`,
  `cmsv9.mediaSecret`, the frp token, `TRACCAR_API_TOKEN`, SMTP, Caburn or
  TachoSync credentials. Refer to them by name and location.
  Writing a key the user supplies into `.env` on their own server, at their
  request, is normal administration and was done for `TACHOSYNC_API_KEY` on
  14 Oct when they could not RDP in. Transcribing passwords out of screenshots
  is still refused.
- Confirm before restarting Traccar, rebooting a tracker (`cpureset`), or
  changing security settings. The user has approved each of these individually;
  none of those approvals carries to the next occasion.

---

## 2. The live blockers

### A. iOS app rejected — awaiting your reply to Apple

Submission `637517d1-2a6d-499c-ac8d-0f76a291bf8c`, build **1.0.5 (113)**,
rejected 30 Sept on three guidelines. **Two are fixed; one needs the user to
send a reply.** Unchanged since 6 October.

| Guideline | State |
|---|---|
| **3.1.1** registration = external purchase route | **Fixed.** Server flag `registration` set to false. |
| **1.5** Support URL not a support page | **Fixed.** `https://dhfleetview.co.uk/support.html` is live. |
| **2.1** Information needed (7 business questions) | **Reply drafted**, not sent — `handover/appstore-2.1-reply.md`. |

Before sending: confirm the £10 / £20 per-vehicle-per-month figures, decide
whether support contact moves from `admin@` to `support@`, and **change the
Support URL in App Store Connect**. No new build needed.

### B. Tachograph DDD download — now outsourced to TachoSync, stuck on one step

**This changed completely on 13–14 October. Read this before touching anything
tacho.**

The first FMC650 is **fitted and working** on **PJ19FBK** (IMEI
`860848081764038`, firmware `03.01.01.Rev.15`, hardware FMC650 HW:17).

**Live tachograph data works** and is in the app: driver name, working state,
driving-until-break, left today/week/fortnight, rest figures. It arrives as
unmapped `io<AVL ID>` position attributes and is decoded client-side. Nothing
about the download blocker affects it.

**The DDD file download does not work from our own server, and cannot.**
Teltonika's WEB Tacho server half is proprietary. Established by observation:

- The unit connects to whatever `201`/`202` point at, announces a Codec 12
  type-**0x10** message containing `STATUS`, then heartbeats a single `0xEF`
  byte every 30 s for 3 minutes and hangs up.
- It ignores anything it does not recognise — five ASCII verbs and five binary
  "EF request" framings produced **no change in behaviour at all**.
- Type 0x10 is not in the public Codec 12 spec (which documents only 0x05
  command / 0x06 response), and the FMC650 command list has no download command:
  only `tachocheck` and `tacho_connect`.
- Teltonika's own WEB Tacho page describes a hosted service — device to
  `ddd.teltonika.lt:29000`, company card PC to `:29002`, their server brokering
  the card authentication into the tachograph. There is no self-host route.

**So the unit now points at Teltonika's TachoSync service** and we fetch the
finished files back through their REST API (section 9).

```
200 = 1                 WEB Tacho enabled
201 = tacho.teltonika.lt
202 = 29000
203 = 5                 start delay, minutes
```

**Where it is stuck (14 Oct):** TachoSync's download history shows attempts
reaching the **Authentication** stage and stopping with *"Card reading error.
Please reinsert the company card, reconnect the card reader, or restart the
service."* The user has since installed TachoSync's own card reader and it shows
**Online** on their side — but the unit then refused new attempts with:

```
"Conditions not correct  Ignition: 1, task already running: 1, enabled: 1, domain: 1"
```

A stale WEB Tacho task from the failed attempts is held in the unit. A
`cpureset` and a `setparam 1000:1800` are **queued** and will apply at its next
check-in; the vehicle switched off at 11:49 UTC on 14 Oct and now reports only
hourly (section 5), so it may be up to an hour.

**Our own Tacho Bridge App cannot help here.** It is flespi's card reader,
forked, and it presents the card to *this* server. TachoSync needs its own
reader software against their service. Both can run; they are separate paths.

**Do not resume the old self-hosted download work** (`TachographManager.java`
still fails to compile on every branch — duplicate `cancelJob`, missing
`queueForwarding` and `bridge`; port parked in
`D:\DHFleetViewData\worktrees\fmc650-merge`). It was aimed at a protocol we now
know is not ours to implement.

---

## 3. What a Teltonika unit needs (this works)

Server side: `protocols.enable = osmand,teltonika`, Windows firewall off.

**Port is 9007, not 5027.** 5027 is filtered by the IONOS cloud firewall — an
external check reports it filtered while the listener is up. 9007 is the one
free port inside 9003–9007, a range already open for CNMS. Borrowed, not owned:
move back to 5027 when that port is opened, which is one line in `traccar.xml`,
a restart, and `setparam 2005:5027` per unit.

1. Add the device with **Identifier = the IMEI**, digits only.
2. Set on the unit:

```
  setparam 2001:<APN>
  setparam 2004:dhfleetview.co.uk
  setparam 2005:9007
  setparam 2006:0
```

**SMS wants the `<login> <password> <command>` form — two leading spaces with no
password set. GPRS does not.** Over GPRS commands go bare: `getver` works,
`  getver` returns `#ERROR`. This cost hours on 13 Oct.

### Commands over GPRS — no SMS needed

Traccar sends Codec 12 commands to a connected unit, and this works today:

```bash
POST /api/commands/send
{"deviceId": <id>, "type": "custom", "attributes": {"data": "getver"}}
```

HTTP 200 = sent to the live socket; **202 = queued** until the unit next
connects. The reply comes back in `tracker-server.log` as a `0c0106…` frame —
decode the hex after the 4-byte length. Useful: `getver`, `getparam <id>`,
`setparam <id>:<value>`, `tachocheck`, `tacho_connect`, `cpureset`.

### Parameters that matter (FMC650 — numbering differs from FMB1xx)

| ID | Meaning | Ours |
|---|---|---|
| 1000 | Open Link Timeout (s) | 1800 queued 14 Oct |
| 10000 / 10005 | Stopped: min period / send period | 3600 / 3600 |
| 10050 / 10055 | Moving: min period / send period | 60 / 60 |
| 10051 / 10052 | Moving: min distance / min angle | 0 / 0 |
| 200–203 | WEB Tacho enable / domain / port / start delay | see section 2B |
| 204 | Tachograph ignition source | 0 |

**`10051` min distance was why the unit sent a record every ~5 seconds** — 100 m
at motorway speed is four seconds, so distance, not the timer, was driving it.
6,608 records in 24 h before, roughly 400 expected now.

---

## 4. Recently resolved — do not re-investigate

### 12–14 October

- **Fleet "offline", GPS wrong (12 Oct, ~3½ hours).** IONOS had no rule for TCP
  **9808** (CNMS gateway). Cameras dropped naturally from 04:28 and could not
  reconnect; the gateway logged nothing because it never saw the attempts. The
  user opened 9808 and the count went 1 → 13 → 15 in four minutes. **Not** the
  channel-count change, which was reverted for nothing.
- **DVR GPS overwrote live tracker fixes every 15 s.** `TaskCnmsSync`'s
  tracker-preference check read the *session cache*, and a Teltonika unit holds
  no session between batches, so it always found nothing. It reads the stored
  position now and never writes a DVR fix older than the one on the device.
  Counter went `0 tracker-preferred` → `1`, and PJ19FBK stopped flipping between
  a live fix and a camera fix 50 km away.
- **Every camera timestamp was an hour ahead through BST.** CNMS serves UK local
  time; `parseCnmsTime` read it as UTC. Now `Europe/London`. Verified against
  CNMS's own clock. **Positions stored March–October keep the error.**
- **Ignition was stuck on for PJ19FBK** — 0 of 10,900 records showed it off. The
  ignition source was Power Voltage with the 12 V-vehicle default window
  (13.2–30 V); a 24 V truck sits at 25.5 V parked, permanently inside it. The
  user set it to **DIN1** and it now follows reality (verified: false at rest,
  true driving, matching the alternator voltage pattern).
- **An offline vehicle showed a green "running" engine** — `DeviceRow.jsx`
  coloured it from the ignition attribute alone, which freezes when a unit goes
  quiet. Grey when offline now, with the tooltip saying "when last heard from".
  (`getIgnitionColor` in `vehicleStatus.js` is dead code — fixed to match, but
  it is not what renders.)
- **TachoSync init packet parsed the IMEI from the wrong offset.** Our code
  assumed `Header+ProtoID+IMEI(8)+Settings`; the unit sends Teltonika's standard
  `length(0x000F) + 15 ASCII digits`. Reading from offset 4 produced
  `3038343830383137` = "08480817", the middle of the real number — so every
  hourly check-in was turned away as an unknown unit, silently, for a night.

### Earlier

- **Live video black on four cameras** — stream names pad the device number to
  **11 digits** (`canonicalTerminal`, `%011d`). The CNMS `mediacontrol` call
  still sends `"0" + terminal` deliberately.
- **Traccar wedged on H2** (1 Oct, 11½ h). Service recovery configured;
  **untested**. Real fix is migrating off H2 to the MySQL already on the box.
- **Parameter Config** works; needs the camera online. Order `8300` takes
  `content` as an object.
- **`result == 4` / `校验错误` on the CNMS WebSocket is NOT an error** — it is
  what triggers the order send.
- **Server reboot button removed**; `POST /api/server/reboot` returns 403.

---

## 5. Environment traps

- **Server timezone is Central America Standard Time (UTC−6).** Log timestamps
  are 6 hours behind UTC and 7 behind the user. On 13 Oct this was misread as
  "five hours ago" when the events were two minutes old. The Python logs use
  local time; Traccar's too.
- **A heredoc in this environment collapses `\xNN` escapes into raw bytes.**
  Writing Python through `python - <<'PY'` with `b"\x01"` in a string put a
  literal control byte in the source and broke the module twice. Build bytes
  functionally instead: `bytes([1])`, `bytes(4)`.
- **`schtasks /end` + `/run` fails silently.** Twice the tacho API was "restarted"
  and the old process was still running, so edits appeared to do nothing. Always
  confirm with `Get-Process python | Select Id,StartTime`.
- **The tacho server's own INFO lines go nowhere unless the logger sits under
  `"tacho"`.** `main.py` raises only that tree; `logging.getLogger(__name__)`
  produced a listener that looked silent while it was turning units away.
  Use `logging.getLogger("tacho.<area>")`.
- **Traccar's online/offline follows the TCP socket, not data freshness.** A unit
  that connects, sends and disconnects each minute reads as offline most of the
  time while reporting perfectly. Raise *Open Link Timeout* (param 1000) rather
  than doubting the data.
- **Service worker updates hourly** (`serviceWorkerUpdateInterval`). Test in a
  private window.
- **Anything served from `web/` that the SPA does not route must be in
  `navigateFallbackDenylist`** in `traccar-web/vite.config.js`, or the page
  renders blank. Currently `[/^\/api/, /^\/tacho/, /^\/support/]`.
- **A Traccar restart drops every logged-in session.**
- `C:\DHFleetView\web\assets` accumulates orphaned build output — **2,168 files**
  untracked as of 14 Oct. Eight files in `web/` are *not* build output
  (`compliance.html`, `shifts.html`, `jobs.html`, `driver-shift.html`, the four
  under `web/tacho/`, `support.html`): a `robocopy /MIR` destroys them. Only
  clean inside `web\assets\`.
- **`C:\tachograph-server` is not a git repository.** All of its work — the
  listener fixes, the TachoSync client — exists only on disk. Worth fixing.

---

## 6. Build and deploy

```bash
# Web (no restart, zero downtime)
cd /c/DHFleetView/traccar-web && npm run build
robocopy C:\DHFleetView\traccar-web\build C:\DHFleetView\web /E     # exit <8 = OK

# Java (~20 s restart; the running JVM locks the jar)
cd /c/DHFleetView && ./gradlew.bat build -x test -x checkstyleMain -x checkstyleTest
# back up the jar, Stop-Service traccar, copy target\tracker-server.jar
#   -> C:\DHFleetView\tracker-server.jar, Start-Service traccar
```

**Verify what a Java change actually ships** before restarting — compare the
built jar against the running one entry by entry:

```bash
unzip -v tracker-server.jar | awk 'NF>7 {print $8, $7}' | sort > running.crc
unzip -v target/tracker-server.jar | awk 'NF>7 {print $8, $7}' | sort > built.crc
diff running.crc built.crc        # expect only the classes you touched
```

- Jar backups `D:\DHFleetViewData\backups\` (and `traccar\jar-backups\`)
- Traccar log `D:\DHFleetViewData\traccar\logs\tracker-server.log`
- Tacho API log `D:\DHFleetViewData\tacho\logs\api.log`
- Tacho API is a **scheduled task**: `schtasks /end /tn tacho-api` then `/run`,
  then confirm the PID changed

---

## 7. Open items

- **RDP: the Administrator password expired 22 June 2026** (max age 42 days) and
  with NLA on, an expired password is refused during the handshake — you never
  reach the change-password prompt. The user could not get in on 14 Oct. Unblock
  with `Set-LocalUser -Name Administrator -PasswordNeverExpires $true`, or set a
  new password from the IONOS console. **Not yet done — awaiting the user.**
- **3389 is open to the internet and under constant brute force** — 108 attempts
  from one IP in 12 hours on 14 Oct, lockout threshold "Never". Nothing has got
  in. Restrict 3389 to the user's own IP in the IONOS firewall.
- **Caburn SIM portal rejects our login** (`Invalid Password` for known-good
  SIMs; username `DHGroup.Live` is live). Blocks DVR setup SMS and SIM
  activation. The tracker SIM's SMS works through the user's own portal.
- **Ports still to open at IONOS: 5027** (Teltonika's own, so 9007 can be given
  back) and **29000** (TachoSync's documented port, if we ever listen again).
  2102 is open and reachable, verified externally.
- **Rotate the credentials that were in public git history** —
  `database.password`, `cmsv9.mediaSecret`, the CNMS account.
- **`tacho-bridge-app` has diverged from its remote.** The remote carries ten
  commits from 17 Sept (Tacho Bridge App port to upstream v0.8, flespi guards,
  sync CI) that were never pulled here; this box has five the remote lacks.
  14 Oct's work went to branch **`tacho-live-20261013`** instead. Reconciling
  the two is a deliberate job, not a merge to improvise.
- **White-label repo is current** — `varaprasad1016/White-Label-Tracking`,
  `main` at `ed78dd7`. Its web app builds; its **Java tree does not compile**
  (the same `TachographManager` faults). One brand leak remains:
  `DevicePage.jsx:268` hard-codes `dhfleetview.co.uk` for the camera web link.
- **Junk account id=100** (`9977b2b62d3f…@example.org`): invoice `DH-2026-0002`
  fails hourly, forever. Delete it or give it a real email.
- **CNMS `UserSvr` restarts repeatedly**, never diagnosed. Ask before reading
  `D:\CMSServer\Log`.
- **Live video plays on mobile but not in the desktop browser (14 Oct, open).**
  Server side proven: `mediacontrol` returns `errCode 0` and valid URLs, the
  deployed bundle is current, 4022 presents a valid Let's Encrypt certificate.
  Prime suspect is the PC's network blocking outbound **4022**. The real fix is
  to proxy the FLV through Apache on **443** (`/live` → `127.0.0.1:4022`) and
  have `buildLiveFlvUrl` return that — removes the odd port for every customer.
- **Trade mark**: register **Infomac Solutions**, not "DH FleetView"
  (descriptive, and collides with Fleetview Solutions Ltd and PowerFleet's
  FleetView™). CITMA clearance search recommended first.
- **About panel** credits Infomac with no upstream Traccar credit — permitted
  only because upstream ships no `NOTICE` file (Apache 2.0 §4(d)). **Do not
  strip per-file copyright headers or `LICENSE.txt`.**

---

## 8. TachoSync integration (built 14 Oct)

Teltonika's hosted service does the download; we keep the files.

- **Account**: D&H Group Ltd. PJ19FBK registered, "Quick schedule" assigned.
- **Key**: `TACHOSYNC_API_KEY` in `C:\tachograph-server\.env`. Company-scoped,
  sent as `X-API-KEY`. Shown once by their portal; if lost, delete and recreate.
- **Spec**: `https://api.tacho.teltonika.lt/swagger/v1/swagger.json` (the
  `/api-docs/v1` page renders client-side and is useless to fetch).
- **Client** `app/services/tachosync.py` — company, vehicles, vehicle/driver
  files, downloads history, file content, and `sync()` which pulls new files
  through `download_ingest` (de-duplicates by sha256, so it is safe to repeat).
- **API** `app/api/tachosync.py` — `/api/tachosync/overview`, `/files`,
  `/files/{kind}/{id}`, `POST /sync`. Manager + licence gated.
- **Page** `/tacho/downloads` (`app/static/downloads.html`): vehicles with status
  and last download, the failure reason when there is one, the file list, and a
  "Fetch new files" button. Linked from the tachograph panel on the video page.

The downloads history is the only place that says *why* a download did not
happen. Read it before touching the unit.

---

## 9. Live tachograph data (working)

The decode exists three times and the AVL IDs must match across all of them:

- `traccar-web/src/common/util/fmc650Tacho.js` — the app's decoder
- `tachograph-server/app/services/fmc650.py` — the server's ingest decoder
- `DHFleetView .../api/resource/TachographResource.java` — the ID set used to
  merge records server-side

Values are sent **on change**, so any single position carries only what moved and
a parked vehicle sends records with none of them. Hence
`GET /api/tachograph/live/{deviceId}` (one vehicle, 24 h, ~5,000 records
scanned) and `GET /api/tachograph/live` (every tacho-capable vehicle, for the
list) which merge newest-first and return about sixty values.

The panel (`TachoOverlay.jsx`) sits over the map on the video page, draggable and
closable, seeded from that endpoint so a parked lorry still shows the driver's
hours. The vehicle list shows the driver's name beside a plate-styled
registration.

**Known gap:** the driver card *number* arrives as a 64-bit integer that JSON
cannot carry exactly, so the app shows the holder's name and "card inserted"
rather than a number. Fixing it properly is a few lines in the Teltonika decoder
and a Traccar restart.

---

## 10. Mistakes made here — do not repeat

- **Watch filters too narrow, twice in one night.** A background watch grepped
  for "Device connected" and missed "a unit with IMEI … tried to connect", so
  hourly check-ins went unnoticed for hours. Another counted the unit's own
  `STATUS` as a new response and reported success that had not happened. When
  waiting on a log, match the failure cases too.
- **Concluded `tacho_connect` did not exist** from an `#ERROR` returned while the
  tachograph was asleep. It works when the vehicle is awake. Test under the
  conditions the feature needs.
- **Restarted a service without verifying it restarted**, then drew conclusions
  from code that was not running.
- **Named the wrong function** as the cause of the green-engine bug
  (`getIgnitionColor`, which nothing calls) instead of the markup in
  `DeviceRow.jsx`.
- **Claimed 5027 was reachable** after testing from the server to its own public
  IP — that is loopback and proves nothing about inbound.
- Blamed **H.265** for black video; blamed the **channel-count change** for the
  9808 outage; called `result:4` fatal. All wrong, all expensive.
- Dismissed `curl` reporting `200 (0 bytes)` as a quirk. It was the
  service-worker fallback bug; the user found it.

General lesson: verify against observed behaviour — logs, byte counts, process
state, record cadence — before acting on a plausible theory, and never
generalise from one sample.
