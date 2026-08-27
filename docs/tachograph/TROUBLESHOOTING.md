# Tachograph Troubleshooting

## Simulator not producing files

- Check `tacho.enabled=true` and `tacho.simulator=true` in `conf/traccar.xml`.
- Check `tacho.storagePath` is writable by the Traccar process.
- Check logs for `Tachograph job ...` lines (`org.traccar.tachograph`).

## Device offline

- `TACHO_DEVICE_OFFLINE` - FMC650 has no active TCP session (`getDeviceSession == null`).
  Verify the device is powered, has cellular coverage and is reporting positions.

## Bridge unavailable

- `TACHO_BRIDGE_UNAVAILABLE` - No bridge with `ONLINE` + `CARD_READY` for the
  vehicle's group. Check `Tachograph > Bridges` dashboard: bridge must show
  `ONLINE`, reader `READER_CONNECTED`, card `CARD_READY`, and `lastHeartbeat`
  within ~2 minutes.

## Card locked

- `TACHO_CARD_LOCKED` - the company card is already in use for another
  download. Wait for the active operation to complete or time out.

## Downloads never start

- Check `TaskTachographScheduler` - automatic jobs only run when
  `nextDriverDownload` / `nextVehicleDownload` is in the past.
- Manual downloads (`POST /api/tachograph/download`) bypass the scheduler.

## Files not downloadable

- Check `data/tachograph` (or `tacho.storagePath`) exists and is not full.
- Check file permissions for the Traccar process.

## Protocol spec missing

- `TACHO_PROTOCOL_SPEC_MISSING` - the real FMC650 tachograph protocol is not
  implemented. This is expected until Teltonika/tachograph documentation is
  supplied. Enable the simulator (`tacho.simulator=true`) for end-to-end
  testing without hardware.

## Stale jobs after restart

- `TaskTachographRecovery` runs 30 seconds after startup and re-queues jobs in
  `REQUESTING`, `DOWNLOADING`, `PROCESSING`, `QUEUED`, `WAITING_*`.
  Check logs for `Recovered stale tachograph job`.

## Storage full

- Monitor `data/tachograph` disk usage. `/data/tachograph` must be included in
  the FastHosts backup.

## Logs to watch

```
org.traccar.tachograph
org.traccar.schedule.TaskTachograph*
```
