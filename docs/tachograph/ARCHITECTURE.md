# Tachograph Architecture

## Verified behaviour

- Traccar 6.15.2, Java 21, Guice + Jersey + Jetty 12, H2 + Liquibase.
- Device model `tc_devices`, groups `tc_groups`, permissions via `PermissionsService`.
- Commands: `CommandsManager` / `CommandResource` (`/api/commands/send`) → `QueuedCommand` over the device TCP session.
- Scheduler: `ScheduleManager` (4-thread pool), `SingleScheduleTask` subclasses.
- Frontend: React + MUI + Redux (`traccar-web`), vite, PWA; routes in `Navigation.jsx`.

## Added architecture (this module)

```
FastHosts Server
  Traccar backend (Java)
    TachographManager  - job state machine, retry, recovery
    TachographStorage  - filesystem abstraction
    TachographResource - REST API
    TaskTachographScheduler / TaskTachographRecovery
    TachographAuthenticationProvider (interface)
      MockAuthenticationProvider (simulator, TEST ONLY)
    TachographDeviceClient (interface)
      SimulatedTachographDeviceClient (FMC650 stub)
  H2 Database (tc_tachograph_*)
  Local filesystem (/data/tachograph)
  Frontend (React)
    TachographPage (dashboard, history, bridges)

Customer site (Windows)
  tacho-bridge (Java, javax.smartcardio)
    PcscSmartCardReader / MockSmartCardReader
    BridgeClient (HTTPS to server)
```

## Assumptions

- The real FMC650 tachograph relay protocol is NOT implemented - see `FMC650-INTEGRATION.md`.
- Card private keys never leave the bridge.
- Bridge uses outbound HTTPS only (no customer port-forward).

## File table

| File | Purpose |
|---|---|
| `model/Tachograph*.java` | DB models |
| `tachograph/TachographManager.java` | Job engine |
| `TachographStorage.java` | Filesystem |
| `api/resource/TachographResource.java` | REST |
| `schedule/TaskTachograph*.java` | Scheduler |
| `tacho-bridge/` | Windows bridge app |
| `docs/tachograph/*.md` | Docs |
