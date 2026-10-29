# Delivery to Analysis Bureaux

How downloaded DDD files reach Convey Reporting, or any other bureau.

## Why it is a queue

A download that has succeeded is a legal record the operator now holds. It must not be lost
because a bureau's SFTP server happened to be down at that moment, so delivery is queued rather
than done inline: each file and target pair becomes a row that is retried on a widening backoff
until it is delivered or an unfixable rejection stops it.

Each pair is independent, so a file going to two bureaux can succeed at one and keep retrying at
the other.

## Setting up a target

**Tachograph → Delivery → Add target.**

Before the first one, set a passphrase in `conf/traccar.xml`:

```xml
<entry key="tacho.forward.secret">a-long-random-value</entry>
```

This encrypts stored credentials with AES-GCM under a key derived from it. It lives in the
configuration file rather than the database, so reading the database alone does not yield a
fleet's bureau credentials. **Do not change it once targets exist** — every stored credential
would have to be entered again.

| Field | Notes |
|---|---|
| Bureau | Convey Reporting, or Other |
| Transport | SFTP for most bureaux; HTTPS where they offer an upload API |
| Company | Which vehicles' files go here. Blank means every vehicle on the server |
| Host, port, remote directory | SFTP. The directory is created if missing |
| Expected host key | Paste the bureau's SSH host key. See below |
| Username, password or key | A password, or paste a private key; the format is detected |
| Remote file name pattern | Blank keeps the local name |
| Sends | Vehicle unit files, driver card files, or both |

Then press **Test**. It connects and authenticates without sending anything, so a wrong credential
surfaces at configuration time rather than when the first legally required file fails to arrive.

## Host key pinning

Set the expected host key. Without it, the first server answering that address is trusted, and
what is being handed over is every driver's complete working record.

Get it from the bureau, or read it yourself once from a trusted network:

```bash
ssh-keyscan -t rsa sftp.example.com
```

Paste either the full `ssh-rsa AAAA...` line or just the base64 body.

## File naming

The default keeps the name the download produced: `M_<registration>_<timestamp>.DDD` for a vehicle
unit, `C_<card>_<timestamp>.DDD` for a driver card.

Some bureaux match files to vehicles by name, so the pattern is configurable:

| Token | Becomes |
|---|---|
| `{name}` | the local file name |
| `{device}` | the vehicle name in DH FleetView |
| `{registration}` | the registration read out of the file |
| `{vin}` | the vehicle identification number |
| `{card}` | the card number, for driver downloads |
| `{type}` | `vehicle` or `driver` |
| `{timestamp}` | download time, `yyyyMMddHHmmss` |

Path separators are stripped from the result: a naming pattern is not a way to write outside the
upload directory.

## Delivery mechanics

SFTP uploads to a `.part` name and renames into place once every byte has arrived. Bureaux poll
their inbound directory on a timer, and a poll that catches a half-written file either imports a
truncated record or rejects it; the rename makes the file appear atomically or not at all.

HTTPS sends `multipart/form-data` with the bytes in a `file` part. Authentication is a bearer
token, or HTTP basic when a username is also set. Plain HTTP is refused — driver hours data is
personal data and does not travel in clear text.

## Retries

`tacho.forward.retryDelays` (default `60,300,1800,7200,21600` seconds) and
`tacho.forward.maxAttempts` (default 6). A failure is only retried when retrying could help:

| Retried | Not retried |
|---|---|
| Connection refused, timeout, reset | Authentication refused |
| HTTP 5xx, 408, 429 | Host key mismatch |
| | Other HTTP 4xx |
| | Missing or malformed configuration |

A rejected credential is permanent until somebody changes it, and spending a day of backoff on it
only delays the moment an operator finds out.

## Checking what happened

- **Tachograph → Files**, expand a row: where that file went, when, and under what name.
- **Tachograph → Delivery**: recent deliveries across all targets, with a Retry button.
- **Tachograph → Audit**: `FORWARD_QUEUED`, `FORWARD_DELIVERED`, `FORWARD_FAILED`.

The question an audit asks is not "did you download it" but "where did it go and when". That is
what these three views answer.

## Convey Reporting specifically

Convey is supported through the standard SFTP drop, which is how it accepts bulk DDD files. Set
the provider to Convey, the transport to SFTP, and use the host, directory and credentials from
your Convey account. The provider field is currently a label rather than a behaviour switch: if
Convey issues an upload API for your account, use the HTTPS transport with the endpoint and key
they supply.
