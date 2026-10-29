"""
Path A: GPRS command handler over the standard Teltonika data protocol (TCP 21756).

Handshake -> AVL ingest (ACK) -> `query_ddd` via Codec 12 when a download is due.

# ASSUMED: the exact framing of the DDD payload as it returns over the data
# channel is not fully public. The command exchange (handshake, AVL, Codec 12)
# is from the documented format; the trailing DDD blob framing below is ASSUMED
# and isolated behind read_ddd_blob()/build_ddd_blob() for easy correction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from app.protocol.teltonika_codec import (
    CMD_TYPE_RESPONSE,
    IMEI_ACCEPT,
    IMEI_REJECT,
    PREAMBLE,
    AvlPacket,
    build_avl_ack,
    build_codec12_command,
    decode_avl_packet,
    parse_codec12,
)

logger = logging.getLogger(__name__)

LookupDevice = Callable[[str], Awaitable[Optional[object]]]
GetPendingSchedule = Callable[[object], Awaitable[Optional[object]]]
OnPositions = Callable[[object, AvlPacket], Awaitable[None]]
StoreFile = Callable[[object, str, bytes], Awaitable[None]]


@dataclass
class DddBlob:
    filename: str
    data: bytes


def build_ddd_blob(blob: DddBlob) -> bytes:
    """# ASSUMED: name_len(2) + name + file_len(4) + bytes."""
    name = blob.filename.encode("utf-8")
    return len(name).to_bytes(2, "big") + name + len(blob.data).to_bytes(4, "big") + blob.data


class GprsServer:
    def __init__(
        self,
        *,
        lookup_device: LookupDevice,
        get_pending_schedule: GetPendingSchedule,
        on_positions: OnPositions,
        store_file: StoreFile,
        ddd_command: str = "web_tacho query_ddd",
        host: str = "0.0.0.0",
        port: int = 21756,
    ):
        self._lookup = lookup_device
        self._schedule = get_pending_schedule
        self._on_positions = on_positions
        self._store = store_file
        self._ddd_command = ddd_command
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> asyncio.AbstractServer:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        h, p = self._server.sockets[0].getsockname()[:2]
        logger.info("GPRS (Path A) listening on %s:%s", h, p)
        return self._server

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1] if self._server else self._port

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            imei = await self._handshake(reader, writer)
            if imei is None:
                return
            device = await self._lookup(imei)
            if device is None:
                writer.write(IMEI_REJECT)
                await writer.drain()
                return
            writer.write(IMEI_ACCEPT)
            await writer.drain()

            schedule = await self._schedule(device)
            if schedule is not None:
                await self._download_ddd(reader, writer, device, imei)
            else:
                await self._ingest_avl(reader, writer, device)
        except (asyncio.IncompleteReadError, ValueError) as exc:
            logger.warning("GPRS session error: %s", exc)
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handshake(self, reader, writer) -> Optional[str]:
        length = int.from_bytes(await reader.readexactly(2), "big")
        if length == 0 or length > 20:
            return None
        return (await reader.readexactly(length)).decode("ascii")

    async def _ingest_avl(self, reader, writer, device) -> None:
        while True:
            try:
                packet = await self._read_avl(reader)
            except asyncio.IncompleteReadError:
                return
            await self._on_positions(device, packet)
            writer.write(build_avl_ack(len(packet.records)))
            await writer.drain()

    async def _download_ddd(self, reader, writer, device, imei) -> None:
        writer.write(build_codec12_command(self._ddd_command))
        await writer.drain()
        msg_type, _payload = await self._read_codec12(reader)
        if msg_type != CMD_TYPE_RESPONSE:
            raise ValueError(f"expected Codec12 response, got type {msg_type}")
        blob = await self._read_ddd_blob(reader)
        await self._store(device, blob.filename, blob.data)
        logger.info("Path A: stored %s (%d bytes) for imei=%s", blob.filename, len(blob.data), imei)

    async def _read_avl(self, reader) -> AvlPacket:
        pre = await reader.readexactly(4)
        if pre != PREAMBLE:
            raise ValueError("bad AVL preamble")
        dl = await reader.readexactly(4)
        n = int.from_bytes(dl, "big")
        rest = await reader.readexactly(n + 4)
        return decode_avl_packet(pre + dl + rest)

    async def _read_codec12(self, reader):
        pre = await reader.readexactly(4)
        dl = await reader.readexactly(4)
        n = int.from_bytes(dl, "big")
        rest = await reader.readexactly(n + 4)
        return parse_codec12(pre + dl + rest)

    async def _read_ddd_blob(self, reader) -> DddBlob:
        name_len = int.from_bytes(await reader.readexactly(2), "big")
        name = (await reader.readexactly(name_len)).decode("utf-8")
        file_len = int.from_bytes(await reader.readexactly(4), "big")
        data = await reader.readexactly(file_len)
        return DddBlob(name, data)
