# Tacho Bridge App — fork modifications

Upstream: `github.com/flespi-software/Tacho-Bridge-App` (MIT). Pin the fork to a
specific commit and record it here.

**Pinned upstream commit:** `<fill-in>` (target release v0.7.0, July 2026)

## Principle
Keep **all** PC/SC and card logic untouched — the TBA stays a transparent APDU
proxy. Change **only** the transport (flespi MQTT → our WebSocket) plus the
identity/config it needs to reach us.

## Changes

### 1. Transport: MQTT → WebSocket (`src-tauri/src/transport/`)
- Remove the flespi MQTT client and its `tacho-bridge` channel wiring.
- Add an **outbound** WebSocket client that dials `server_address`
  (e.g. `ws://our-server:8765`) and auto-reconnects with backoff.
- Message framing is the JSON protocol our server speaks (see below). The TBA
  never listens; it always connects out to us.

### 2. Identity / config (`src-tauri/src/config/`)
- New config file fields:
  - `server_address` — our WebSocket URL/IP.
  - `tba_id` — this bridge's identity (UUID or string); the server validates it.
  - `card_ids` — mapping of physical card (by ATR or slot) → our `card_id`.
- Remove all flespi API calls, tokens, and channel config.

### 3. Heartbeat & lifecycle
- Every **30 s**, send a `status` message: per-card `present` / `busy` / `atr`.
- On graceful shutdown, notify the server (close the socket cleanly).

### 4. Keep
- PC/SC comms (libpcsclite / native), multi-card (card hotel), auto protocol
  detection (VDO/Stoneridge/Intellic), and the Quasar UI (handy for local
  debugging of card status).

## Wire protocol (server ⇄ TBA)
Exactly what `app/services/tba_bridge.py` implements on our side:

```
Server → TBA   {"type":"apdu_request","request_id","card_id","apdu":<hex>,"timeout_ms"}
TBA → Server   {"type":"apdu_response","request_id","card_id","sw1","sw2","data":<hex>}
TBA → Server   {"type":"status","tba_id","cards":[{"card_id","present","busy","atr"}]}
Server → TBA   {"type":"session_start","session_id","card_id"}
Server → TBA   {"type":"session_end","session_id","card_id"}
```

The server owns the ISO-7816 sequencing; the TBA just executes each APDU against
the physical card and returns `sw1/sw2/data`. Our in-memory mock
(`tests/test_services/mock_tba.py`) implements this contract for tests, and a
`websockets`-based mock server can stand in for the real bridge in integration.

## Verification without the fork
`scripts/verify_tba.py` and `tests/test_services/` exercise the whole server-side
contract against the mock — no Rust build, reader, or card required.
