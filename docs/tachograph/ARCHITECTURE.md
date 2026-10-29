# Tachograph Architecture

## The problem

An operator must download every vehicle unit at least every 90 days and every driver card every
28, keep the files for a year, and be able to show an inspector where they went. Doing that by
driving a company card out to each vehicle does not scale past a handful of trucks.

Remote download solves it, and the awkward part is the company card: the regulation requires one
to authorise a download, and it lives in an office, not in the cab.

## The shape of the solution

```
Vehicle                          Server                          Office
────────────────────────────────────────────────────────────────────────────
Tachograph (VU)
  │ K-line
FMC650  ──────TCP tunnel──────►  TachographTunnelServer
                                 TachographTunnelRegistry
                                        │
                                 VuDownloadSession ──── Annex 1B protocol
                                 DddFileBuilder / DddInspector
                                        │
                                 TachographManager  ◄──┐
                                   job state machine    │ card commands
                                        │               │
                                 TachographStorage      │
                                   DDD + SHA-256        │
                                        │          RemoteCardService
                                 TachographForwardService    ▲
                                        │                    │ HTTPS long poll
                                        ▼                    │
                                 Convey Reporting      Tacho Bridge ── PC/SC ── company card
```

**The card never moves.** Its command traffic is relayed to it over HTTPS instead. The vehicle
unit and the card authenticate each other directly; the server is a wire between them, holding no
key material and performing no card cryptography. That is what makes remote download possible
without card secrets leaving the office reader.

## Packages

| Package | Responsibility |
|---|---|
| `tachograph.protocol` | The Annex 1B download protocol: framing, session, DDD assembly, inspection |
| `tachograph.tunnel` | The listener FMC650 units connect to, and the registry of live tunnels |
| `tachograph.device` | Device clients: the real FMC650 one, the emulator, and the runner they share |
| `tachograph.card` | The company-card relay: command queue, long poll, identity reading |
| `tachograph.forward` | Delivery to analysis bureaux: SFTP, HTTPS, credential encryption, retries |
| `tachograph` | Job engine, bridge management, storage, audit |

## Key classes

| Class | Role |
|---|---|
| `VuDownloadSession` | Drives one download: handshake, block requests, retries, multi-message assembly |
| `VuDownloadRunner` | Sequences the blocks and turns a session into a stored file. Shared by both clients |
| `Fmc650TachographClient` | Gets to a usable tunnel: trigger, wait, exclusive lease |
| `VirtualVehicleUnit` | A vehicle unit emulator that answers the real protocol |
| `TachographManager` | Job lifecycle: create, execute, progress, cancel, retry, recover |
| `RemoteCardService` | Routes card commands between a download and the bridge holding the card |
| `TachographBridgeManager` | Pairing, token authentication, liveness, card identity |
| `TachographForwardService` | Delivery queue and target configuration |

## Decisions worth knowing

**Jobs are persistent and restartable.** A download can take half an hour over a mobile link, so
the state that matters lives in the database. A restart mid-download leaves a job that
`recoverStaleJobs` picks up rather than a silent hole in a legally required record. It restarts
rather than resumes: the tunnel and card session are long gone.

**Delivery is a separate queue.** A downloaded file is already a record the operator holds. It
must survive the bureau being unreachable, so a transfer failure delays delivery rather than
losing it.

**The simulator is not a shortcut.** It runs the same `VuDownloadRunner` production uses, over a
channel that speaks the real protocol. A regression in framing, assembly, naming or delivery fails
there first. Its files are stamped so they cannot be mistaken for real ones.

**Cancellation is cooperative.** A running job checks between data blocks and stops at a safe
point rather than being killed part way through writing a file.

**Signatures are not verified here.** That needs the European Root Certificate chain and is the
bureau's job. The server's obligation is to deliver the bytes unaltered, which the stored SHA-256
attests.

## Files

| Path | Contents |
|---|---|
| `src/main/java/org/traccar/tachograph/` | Everything above |
| `src/main/java/org/traccar/model/Tachograph*.java` | Configuration, job, file, bridge, forward, target, audit |
| `src/main/java/org/traccar/api/resource/TachographResource.java` | REST API |
| `src/main/java/org/traccar/schedule/TaskTachograph*.java` | Scheduler, recovery, delivery worker |
| `schema/changelog-6.16.0.xml`, `changelog-6.17.0.xml` | Database schema |
| `tacho-bridge/` | The office bridge application |
| `traccar-web/src/tachograph/` | The web app section |
| `docs/tachograph/` | These documents |

## Further reading

- `VU-PROTOCOL.md` — the download protocol, and the one thing to confirm against hardware
- `FMC650-INTEGRATION.md` — commissioning a vehicle
- `TACHO-BRIDGE.md` — the office bridge and the company card
- `FORWARDING.md` — delivery to Convey Reporting and other bureaux
- `API.md` — the REST surface
- `TESTING.md` — how to exercise it without hardware
