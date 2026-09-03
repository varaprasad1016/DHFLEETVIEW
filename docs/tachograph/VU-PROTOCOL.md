# Vehicle Unit Download Protocol

How the server talks to a tachograph, what part of it is specified, and what has to be
confirmed against real hardware.

## What this implements

The download protocol from Commission Regulation (EEC) No 3821/85 Annex 1B Appendix 7, and the
Annex 1C equivalents for generation 2 and generation 2 version 2 vehicle units. This is a public
specification. Nothing here is reverse engineered.

Message framing, KWP2000 over ISO 14230-2 as profiled by the regulation:

```
Fmt | Tgt | Src | Len | Data field (Len bytes) | Checksum
0x80  0xEE  0xF0   n    SID + parameters         sum of preceding bytes mod 256
```

`Tgt` 0xEE is the vehicle unit, `Src` 0xF0 the downloading device. Responses reverse them. A
positive response identifier is the request identifier plus 0x40.

Session sequence:

| Step | Request | Positive response |
|---|---|---|
| Start communication | `81` | `C1` + key bytes |
| Start diagnostic session | `10 81` | `50 81` |
| Request upload | `35 00 00 00 00 00 FF FF FF FF` | `75 …` |
| Transfer data | `36 <TREP>` | `76 <TREP> <data>` |
| Transfer exit | `37` | `77` |
| Stop communication | `82` | `C2` |

Negative response `7F <SID> <code>`. Code `0x78` means "response pending" and extends the
deadline rather than failing; `0x21` means busy and repeats the request.

## TREP blocks

| Code | Block | Gen 1 | Gen 2 | Gen 2 v2 |
|---|---|---|---|---|
| Overview | 0x01 | 0x21 | 0x31 | |
| Activities | 0x02 | 0x22 | 0x32 | |
| Events and faults | 0x03 | 0x23 | 0x33 | |
| Detailed speed | 0x04 | 0x24 | 0x34 | |
| Technical data | 0x05 | 0x25 | 0x35 | |
| Card download | 0x06 | | | |

The generation is detected by asking for the generation 1 overview and falling through to the
later ones if it is refused. The block that succeeds is kept, so probing costs no extra transfer.

Activities are requested one calendar day at a time — the request parameter is a single
`TimeReal` date — so a 92 day window is 92 request/response cycles. Days with no activity return
a short block, which is kept: an analysis bureau reads absence of activity as meaningful.

Detailed speed is off by default (`tacho.includeDetailedSpeed`). It is large, slow over a mobile
link, and rarely analysed.

## The one thing to confirm against hardware

**Multi-message continuation.** A data field holds at most 255 bytes, so every block larger than
that arrives in several messages. What the continuation messages look like is the part
manufacturers differ on, and it decides whether the assembled file is byte-correct: get it wrong
and the file gains or loses two bytes at every boundary, which no bureau will parse.

Both observed behaviours are implemented and selected by `tacho.vu.continuationMode`:

- `REPEAT_HEADER` (default) — every message repeats `76 <TREP>`; the repeat is stripped when the
  file is assembled.
- `RAW_CONTINUATION` — only the first message carries the header; continuation messages are pure
  payload.

**How to check it on a real vehicle.** Download a vehicle overview block, which is always larger
than one message, and look at the resulting file:

```bash
xxd -l 64 M_*.DDD          # must begin 76 01
grep -c $'\x76\x01' M_*.DDD   # indicative only; payload can contain those bytes by chance
```

The reliable check is to submit one file to the bureau. If it is rejected as malformed, switch
the mode and download again. `VuDownloadSessionTest` pins the behaviour of both modes so the
switch is a configuration change rather than a code change.

**Block completion.** The end of a block is detected by the vehicle unit going quiet for
`tacho.vu.blockIdleMillis` (default 5 s). If large blocks arrive truncated on real hardware,
raise it. If downloads are slower than they should be on a good link, lower it.

## Signatures

Every block carries a digital signature, and this server does not verify them. Verification needs
the European Root Certificate chain and is the analysis bureau's job. The server's obligation is
to deliver the bytes unaltered, which the stored SHA-256 digest attests — it is recorded at
download time and returned in the `X-File-SHA256` header whenever the file is retrieved.

## Testing without a vehicle

`VirtualVehicleUnit` is a vehicle-unit emulator that answers this protocol properly: real
framing, real checksums, real multi-message blocks, negative responses for the generations it
does not support. `tacho.simulator=true` runs downloads against it through the same
`VuDownloadRunner` production uses, so the session driver, file assembler, inspector, storage,
naming and delivery are all exercised.

The files it produces are structurally valid but synthetic, and their technical data block is
stamped `DHFLEETVIEW SIMULATOR` so one can never be mistaken for a real record. Content is
derived from the device id, so repeated downloads of the same device are byte-identical.

Stage failures with a system property:

```bash
java -Dtacho.simulator.behaviour=OFFLINE -jar tracker-server.jar conf/traccar.xml
```

`SUCCESS`, `OFFLINE`, `TIMEOUT`, `INVALID_FILE`, `NO_CARD`, `DEVICE_ERROR`.
