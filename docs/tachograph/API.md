# Tachograph API

All endpoints follow the existing `BaseResource` conventions
(`permissionsService.checkPermission(Device/Group.class, getUserId(), id)`).

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/tachograph/configuration/{deviceId}` | user | Get tachograph config for device |
| POST | `/api/tachograph/configuration/{deviceId}` | user | Create/update config |
| POST | `/api/tachograph/download` | user | Create download job. Body: `{deviceId, downloadType}`. Returns 202. |
| GET | `/api/tachograph/downloads?deviceId=&status=&from=&to=&limit=` | user | List jobs (group-filtered) |
| GET | `/api/tachograph/downloads/{id}` | user | Get job |
| POST | `/api/tachograph/downloads/{id}/cancel` | user | Cancel job |
| GET | `/api/tachograph/files?deviceId=&limit=` | user | List files |
| GET | `/api/tachograph/files/{id}/download` | user | Stream DDD file (permission-checked, no path exposed) |
| GET | `/api/tachograph/bridges` | user | List bridges (group-filtered) |
| POST | `/api/tachograph/bridges/pairing-code` | user | Generate one-time pairing code. Body: `{groupId, name}` |
| POST | `/api/tachograph/bridges/register` | pairing code | Register bridge. Body: `{pairingCode, bridgeId, name, softwareVersion}` |
| POST | `/api/tachograph/bridges/{id}/heartbeat` | bridge token | Heartbeat. Header `X-Bridge-Token` or `Authorization: Bearer <token>`. Body: `{readerStatus, cardStatus, softwareVersion}` |
| GET | `/api/tachograph/bridges/{id}/status` | user | Bridge status |

All list endpoints filter by the caller's device/group permissions.
Binary file endpoints use `StreamingOutput` and never expose filesystem paths.

## Error codes

`TACHO_DEVICE_OFFLINE`, `TACHO_DOWNLOAD_TIMEOUT`, `TACHO_AUTHENTICATION_FAILED`,
`TACHO_CARD_UNAVAILABLE`, `TACHO_BRIDGE_UNAVAILABLE`, `TACHO_PROTOCOL_ERROR`,
`TACHO_INVALID_FILE`, `TACHO_STORAGE_ERROR`, `TACHO_PERMISSION_DENIED`,
`TACHO_ALREADY_RUNNING`, `TACHO_CARD_REMOVED`, `TACHO_CARD_LOCKED`,
`TACHO_PROTOCOL_SPEC_MISSING`.
