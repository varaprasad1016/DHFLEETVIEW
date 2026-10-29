# FMC650 Integration

How a Teltonika FMC650 gets tachograph data from a vehicle to this server.

## The shape of it

```
Tachograph (VU)  ──K-line──  FMC650  ──TCP──  tacho.tunnel.port  ──  TachographTunnelServer
                                                                          │
                                                                     VuDownloadSession
                                                                          │
                                                            DDD file → storage → bureau
```

The device keeps its normal tracking connection on the Teltonika protocol port throughout. The
tachograph tunnel is a **second, separate socket** it opens only for the duration of a download.

## Commissioning a vehicle

1. **Server.** Set `tacho.tunnel.port` in `conf/traccar.xml` and open that port on the firewall.
   The listener stays off while the port is zero, which is the default.
2. **Device.** In the Teltonika configurator, point the remote tachograph server setting at this
   server's host and that port.
3. **Traccar.** The device must already exist as a device, matched on its IMEI. The tunnel refuses
   any connection whose IMEI it does not recognise.
4. **Vehicle.** Enable tachograph downloads for the device under Tachograph, Vehicles.

## Tunnel handshake

The device identifies itself the same way it does on the tracking port: a two-byte big-endian
length followed by the IMEI in ASCII. The server answers with one byte, `0x01` to accept and
`0x00` to reject. Everything after that is opaque vehicle-unit traffic, passed straight through
in both directions.

A connection that sends payload before identifying itself, or presents an unknown IMEI, is closed
immediately. An unauthenticated socket must never be able to reach a download.

## Starting a download

Two ways, and both are supported because installations differ:

- **The server asks.** Set `tacho.triggerCommand` to the command your firmware uses, and the
  server sends it over the tracking connection, then waits up to `tacho.tunnel.waitSeconds` for
  the device to connect.
- **The device decides.** Leave `tacho.triggerCommand` unset. The server waits for the device to
  bring the tunnel up on its own schedule.

The trigger text is configuration rather than code because it differs between FMC650 firmware
builds. **This is the one value to confirm against your own hardware and firmware version.**
Everything downstream of the tunnel is specified by the regulation and does not vary.

## What the server does over the tunnel

See `VU-PROTOCOL.md`. In short: the Annex 1B download protocol, one `TransferData` request per
data block, activity data one calendar day at a time, assembled into a DDD file, inspected for
vehicle identity, stored with a SHA-256 digest, then queued for delivery.

## Company card

A remote download needs a company card. The card stays in a reader in the office and its command
traffic is relayed to it over HTTPS — see `TACHO-BRIDGE.md`. The server relays bytes; it holds no
card keys and performs no card cryptography.

## Testing without a vehicle

Set `tacho.simulator=true`. Downloads run against a built-in vehicle-unit emulator that speaks the
real protocol, through the same code path production uses. See `VU-PROTOCOL.md`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `TACHO_DEVICE_OFFLINE`, "no tracking connection" | The device is not connected at all. |
| `TACHO_DEVICE_OFFLINE`, "did not open its tachograph tunnel" | The device is online but did not connect to the tunnel port. Check the configurator setting, the firewall, and `tacho.triggerCommand`. |
| Tunnel connects then closes | The IMEI is not a known device, or does not match the tracking connection. Check the server log for "unknown device". |
| `TACHO_PROTOCOL_ERROR` on the first block | The tachograph is not answering the download protocol. Check the K-line wiring and that the vehicle ignition is on. |
| Blocks truncated | Raise `tacho.vu.blockIdleMillis`. |
| Bureau rejects the file as malformed | Switch `tacho.vu.continuationMode`. See `VU-PROTOCOL.md`. |
