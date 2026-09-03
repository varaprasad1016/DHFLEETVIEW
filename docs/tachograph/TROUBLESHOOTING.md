# Tachograph Troubleshooting

Every error code below is also explained in plain language in the web app, on the job or delivery
that produced it.

## Nothing downloads at all

Work down this list; it is ordered by how often each one is the answer.

1. `tacho.enabled=true` in `conf/traccar.xml`.
2. `tacho.tunnel.port` is set to a non-zero port, and that port is open on the firewall. While it
   is zero the listener does not start and downloads fail with `TACHO_PROTOCOL_SPEC_MISSING`. The
   startup log says `Tachograph tunnel disabled` or `Tachograph tunnel listening on port N`.
3. The vehicle is enabled under **Tachograph → Vehicles**.
4. A bridge is online with a card, if this installation uses one.

## `TACHO_PROTOCOL_SPEC_MISSING`

No transport is configured. Set `tacho.tunnel.port`, or turn on `tacho.simulator` for testing.
This is not about a missing specification any more — the protocol is implemented.

## `TACHO_DEVICE_OFFLINE`

Two different causes, distinguished by the message:

- *"has no tracking connection"* — the device is not connected at all. Check power, coverage, and
  that it is reporting positions.
- *"did not open its tachograph tunnel"* — the device is online but never connected to the tunnel
  port. Check the remote tachograph server setting in the Teltonika configurator, the firewall,
  and `tacho.triggerCommand`. Raise `tacho.tunnel.waitSeconds` on a slow network.

If the tunnel connects and immediately closes, the server log will say why. "unknown device" means
the IMEI does not match any device in Traccar.

## `TACHO_BRIDGE_UNAVAILABLE`

No bridge with a ready card is online for that vehicle's company. Under **Tachograph → Bridges**
the bridge must show `ONLINE`, reader `READER_CONNECTED`, card `CARD_READY`, and a heartbeat
within `tacho.bridge.offlineAfterSeconds` (default two minutes).

A bridge configured for company A does not serve company B's vehicles. A bridge with no company
serves everything.

## `TACHO_CARD_UNAVAILABLE`

The card did not answer. Either it is not seated — reseat it and use **Read card** — or another
download holds it. A card serves one authentication at a time, and the hold is released when that
download ends.

## `TACHO_CARD_LOCKED`

The company card is outside its validity period. It must be replaced; no retry will help.

**This is the failure worth preventing rather than diagnosing.** An expired company card does not
announce itself: every scheduled download in the fleet simply starts failing, and by the time
somebody investigates, weeks of legally required data may be missing. The Bridges tab warns from
30 days out — act on that warning.

## `TACHO_PROTOCOL_ERROR`

The tachograph is not following the download protocol. Check the K-line wiring and that the
ignition is on. If it happens only on large blocks, raise `tacho.vu.blockIdleMillis`.

## Files download but the bureau rejects them

Almost certainly the multi-message continuation rule. Switch `tacho.vu.continuationMode` between
`REPEAT_HEADER` and `RAW_CONTINUATION` and download again. See `VU-PROTOCOL.md`; this is the one
part of the protocol manufacturers differ on.

## Downloads are very slow

- `tacho.includeDetailedSpeed=false` unless the bureau actually needs it. It is the largest block
  by far.
- Reduce `tacho.activityDays`. Activity data is fetched one calendar day at a time, so 92 days is
  92 round trips.
- Lower `tacho.vu.blockIdleMillis` on a good link. It is dead time at the end of every block.

## Deliveries never arrive

- **Test** the target. It connects and authenticates without sending a file.
- `TACHO_FORWARD_AUTH` and `TACHO_FORWARD_HOST_KEY` are permanent and are not retried: something
  has to change before they can succeed.
- `TACHO_FORWARD_CONNECT` is retried on a widening backoff; check `nextAttemptAt`.
- `tacho.forward.enabled` must be true.
- A target with no credential shows **No credential** on the Delivery tab.

## "Could not decrypt a forwarding credential"

`tacho.forward.secret` has changed since the credential was stored. Either put the old value back,
or re-enter every credential.

## Stale jobs after a restart

`TaskTachographRecovery` runs 30 seconds after startup and re-queues anything that was mid-flight.
Look for `Recovered tachograph job` in the log. They restart rather than resume: the tunnel and
card session are gone.

## Storage

`tacho.storagePath` must exist, be writable by the server process, have room, and be included in
the backup. Files are the legal record; losing them is losing the record.

## Logs

```
org.traccar.tachograph
org.traccar.tachograph.tunnel
org.traccar.tachograph.forward
org.traccar.schedule.TaskTachograph*
```

Card command and response bytes are never logged, deliberately — an authentication exchange
carries challenge and cryptogram material.
