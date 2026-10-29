# Testing the Tachograph Module

Everything below runs without a vehicle, a tachograph, a card reader or a bureau account.

## Automated tests

```bash
./gradlew test --tests "org.traccar.tachograph.*"
./gradlew :tacho-bridge:build
```

| Test | What it pins down |
|---|---|
| `VuMessageTest` | Framing: encoding, checksums, truncated and corrupt frames, negative responses |
| `VuDownloadSessionTest` | A real session against the emulator: handshake, multi-message blocks, generation fallback, date-ranged activities, end-to-end file inspection |
| `SecretCipherTest` | Credential encryption: round trip, fresh IV per encryption, tamper detection, wrong passphrase |
| `TachographStorageTest` | Path handling and traversal rejection |

The session tests are the ones that matter most. Every other layer can be checked by reading it;
whether the session driver, the framing and the file assembler agree with each other over a
multi-message transfer can only be checked by running one.

## The simulator

`tacho.simulator=true` runs downloads against `VirtualVehicleUnit`, a vehicle-unit emulator that
answers the real Annex 1B protocol, through the same code path production uses.

Its files are structurally valid but synthetic. The technical data block is stamped
`DHFLEETVIEW SIMULATOR`, so one can never be mistaken for a real record. Content is derived from
the device id, so repeated downloads of the same device are byte-identical, which makes delivery
and de-duplication testable.

**Never enable it on a production server.**

Stage a failure with a system property:

```bash
java -Dtacho.simulator.behaviour=OFFLINE -jar tracker-server.jar conf/traccar.xml
```

`SUCCESS`, `OFFLINE`, `TIMEOUT`, `INVALID_FILE`, `NO_CARD`, `DEVICE_ERROR`. Use these to check the
retry backoff and that the web app explains each failure usefully.

## End-to-end by hand

Against a server with the simulator on:

```bash
API=http://localhost:8082/api
curl -c c.txt -X POST $API/session -d "email=you@example.com&password=..."

# request a download
curl -b c.txt -X POST $API/tachograph/download \
  -H 'Content-Type: application/json' -d '{"deviceId":1,"downloadType":"VEHICLE"}'

# watch it; progress and progressDetail move while it runs
curl -b c.txt "$API/tachograph/downloads/1"

# the stored file, with the vehicle identity read out of it
curl -b c.txt "$API/tachograph/files"

# fetch it and confirm the digest matches the one recorded at download time
curl -b c.txt -D - -o out.DDD "$API/tachograph/files/1/download"
sha256sum out.DDD
```

A correct DDD file begins `76 01`:

```bash
xxd -l 16 out.DDD
```

Worth also confirming: a second download of the same type while one is running is refused with
`TACHO_ALREADY_RUNNING`, and the audit trail records the request, the completion and every file
retrieval.

## Testing the card relay without a card

The bridge side is plain HTTPS, so a shell script can stand in for one: poll for commands, answer
them the way a card would, and the whole relay path is exercised.

```bash
# pair a bridge in the web app, note the token it prints once, then:
curl -X POST $API/tachograph/bridges/1/heartbeat \
  -H 'Content-Type: application/json' -H "X-Bridge-Token: $TOKEN" \
  -d '{"readerStatus":"READER_CONNECTED","cardStatus":"CARD_READY"}'

# in one terminal, poll and answer
curl "$API/tachograph/bridges/1/card/poll" -H "X-Bridge-Token: $TOKEN"
curl -X POST "$API/tachograph/bridges/1/card/respond" \
  -H 'Content-Type: application/json' -H "X-Bridge-Token: $TOKEN" \
  -d '{"commandId":"...","data":"kAA="}'   # kAA= is 9000, success

# in another, trigger a card read
curl -b c.txt -X POST "$API/tachograph/bridges/1/read-card"
```

The server issues `00 A4 04 0C 06 FF 54 41 43 48 4F` to select the tachograph application,
`00 A4 02 0C 02 05 20` to select `EF_Identification`, and `00 B0 00 00 8B` to read its 139 bytes.
Answering the last one with a well-formed identity file should come back as a decoded card number,
company, issuer and expiry date.

Confirm the negative cases too: a wrong `X-Bridge-Token` must give 401, a missing one must give
401, and a reused pairing code must be refused.

## Testing delivery without a bureau

Point a target at any SFTP server you control, or at a host that does not exist to check the
failure path reports a clear, retryable error and schedules a retry rather than giving up.

Use **Test** on the target rather than waiting for a real download: it connects and authenticates
without sending a file, so a wrong credential surfaces immediately.

Also confirm that saving a credential and reading the target back never returns it — only
`hasSecret` — and that updating a target with a blank credential keeps the stored one.

## Permissions

Worth checking by hand, because it is the kind of thing that only breaks in production:

- A user in company A cannot list, fetch or download jobs or files for company B's vehicles.
- A non-administrator cannot create a delivery target, delete a file, or read the whole audit trail.
- A bridge token reaches only the four `bridges/{id}/` endpoints and no fleet data.

## Restart recovery

Create a job, stop the server while it is running, and start it again. `TaskTachographRecovery`
runs 30 seconds after startup and should re-queue it. It restarts rather than resumes: the tunnel
and card session are gone.

## What still needs hardware

| Needs | To confirm |
|---|---|
| An FMC650 and a vehicle | `tacho.triggerCommand` syntax for your firmware, and the tunnel handshake against a real device |
| One real download | `tacho.vu.continuationMode`, by submitting a file to the bureau. See `VU-PROTOCOL.md` |
| A real company card | That a live vehicle unit completes authentication through the relay |
| A bureau account | That files are accepted, and whether the naming pattern needs adjusting |

Do a single-vehicle test before enabling a fleet.
