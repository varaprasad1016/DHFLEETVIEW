# Tachograph Storage

Configuration key: `tacho.storagePath` (in `conf/traccar.xml`).

Defaults to `data/tachograph` on the FastHosts server.

## Layout

```
{tacho.storagePath}/{groupId}/{deviceId}/{year}/{month}/{fileName}
```

Example:

```
data/tachograph/company-1/vehicle-25/2026/08/M_20260827_120000_25.DDD
```

Temporary files are written to `{storagePath}/.tmp/tacho-*.tmp` and moved atomically
with `Files.move(..., REPLACE_EXISTING)`.

## Safety

- `TachographStorage.resolveFinalPath` validates that the file name contains no `..`, `/` or `\`.
- Group/device segments are sanitized (`[^a-zA-Z0-9._-]` -> `_`).
- Absolute paths are rejected.
- No user input is used to construct arbitrary filesystem paths.

## Integrity

- SHA-256 is calculated for every stored file and persisted in `tc_tachograph_files.sha256`.
- Original DDD files are never modified.

## Backup

`/data/tachograph` (or the configured `tacho.storagePath`) MUST be included in the
FastHosts server backup alongside the database. Database backup alone is insufficient
because DDD binaries are stored on the filesystem.

## Monitoring

Watch `data/tachograph` disk usage; alert on failed downloads (`status=FAILED`),
stale jobs and recent successful downloads via the Tachograph dashboard.
