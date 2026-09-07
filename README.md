# Tachograph Server

Self-hosted remote tachograph DDD download platform — a clean-room replacement
for Teltonika TachoSync. Integrates Teltonika Professional trackers (FMB640,
FMC650, FMM650, FMB641, FMC640) with a **forked** Tacho Bridge App (MIT) for
company-card authentication.

## Two device paths
- **Path A — GPRS `query_ddd`** (Wialon-style, over the standard Teltonika data
  protocol; Codec 8/12/13). Documented and open; the recommended primary.
- **Path B — TachoSync binary** (TCP 29000). Proprietary; the wire format here is
  **ASSUMED** from public references and must be confirmed against Teltonika's
  spec before production.

Card I/O is **not** in this codebase — the forked TBA owns all PC/SC access and
we relay APDUs to it over WebSocket/TCP.

## Status

| Phase | Scope | State |
|-------|-------|-------|
| 1 | Foundation + Path B protocol handler | **code complete** (infra boot pending) |
| 2 | TBA bridge + card session | **code complete** (verified in-process) |
| 3 | Path A (`query_ddd`) | **code complete** (verified in-process) |
| 4 | Core services (schedule/compliance/files/SFTP/webhooks) | not started |
| 5 | React frontend | not started |
| 6 | Hardening + deployment | not started |

### Phase 1 — done so far (verified)
- `app/protocol/crc.py` — chained CRC-16 (poly 0x8408). **Verified** against the
  X.25 known-answer vector `0x906E`.
- `app/protocol/packets.py` + `fields.py` — framing, init-packet, metadata.
  **Verified** round-trip incl. chained-CRC seed rejection.
- `app/protocol/tacho_server.py` — TCP 29000 server driving the full transfer
  sequence (path → metadata → file request → start → sync → data → status →
  close), with injected deps so it runs infra-free.
- `tests/test_protocol/mock_device.py` — mock Teltonika device.
- **End-to-end verified** (`scripts/verify_transfer.py`, 7/7 PASS): multi-chunk
  file transferred and stored byte-identical; unknown IMEI closed with no store.
- `app/main.py` (`/health`), `app/database.py`, `app/config.py`.
- Project skeleton, `docker-compose.yml`, `Dockerfile`, `requirements.txt`,
  `.env.example`.
- Tests: `test_crc.py`, `test_packets.py`, `test_tacho_server.py`.

### Phase 1 — remaining
- `docker compose up` + `alembic upgrade head` end-to-end boot check (needs a
  host with Docker/Postgres; every file is syntax-checked and the protocol is
  verified in-process, but the DB boot itself is unrun here).

### Persistence (done — code complete)
- `app/models/` — all 12 tables (`core.py`, `operations.py`, `integrations.py`).
- `alembic/` — async `env.py` + hand-written `0001_initial` migration.
- All modules pass `python -m py_compile`.

## Run tests
```
pip install -r requirements.txt
pytest
```

## Important
Every ASSUMED wire constant lives in `app/protocol/` (`crc.py`, `packets.py`) so
a single correction from the real Teltonika spec updates the whole system. Do
not scatter protocol constants elsewhere.
