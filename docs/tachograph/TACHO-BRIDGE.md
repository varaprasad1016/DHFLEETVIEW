# Tacho Bridge

The office application that makes a company tachograph card available to the fleet server, so
vehicles can be downloaded remotely instead of somebody driving the card out to each one.

## What it is, and what it deliberately is not

```
Company card in a PC/SC reader
        │  APDUs
   Tacho Bridge (office machine, Windows)
        │  outbound HTTPS only
   DH FleetView server
        │
   Vehicle unit, via the FMC650 tunnel
```

The bridge relays command bytes to the card and relays the answers back. That is all it does.

**It performs no cryptography, and neither does the server.** In a remote download the vehicle
unit and the company card authenticate each other directly; everything in between is a wire. This
is what makes the whole feature possible without card secrets ever leaving the reader — there is
no key material anywhere in this codebase to steal, and no card protocol to get subtly wrong.

## Installing

Requires Java 17 or later and a PC/SC card reader.

```bash
cd tacho-bridge
./gradlew build
# copy build/libs/tacho-bridge.jar to the office machine
```

Create `bridge.properties` next to the JAR:

```properties
serverUrl=https://dhfleetview.co.uk
bridgeName=Head Office
```

## Pairing

1. In the web app: **Tachograph → Bridges → Pair a bridge**. Choose which company's vehicles this
   card may authorise, and generate a code.
2. On the office machine:

```bash
java -jar tacho-bridge.jar pair 472435
```

3. Run it:

```bash
java -jar tacho-bridge.jar
```

The code is six digits, single use, and expires in fifteen minutes. It is stored only as a hash,
as is the token it is exchanged for. Neither is ever returned by the API after the moment it is
issued — if the token is lost, pair again.

Run it as a Windows service so it survives a reboot; a bridge that is not running stops every
scheduled download in the fleet.

## How it talks to the server

All traffic is outbound HTTPS. The bridge never listens for inbound connections, so it needs no
firewall change and no port forward on the customer's network.

| What | Endpoint | Auth |
|---|---|---|
| Pair | `POST /api/tachograph/bridges/register` | pairing code |
| Heartbeat, every 30 s | `POST /api/tachograph/bridges/{id}/heartbeat` | `X-Bridge-Token` |
| Wait for card work | `GET /api/tachograph/bridges/{id}/card/poll` | `X-Bridge-Token` |
| Return the answer | `POST /api/tachograph/bridges/{id}/card/respond` | `X-Bridge-Token` |

The poll is a long poll: the server holds it open until it has work or `tacho.card.pollTimeoutSeconds`
elapses, so an idle bridge costs one request every half minute rather than a steady stream.

A bridge that stops sending heartbeats is marked offline after `tacho.bridge.offlineAfterSeconds`,
and stops being offered for downloads. A crashed bridge does not get to look available and swallow
every job in the fleet.

## Card exclusivity

A smart card has one security context, so it serves one authentication at a time. The server
opens an exclusive session on a bridge's card for the length of a download and refuses a second
one rather than interleaving commands, which the card would not survive.

## Reading the card

**Tachograph → Bridges → Read card** selects the tachograph application, reads
`EF_Identification`, and shows the card number, company, issuer and expiry date.

Do this after pairing. The expiry date is the thing worth knowing: an expired company card does
not announce itself — every scheduled download simply starts failing authentication, and by the
time somebody investigates, weeks of legally required data may be missing. The web app warns from
30 days out.

## Diagnostics

`http://127.0.0.1:8765/status` on the office machine, loopback only:

```json
{"version":"2.0.0","server":"https://...","paired":true,
 "reader":"READER_CONNECTED","card":"CARD_READY","lastError":null}
```

## Security

- Outbound HTTPS only.
- `bridge.properties` holds the token. Restrict its file permissions. Never commit it.
- The status server binds to loopback, never `0.0.0.0`.
- Card command and response bytes are never logged. An authentication exchange carries challenge
  and cryptogram material, and a log file is not the place for it.
- `MockSmartCardReader` is test-only; select it with `-Dtacho.reader=mock`. The default is PC/SC.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Bridge shows OFFLINE | Not running, or cannot reach the server. Check `/status` and `lastError`. |
| `NO_READER` | The reader is unplugged, or its driver is not installed. |
| `NO_CARD` | The card is not seated. Reseat it and read the card again. |
| `TACHO_CARD_UNAVAILABLE` on downloads | No bridge with a ready card is online for that company. |
| "Company card is in use" | Another download holds the card. It is released when that one ends. |
| Card reads fail with status `6A82` | The card is not a tachograph company card, or is faulty. |
