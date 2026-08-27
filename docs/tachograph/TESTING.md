# Tachograph Testing

## Unit tests

- `TachographStorageTest` - safe path resolution (traversal rejection, absolute path rejection,
  sanitization) and SHA-256.

## Integration tests

With `tacho.simulator=true`:

1. Create a vehicle + FMC650 device.
2. Enable tachograph for the vehicle.
3. `POST /api/tachograph/download` with `DRIVER` -> 202 + job in `QUEUED`.
4. Poll `GET /api/tachograph/downloads/{id}` until `COMPLETED`.
5. `GET /api/tachograph/files/{id}/download` returns the synthetic DDD bytes.
6. Verify `sha256` matches and the file exists under `data/tachograph/`.
7. Verify permission: a user from another group cannot fetch the file/job.

Set `tacho.simulator.behaviour` system property to exercise the simulator:

- `SUCCESS` (default), `OFFLINE`, `TIMEOUT`, `INVALID_FILE`, `DEVICE_ERROR`.

## File-storage tests

- Write a known byte array via `TachographStorage.writeBytes` + `moveTempToFinal`.
- Assert `calculateSha256` matches `MessageDigest.getInstance("SHA-256")`.

## Permission tests

- Create two groups/companies, each with a vehicle.
- A user in group A cannot list, fetch or download jobs/files for group B's vehicles.

## Scheduler tests

- Set `nextDriverDownload` in the past, run `TaskTachographScheduler` once, assert a
  `DRIVER` job is created and no duplicate is created while one is already `DOWNLOADING`.

## Retry tests

- Set `tacho.retryDelays=1,1,1` and `tacho.simulator.behaviour=TIMEOUT`.
- Request a download, observe `retryCount` increments and `nextRetryAt` is honoured,
  then final `FAILED` after max retries.

## Restart-recovery tests

- Create a job in `REQUESTING` / `DOWNLOADING` / `PROCESSING`, restart the server
  (or call `TachographManager.recoverStaleJobs()`), assert it is re-queued and completes.

## End-to-end simulated test

```
POST /api/tachograph/download (DRIVER)
  -> FMC650 simulator
  -> DDD file (synthetic)
  -> TachographStorage (filesystem + DB)
  -> GET /api/tachograph/downloads/{id} (COMPLETED)
  -> GET /api/tachograph/files/{id}/download (bytes match)
```

## Hardware test

Once the simulator passes, perform a physical test with: 1 FMC650, 1 compatible
tachograph, 1 company card, 1 reader, 1 vehicle, 1 FastHosts server.
The test must prove: `FMC650 -> tachograph -> DDD -> FastHosts filesystem -> DB -> frontend`.
Do not test a fleet before this single-vehicle test succeeds.

Run with:

```
./gradlew test -P tacho.simulator=true
./gradlew :tacho-bridge:build
```
