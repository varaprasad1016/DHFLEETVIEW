# FMC650 Integration

## Verified behaviour

- Teltonika stack: `TeltonikaProtocol` / `TeltonikaFrameDecoder` / `TeltonikaProtocolDecoder` /
  `TeltonikaProtocolEncoder` in `src/main/java/org/traccar/protocol/teletonika/`.
- Device X23DHG (0443950178) communicates as a standard Teltonika tracker - no tachograph.
- Supported commands in `TeltonikaProtocol`: `TYPE_CUSTOM`, `TYPE_ENGINE_STOP`, `TYPE_ENGINE_RESUME`.

## Missing specification - DO NOT INVENT

The following is **not available** in this repository or in the supplied documentation:

1. **Teltonika FMC650 remote tachograph server protocol** - TCP handshake, message framing,
   and the "serial-over-IP" relay that the FMC650 uses to proxy the tachograph.
2. **Tachograph manufacturer protocols** - Continental DTCO, Stoneridge SE5000, Intellic Efas
   company-card authentication and DDD download per the EU regulation.
3. **Teltonika configurator parameters** for the remote tachograph server (address/port, enable flag).

## Current implementation

`TachographDeviceClient` is an interface with two implementations:

- `SimulatedTachographDeviceClient` - enabled with `tacho.simulator=true`. Generates
  synthetic DDD bytes, respects `tacho.simulator.behaviour` system property
  (`SUCCESS`, `OFFLINE`, `TIMEOUT`, `INVALID_FILE`, `DEVICE_ERROR`). TEST ONLY.
- Real FMC650 client - throws `TACHO_PROTOCOL_SPEC_MISSING` until the above
  specifications are supplied. No fake packet structures are implemented.

```
TachographManager
  -> TachographDeviceClient (interface)
       -> SimulatedTachographDeviceClient (simulator)
       -> FMC650TachographClient (stub, throws spec-missing)
```

## What is needed to implement the real client

- Teltonika "Tachograph Data Download" documentation for FMC650 (codec 8 extended,
  tacho file transfer messages, or the remote server relay spec)
- Tachograph manufacturer DDD protocol documentation
- A physical FMC650 + tachograph + company card + test vehicle on FastHosts
- Company-card authentication flow verified with the Tacho Bridge (see `TACHO-BRIDGE.md`)

Until these are available the integration remains in simulator mode.
