"""
Path B: TachoSync binary protocol server (TCP 29000).

# ASSUMED wire sequence — see packets.py / fields.py. All infra dependencies are
# injected as callables so the whole session can be exercised in-process against
# a mock device, with no Postgres/MinIO/reader present.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .crc import INIT_DEFAULT
from .fields import Metadata, build_offset, parse_metadata, parse_packet_count
from .packets import (
    CMD_CLOSE,
    CMD_DATA,
    CMD_FILE_PATH,
    CMD_FILE_REQUEST,
    CMD_METADATA,
    CMD_REQUEST_METADATA,
    CMD_REQUEST_PATH,
    CMD_START_TRANSFER,
    CMD_SYNC,
    CMD_TRANSFER_STATUS,
    INIT_PACKET_LEN,
    MAX_IMEI_LEN,
    InitPacket,
    decode_imei,
    decode_init_packet,
    decode_packet,
    encode_packet,
)

# Named under "tacho" because that is the tree main.py raises to INFO; with the
# module's dotted name these lines were written nowhere and the listener looked
# silent even while it was turning units away.
logger = logging.getLogger("tacho.sync")


def _probe_reply():
    """The bytes to answer a unit with, or None to fall back to a plain ack."""
    try:
        text = PROBE_REPLY_FILE.read_text(encoding="utf-8")
    except OSError:
        return None
    cleaned = "".join(line.split("#")[0] for line in text.splitlines()).replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        logger.warning("probe reply file is not hex: %r", cleaned[:40])
        return None

# The one-byte answer to a unit announcing itself: 1 accepts, 0 turns it away.
ACCEPT = 1


class RawStream(Exception):
    """Raised when what arrives is file content rather than a framed packet."""

    def __init__(self, head: bytes) -> None:
        super().__init__("raw stream")
        self.head = head

# Where a hand-written reply is read from while the message set is being worked
# out. Absent in normal running, and nothing depends on it.
PROBE_REPLY_FILE = Path("D:/DHFleetViewData/tacho/probe_reply.hex")

# Teltonika's TCP envelope: four zero bytes, a four-byte length, the payload,
# then a four-byte CRC.
TELTONIKA_PREAMBLE = bytes(4)   # four zero bytes, written without an escape
MAX_PAYLOAD = 2 * 1024 * 1024
HEARTBEAT_BYTE = 0xEF
PACKET_TIMEOUT = 120
# A full download is a few hundred kilobytes over a mobile link and can take
# many minutes; what ends it is silence, not elapsed time.
STREAM_IDLE_TIMEOUT = 180
INCOMING_DIR = Path("D:/DHFleetViewData/tacho/files/incoming")
PAYLOAD_LOG_BYTES = 256

# Injected dependencies.
LookupDevice = Callable[[str], Awaitable[Optional[object]]]
GetPendingSchedule = Callable[[object], Awaitable[Optional[object]]]
StoreFile = Callable[[object, Metadata, bytes], Awaitable[None]]


class ProtocolError(Exception):
    pass


class TachoSyncServer:
    def __init__(
        self,
        *,
        lookup_device: LookupDevice,
        get_pending_schedule: GetPendingSchedule,
        store_file: StoreFile,
        host: str = "0.0.0.0",
        port: int = 29000,
    ):
        self._lookup = lookup_device
        self._schedule = get_pending_schedule
        self._store = store_file
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> asyncio.AbstractServer:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        host, port = self._server.sockets[0].getsockname()[:2]
        logger.info("TachoSync (Path B) listening on %s:%s", host, port)
        return self._server

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @property
    def port(self) -> int:
        if self._server:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        # Logged before anything is read. A vehicle that opens the socket and
        # says nothing looks exactly like a port scanner until you can see
        # where it came from, and on a public address both arrive.
        logger.info("TachoSync connection from %s", peer)
        try:
            await self._session(reader, writer)
        except (asyncio.IncompleteReadError, ProtocolError, ValueError) as exc:
            logger.warning("Session error from %s: %s", peer, exc)
        except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            # The far end hung up mid-read. Normal on a mobile link and not worth
            # a traceback - but say so, because a device that connects and drops
            # repeatedly is a symptom and must not look like silence.
            logger.warning("Connection from %s dropped before the session began: %s", peer, exc)
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """One unit's visit: it says who it is, and is asked for a file or sent away."""
        # The unit opens with a two-byte length and that many ASCII digits of
        # IMEI. The raw bytes are logged because this protocol was reconstructed
        # rather than documented, and the first unit through it is the only
        # authority on what it actually sends.
        header = await reader.readexactly(2)
        length = int.from_bytes(header, "big")
        if 0 < length <= MAX_IMEI_LEN:
            body = await reader.readexactly(length)
            init = InitPacket(protocol_id=0, imei=decode_imei(body), settings=0)
            logger.info("Device connected imei=%s (init %s)", init.imei, (header + body).hex())
        else:
            rest = await reader.readexactly(INIT_PACKET_LEN - 2)
            init = decode_init_packet(header + rest)
            logger.info("Device connected imei=%s proto=%s (init %s)",
                        init.imei, init.protocol_id, (header + rest).hex())

        # A unit that has just announced itself waits to hear whether it was
        # accepted: one byte, 0x01 for yes, as in Teltonika's own protocol.
        # Without it the first unit through here sent nothing further and hung
        # up, which is what "0 bytes read on a total of 4 expected" was.
        writer.write(bytes([ACCEPT]))
        await writer.drain()

        device = await self._lookup(init.imei)
        schedule = await self._schedule(device) if device is not None else None
        if schedule is None:
            logger.info("No download due for imei=%s; letting it go", init.imei)
            return
        logger.info("Download due for %s: %s", device.get("registration"), schedule.get("reason"))

        # From here the unit speaks Teltonika's own TCP framing, not the
        # command framing this module was first written to. Its opening packet
        # was four zero bytes, which is that envelope's preamble - read as a
        # command id and a length it could only ever fail the CRC.
        #
        # Nothing is assumed about what the payload means yet: every packet is
        # logged whole, acknowledged the documented way, and the session is held
        # open until the unit stops talking. The first real transfer is what
        # turns this into a parser.
        while True:
            try:
                packet = await asyncio.wait_for(self._read_envelope(reader), PACKET_TIMEOUT)
            except RawStream as raw:
                await self._capture_file(reader, init.imei, device, raw.head)
                return
            except asyncio.TimeoutError:
                logger.info("imei=%s went quiet; closing", init.imei)
                return
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    logger.info("imei=%s closed mid-packet after %s", init.imei, exc.partial.hex())
                else:
                    logger.info("imei=%s closed the connection", init.imei)
                return
            if packet is None:
                return

            # What to answer with is the one thing still unknown: the unit speaks
            # a type-0x10 message set Teltonika has not published. Rather than
            # bake a guess into the code, the reply is read from a file each
            # time, so an attempt costs an edit rather than a restart. The file
            # holds hex (whitespace and # comments ignored); with no file, the
            # unit is acknowledged the ordinary Teltonika way and simply waits.
            # The unit's keep-alive: codec 12, type 0x10, a single 0xEF byte.
            # It is the frame a file request is supposed to answer, so the probe
            # reply goes here and nowhere else - answering its opening STATUS
            # with the same bytes only muddies what the unit is reacting to.
            heartbeat = len(packet) == 9 and packet[7] == HEARTBEAT_BYTE
            reply = _probe_reply() if heartbeat else None
            if reply is not None:
                logger.info("probe reply: %s", reply.hex())
                writer.write(TELTONIKA_PREAMBLE + len(reply).to_bytes(4, "big") + reply
                             + bytes(4))
            else:
                records = packet[1] if len(packet) > 1 else 0
                writer.write(records.to_bytes(4, "big"))
            await writer.drain()

    async def _capture_file(self, reader: asyncio.StreamReader, imei: str, device, head: bytes) -> None:
        """Read a file off the wire and keep it, whatever we can make of it.

        Written to disk first and parsed afterwards. A tachograph download is
        the one thing here that cannot be asked for again cheaply - the vehicle
        has to be awake, the card has to be in, and the unit decides when - so
        the bytes are safe on disk before anything clever is attempted.
        """
        buffer = bytearray(head)
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(65536), STREAM_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                logger.info("stream went quiet after %d bytes", len(buffer))
                break
            if not chunk:
                break
            buffer += chunk
            if len(buffer) % (64 * 1024) < 65536:
                logger.info("received %d bytes so far from imei=%s", len(buffer), imei)
        if not buffer:
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name = "%s-%s.ddd" % (device.get("registration") or imei, stamp)
        INCOMING_DIR.mkdir(parents=True, exist_ok=True)
        path = INCOMING_DIR / name
        path.write_bytes(bytes(buffer))
        logger.info("kept %d bytes from imei=%s as %s", len(buffer), imei, path)

        try:
            await self._store(device, Metadata(size=len(buffer), file_type=0, filename=name), bytes(buffer))
            logger.info("Stored %s (%d bytes) for imei=%s", name, len(buffer), imei)
        except Exception:
            logger.exception("the file arrived and is saved at %s, but could not be ingested", path)

    async def _read_envelope(self, reader: asyncio.StreamReader) -> Optional[bytes]:
        """One Teltonika TCP packet: preamble, length, payload, CRC.

        The payload is returned whole and logged as hex. Until the file
        transfer is understood that log is the point of this listener.
        """
        preamble = await reader.readexactly(4)
        if preamble != TELTONIKA_PREAMBLE:
            # Not a framed packet: this is the file itself arriving. Hand the
            # bytes back rather than dropping them - they are the first four of
            # a DDD and there may be no second chance to ask for it.
            logger.info("stream does not start with a packet preamble (%s): treating it as file data",
                        preamble.hex())
            raise RawStream(preamble)
        length = int.from_bytes(await reader.readexactly(4), "big")
        if length <= 0 or length > MAX_PAYLOAD:
            logger.warning("payload length %d is out of range", length)
            return None
        payload = await reader.readexactly(length)
        crc = await reader.readexactly(4)
        logger.info("packet: codec=0x%02x records=%d length=%d crc=%s",
                    payload[0], payload[1] if len(payload) > 1 else -1, length, crc.hex())
        logger.info("payload: %s%s", payload[:PAYLOAD_LOG_BYTES].hex(),
                    "..." if length > PAYLOAD_LOG_BYTES else "")
        return payload

    async def _send(self, writer: asyncio.StreamWriter, cmd_id: int, data: bytes, prev_crc: int) -> int:
        frame, new_crc = encode_packet(cmd_id, data, prev_crc)
        writer.write(frame)
        await writer.drain()
        return new_crc

    async def _recv(self, reader: asyncio.StreamReader, prev_crc: int, expected_cmd: Optional[int]):
        header = await reader.readexactly(4)
        logger.info("packet header %s (expecting cmd %s)", header.hex(), expected_cmd)
        data_len = int.from_bytes(header[2:4], "big")
        rest = await reader.readexactly(data_len + 2)
        pkt = decode_packet(header + rest, prev_crc)
        if expected_cmd is not None and pkt.cmd_id != expected_cmd:
            raise ProtocolError(f"expected cmd 0x{expected_cmd:04X}, got 0x{pkt.cmd_id:04X}")
        return pkt, pkt.crc
