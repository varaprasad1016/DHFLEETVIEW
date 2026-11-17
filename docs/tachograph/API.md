# Tachograph API

Two kinds of caller reach these endpoints. **Operators** arrive with a normal user session, and
everything they touch is checked against their device and group permissions. **Tacho bridges**
arrive with a bridge token in a header, can only reach the endpoints under `bridges/{id}/`, and
never see fleet data.

## Overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/tachograph/summary` | Counts for the dashboard, over the caller's visible devices |

## Configuration

| Method | Path | Description |
|---|---|---|
| GET | `/api/tachograph/configuration/{deviceId}` | Settings for a vehicle. Never null; an unconfigured device returns disabled defaults |
| POST | `/api/tachograph/configuration/{deviceId}` | Save settings. Download history is server-owned and ignored on input |

## Downloads

| Method | Path | Description |
|---|---|---|
| POST | `/api/tachograph/download` | Queue a job. Body `{deviceId, downloadType, from?, to?}`. Returns 202 |
| GET | `/api/tachograph/downloads` | List jobs. `deviceId`, `status`, `from`, `to`, `limit` |
| GET | `/api/tachograph/downloads/{id}` | One job, including live `progress` and `progressDetail` |
| POST | `/api/tachograph/downloads/{id}/cancel` | Ask a job to stop. A running one stops at the next safe point |

`downloadType` is `VEHICLE` or `DRIVER`. Dates accept epoch milliseconds or ISO-8601. Requesting a
second job of the same type for a vehicle that already has one in flight returns an error with
`TACHO_ALREADY_RUNNING`.

## Files

| Method | Path | Description |
|---|---|---|
| GET | `/api/tachograph/files` | List files. `deviceId`, `type`, `limit` |
| GET | `/api/tachograph/files/{id}/download` | Stream the DDD file |
| DELETE | `/api/tachograph/files/{id}` | Delete a file. Administrators only |

The download response carries `X-File-SHA256`, the digest recorded when the vehicle produced the
bytes, so a recipient can confirm nothing altered them. Every retrieval is written to the audit
trail. Filesystem paths are never exposed.

Operators are required to keep tachograph data for a year, which is why deletion is an explicit
administrator action and nothing removes files automatically.

## Bridges, operator side

| Method | Path | Description |
|---|---|---|
| GET | `/api/tachograph/bridges` | List bridges in the caller's groups |
| GET | `/api/tachograph/bridges/{id}` | One bridge |
| DELETE | `/api/tachograph/bridges/{id}` | Remove a bridge and drop its queued card work |
| POST | `/api/tachograph/bridges/pairing-code` | Generate a code. Body `{groupId, name}` |
| POST | `/api/tachograph/bridges/{id}/read-card` | Read the company card's identity |

`groupId` zero means every vehicle on the server and requires an administrator. The pairing code
is returned once, at generation. Token and pairing-code hashes are never serialised.

## Bridges, bridge side

These carry `@PermitAll` so they bypass the user-session filter, and authenticate themselves.

| Method | Path | Auth |
|---|---|---|
| POST | `/api/tachograph/bridges/register` | pairing code in the body |
| POST | `/api/tachograph/bridges/{id}/heartbeat` | `X-Bridge-Token`, or `Authorization: Bearer` |
| GET | `/api/tachograph/bridges/{id}/card/poll` | `X-Bridge-Token` |
| POST | `/api/tachograph/bridges/{id}/card/respond` | `X-Bridge-Token` |

`register` returns `bridgeToken` exactly once; the server keeps only its hash. A bad or missing
token gets a bare 401 with no detail, so a caller who does not hold one learns nothing about
whether the bridge exists.

`card/poll` is a long poll, returning `{"command":"NONE"}` when the wait elapses. Command and
response bytes travel as base64 and are the card's own protocol data, which the server relays
without interpreting.

## Delivery

| Method | Path | Description |
|---|---|---|
| GET | `/api/tachograph/targets` | List targets in the caller's groups |
| POST | `/api/tachograph/targets` | Create. Administrators only |
| PUT | `/api/tachograph/targets/{id}` | Update. Administrators only |
| DELETE | `/api/tachograph/targets/{id}` | Delete, cancelling anything queued for it |
| POST | `/api/tachograph/targets/{id}/test` | Connect and authenticate without sending a file |
| GET | `/api/tachograph/forwards` | Delivery records. `fileId`, `status`, `limit` |
| POST | `/api/tachograph/forwards/{id}/retry` | Re-queue a failed delivery |

Credentials are supplied as `secretInput`, which is write-only: it binds from a request body and
is never returned. `hasSecret` reports whether one is stored. Leaving it blank on an update keeps
the existing credential, so editing a schedule does not silently wipe a password.

## Audit

| Method | Path | Description |
|---|---|---|
| GET | `/api/tachograph/audit` | The audit trail. `deviceId`, `limit` |

Without `deviceId` this requires an administrator; with one, permission on that device.

## Error codes

Download and card: `TACHO_DEVICE_OFFLINE`, `TACHO_DOWNLOAD_TIMEOUT`, `TACHO_AUTHENTICATION_FAILED`,
`TACHO_CARD_UNAVAILABLE`, `TACHO_CARD_REMOVED`, `TACHO_CARD_LOCKED`, `TACHO_BRIDGE_UNAVAILABLE`,
`TACHO_PROTOCOL_ERROR`, `TACHO_INVALID_FILE`, `TACHO_STORAGE_ERROR`, `TACHO_PERMISSION_DENIED`,
`TACHO_ALREADY_RUNNING`, `TACHO_PROTOCOL_SPEC_MISSING`.

Delivery: `TACHO_FORWARD_CONNECT`, `TACHO_FORWARD_AUTH`, `TACHO_FORWARD_HOST_KEY`,
`TACHO_FORWARD_TRANSFER`, `TACHO_FORWARD_REJECTED`, `TACHO_FORWARD_CONFIGURATION`.

The web app turns each of these into a sentence saying what to go and do about it; see
`tachoExplainError` in `traccar-web/src/common/util/tachograph.js`.
