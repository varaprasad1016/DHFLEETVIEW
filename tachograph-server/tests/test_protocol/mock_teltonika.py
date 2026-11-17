"""Mock Teltonika device speaking the Path A data protocol (handshake, AVL, Codec 12)."""

from __future__ import annotations

import asyncio
from typing import Optional

from app.protocol.gprs_handler import DddBlob, build_ddd_blob
from app.protocol.teltonika_codec import (
    IMEI_ACCEPT,
    AvlPacket,
    build_codec12_response,
    build_imei,
    encode_avl_packet,
    parse_codec12,
)


class MockTeltonikaDevice:
    def __init__(
        self,
        imei: str,
        mode: str,  # "avl" or "ddd"
        *,
        avl_packet: Optional[AvlPacket] = None,
        ddd_filename: str = "",
        ddd_payload: bytes = b"",
    ):
        self.imei = imei
        self.mode = mode
        self.avl_packet = avl_packet
        self.ddd_filename = ddd_filename
        self.ddd_payload = ddd_payload
        # observed results
        self.accepted = False
        self.avl_ack: Optional[int] = None
        self.received_command: Optional[bytes] = None

    async def run(self, host: str, port: int) -> None:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(build_imei(self.imei))
            await writer.drain()
            self.accepted = (await reader.readexactly(1)) == IMEI_ACCEPT
            if not self.accepted:
                return

            if self.mode == "avl":
                writer.write(encode_avl_packet(self.avl_packet))
                await writer.drain()
                self.avl_ack = int.from_bytes(await reader.readexactly(4), "big")

            elif self.mode == "ddd":
                _type, payload = parse_codec12(await self._read_frame(reader))
                self.received_command = payload
                writer.write(build_codec12_response(b"OK"))
                await writer.drain()
                writer.write(build_ddd_blob(DddBlob(self.ddd_filename, self.ddd_payload)))
                await writer.drain()
        finally:
            writer.close()

    @staticmethod
    async def _read_frame(reader) -> bytes:
        pre = await reader.readexactly(4)
        dl = await reader.readexactly(4)
        n = int.from_bytes(dl, "big")
        rest = await reader.readexactly(n + 4)
        return pre + dl + rest
