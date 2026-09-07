"""
Mock Teltonika device speaking the ASSUMED TachoSync (Path B) protocol.

Lets Phase 1 be verified end-to-end with no tracker and no reader present.
"""

from __future__ import annotations

import asyncio

from app.protocol.crc import INIT_DEFAULT
from app.protocol.fields import Metadata, build_metadata, build_packet_count
from app.protocol.packets import (
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
    MAX_DATA_LEN,
    decode_packet,
    encode_packet,
)


def build_init(imei_hex: str, protocol_id: int = 1, settings: int = 0x0F) -> bytes:
    imei = bytes.fromhex(imei_hex.ljust(16, "0"))[:8]
    return b"\x00\x00" + protocol_id.to_bytes(2, "big") + imei + settings.to_bytes(4, "big")


class MockDevice:
    def __init__(self, imei_hex: str, filename: str, payload: bytes, file_type: int = 1):
        self.imei_hex = imei_hex
        self.filename = filename
        self.payload = payload
        self.file_type = file_type
        self.closed_cleanly = False
        self._chunks: list[bytes] = []

    async def run(self, host: str, port: int) -> None:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(build_init(self.imei_hex))
            await writer.drain()
            tx_crc = INIT_DEFAULT  # our outgoing chain
            rx_crc = INIT_DEFAULT  # server's outgoing chain (we decode)
            while True:
                pkt, rx_crc = await self._recv(reader, rx_crc)
                if pkt.cmd_id == CMD_CLOSE:
                    self.closed_cleanly = True
                    break
                if pkt.cmd_id == CMD_REQUEST_PATH:
                    path = ("/tacho/" + self.filename).encode("utf-8")
                    tx_crc = await self._send(writer, CMD_FILE_PATH, path, tx_crc)
                elif pkt.cmd_id == CMD_REQUEST_METADATA:
                    meta = build_metadata(Metadata(len(self.payload), self.file_type, self.filename))
                    tx_crc = await self._send(writer, CMD_METADATA, meta, tx_crc)
                elif pkt.cmd_id == CMD_FILE_REQUEST:
                    self._chunks = self._chunk(self.payload)
                    tx_crc = await self._send(
                        writer, CMD_START_TRANSFER, build_packet_count(len(self._chunks)), tx_crc
                    )
                elif pkt.cmd_id == CMD_SYNC:
                    for chunk in self._chunks:
                        tx_crc = await self._send(writer, CMD_DATA, chunk, tx_crc)
                    tx_crc = await self._send(writer, CMD_TRANSFER_STATUS, b"\x00", tx_crc)
                else:
                    break
        finally:
            writer.close()

    @staticmethod
    def _chunk(data: bytes) -> list[bytes]:
        if not data:
            return [b""]
        return [data[i:i + MAX_DATA_LEN] for i in range(0, len(data), MAX_DATA_LEN)]

    async def _send(self, writer, cmd_id, data, prev_crc):
        frame, new_crc = encode_packet(cmd_id, data, prev_crc)
        writer.write(frame)
        await writer.drain()
        return new_crc

    async def _recv(self, reader, prev_crc):
        header = await reader.readexactly(4)
        data_len = int.from_bytes(header[2:4], "big")
        rest = await reader.readexactly(data_len + 2)
        pkt = decode_packet(header + rest, prev_crc)
        return pkt, pkt.crc
