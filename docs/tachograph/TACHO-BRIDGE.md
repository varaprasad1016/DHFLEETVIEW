# Tacho Bridge

Customer Company Tachograph Card
  -> Physical Smart Card Reader (PC/SC)
  -> Tacho Bridge (Windows, outbound HTTPS to FastHosts)
  -> FastHosts Server (TachographManager + TachographAuthenticationProvider)
  -> FMC650 -> Tachograph -> DDD -> FastHosts storage

## Bridge application

Location: `tacho-bridge/` (separate Gradle project, Java 17, `javax.smartcardio`).

```
tacho-bridge/
  src/main/java/com/dhfleetview/bridge/
    Main.java              - pairing, heartbeat loop, local status server
    BridgeConfig.java      - bridge.properties next to the JAR
    SmartCardReader.java   - interface
    PcscSmartCardReader.java - PC/SC via javax.smartcardio
    MockSmartCardReader.java - TEST ONLY
    CardInfo.java
```

### PC/SC

The bridge detects compatible readers via `TerminalFactory.getDefault()` (OS PC/SC).
`SmartCardReader` abstraction: `connect()`, `disconnect()`, `isPresent()`,
`getReaderStatus()`, `getCardStatus()`, `transmit(byte[])`, `getCardInfo()`.
A dedicated card-reader abstraction is used - no proprietary reader protocol is assumed.

### Card states

`NO_READER`, `READER_CONNECTED`, `NO_CARD`, `CARD_INSERTED`, `CARD_READING`,
`CARD_READY`, `CARD_ERROR`, `CARD_REMOVED` - reported to the server in each heartbeat.

### Pairing

1. Web app: Tachograph > Bridges > Generate Pairing Code (one-time, 6 digits, 15 min expiry).
2. Bridge: `java -jar tacho-bridge.jar pair <CODE>` -> POST `/api/tachograph/bridges/register`
   with `pairingCode`, `bridgeId` (UUID), `name`, `softwareVersion`.
3. Server returns a bridge token (hash stored in `tc_tachograph_bridges.tokenhash`).
4. Bridge saves `bridgeId` + `bridgeToken` to `bridge.properties`.

Pairing codes: random 6 digits, SHA-256 hashed in DB, single-use, 15 min expiry.

### Heartbeat

Every 30 seconds: `POST /api/tachograph/bridges/{id}/heartbeat`
Header: `X-Bridge-Token: <token>` or `Authorization: Bearer <token>`.
Body: `{readerStatus, cardStatus, softwareVersion}`.
Server updates `lastHeartbeat` / `lastSeenAt` / `status` and may return pending
server instructions (future: auth operations).

### Security

- Bridge uses **outbound HTTPS only** - no customer port-forward.
- `bridge.properties` holds `bridgeToken`; restrict file permissions.
- Local status server binds to `127.0.0.1:8765` only (`/status` JSON).
- Never log PIN, private keys or raw APDU payloads.

### Mock mode

`MockSmartCardReader` + `MockAuthenticationProvider` (server) are `TEST ONLY` and
must never be enabled in production (`tacho.simulator=false`).

## Cryptography - STOP condition

No real card cryptography is implemented. The required tachograph smart-card
specification is not available. See `docs/tachograph/TACHO-BRIDGE.md` stop
condition: build only the architecture, PC/SC detection, presence detection,
mock auth and secure transport. Report the exact missing spec to implement
production authentication.
