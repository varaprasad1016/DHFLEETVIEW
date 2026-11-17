"""
Path B: TachoSync binary protocol server (TCP 29000).

# ASSUMED wire sequence — see packets.py / fields.py. All infra dependencies are
# injected as callables so the whole session can be exercised in-process against
# a mock device, with no Postgres/MinIO/reader present.
"""

from __future__ import annotations

import asyncio
import logging
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
    decode_init_packet,
    decode_packet,
    encode_packet,
)

logger = logging.getLogger(__name__)

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
        try:
            await self._session(reader, writer)
        except (asyncio.IncompleteReadError, ProtocolError, ValueError) as exc:
            logger.warning("Session error from %s: %s", peer, exc)
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        init = decode_init_packet(await reader.readexactly(INIT_PACKET_LEN))
        logger.info("Device connected imei=%s proto=%s", init.imei, init.protocol_id)

        device = await self._lookup(init.imei)
        schedule = await self._schedule(device) if device is not None else None

        tx_crc = INIT_DEFAULT
        if schedule is None:
            tx_crc = await self._send(writer, CMD_CLOSE, b"", tx_crc)
            logger.info("No pending schedule for imei=%s; session closed", init.imei)
            return

        rx_crc = INIT_DEFAULT

        tx_crc = await self._send(writer, CMD_REQUEST_PATH, b"", tx_crc)
        _, rx_crc = await self._recv(reader, rx_crc, CMD_FILE_PATH)

        tx_crc = await self._send(writer, CMD_REQUEST_METADATA, b"", tx_crc)
        meta_pkt, rx_crc = await self._recv(reader, rx_crc, CMD_METADATA)
        meta = parse_metadata(meta_pkt.data)

        tx_crc = await self._send(writer, CMD_FILE_REQUEST, b"", tx_crc)
        start_pkt, rx_crc = await self._recv(reader, rx_crc, CMD_START_TRANSFER)
        total_packets = parse_packet_count(start_pkt.data)

        tx_crc = await self._send(writer, CMD_SYNC, build_offset(0), tx_crc)

        buffer = bytearray()
        for _ in range(total_packets):
            data_pkt, rx_crc = await self._recv(reader, rx_crc, CMD_DATA)
            buffer += data_pkt.data

        _, rx_crc = await self._recv(reader, rx_crc, CMD_TRANSFER_STATUS)

        if meta.size and len(buffer) != meta.size:
            raise ProtocolError(f"size mismatch: got {len(buffer)}, metadata said {meta.size}")

        await self._store(device, meta, bytes(buffer))
        logger.info("Stored %s (%d bytes) for imei=%s", meta.filename, len(buffer), init.imei)

        await self._send(writer, CMD_CLOSE, b"", tx_crc)

    async def _send(self, writer: asyncio.StreamWriter, cmd_id: int, data: bytes, prev_crc: int) -> int:
        frame, new_crc = encode_packet(cmd_id, data, prev_crc)
        writer.write(frame)
        await writer.drain()
        return new_crc

    async def _recv(self, reader: asyncio.StreamReader, prev_crc: int, expected_cmd: Optional[int]):
        header = await reader.readexactly(4)
        data_len = int.from_bytes(header[2:4], "big")
        rest = await reader.readexactly(data_len + 2)
        pkt = decode_packet(header + rest, prev_crc)
        if expected_cmd is not None and pkt.cmd_id != expected_cmd:
            raise ProtocolError(f"expected cmd 0x{expected_cmd:04X}, got 0x{pkt.cmd_id:04X}")
        return pkt, pkt.crc
