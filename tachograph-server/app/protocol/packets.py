"""
Packet framing for the Teltonika TachoSync (Path B) protocol on TCP 29000.

# ASSUMED PROTOCOL — the command IDs and frame layouts below are reconstructed
# from the closest public reference and are NOT confirmed against Teltonika's
# proprietary TachoSync spec. Anything a future correction touches lives here so
# the rest of the codebase never hard-codes a wire constant.
"""

from __future__ import annotations

from dataclasses import dataclass

from .crc import crc16_update

# --- Command IDs (ASSUMED) ---
CMD_CLOSE = 0x0000
CMD_START_TRANSFER = 0x0001
CMD_SYNC = 0x0003
CMD_DATA = 0x0004
CMD_TRANSFER_STATUS = 0x0005
CMD_FILE_REQUEST = 0x0008
CMD_REQUEST_METADATA = 0x000A
CMD_METADATA = 0x000B
CMD_REQUEST_PATH = 0x000C
CMD_FILE_PATH = 0x000D

MAX_DATA_LEN = 1024
INIT_PACKET_LEN = 16


@dataclass
class DataPacket:
    """A framed protocol packet: CMD_ID(2) + DataLen(2) + Data + CRC(2)."""

    cmd_id: int
    data: bytes
    crc: int


@dataclass
class InitPacket:
    """First packet a device sends: Header(2)=0x0000 + ProtoID(2) + IMEI(8) + Settings(4)."""

    protocol_id: int
    imei: str
    settings: int


def encode_packet(cmd_id: int, data: bytes, prev_crc: int) -> tuple[bytes, int]:
    """Frame a command. CRC is chained: seeded with ``prev_crc``.

    Returns ``(frame_bytes, new_crc)`` — feed ``new_crc`` into the next call.
    """
    if len(data) > MAX_DATA_LEN:
        raise ValueError(f"data too long: {len(data)} > {MAX_DATA_LEN}")
    body = cmd_id.to_bytes(2, "big") + len(data).to_bytes(2, "big") + data
    crc = crc16_update(body, prev_crc)
    return body + crc.to_bytes(2, "big"), crc


def decode_packet(frame: bytes, prev_crc: int) -> DataPacket:
    """Parse and verify one framed packet using the chained ``prev_crc`` seed."""
    if len(frame) < 6:
        raise ValueError("frame too short")
    cmd_id = int.from_bytes(frame[0:2], "big")
    data_len = int.from_bytes(frame[2:4], "big")
    end = 4 + data_len
    if len(frame) < end + 2:
        raise ValueError("truncated data/crc")
    data = frame[4:end]
    crc_received = int.from_bytes(frame[end:end + 2], "big")
    crc_expected = crc16_update(frame[:end], prev_crc)
    if crc_received != crc_expected:
        raise ValueError(f"CRC mismatch: got 0x{crc_received:04X}, expected 0x{crc_expected:04X}")
    return DataPacket(cmd_id, data, crc_received)


def decode_init_packet(raw: bytes) -> InitPacket:
    """Parse the device init packet.

    # ASSUMED: the 8-byte IMEI encoding (BCD vs raw big-endian integer) is
    # unconfirmed; exposed as hex here until the spec is verified.
    """
    if len(raw) < INIT_PACKET_LEN:
        raise ValueError(f"init packet too short: {len(raw)} < {INIT_PACKET_LEN}")
    protocol_id = int.from_bytes(raw[2:4], "big")
    imei = raw[4:12].hex()
    settings = int.from_bytes(raw[12:16], "big")
    return InitPacket(protocol_id=protocol_id, imei=imei, settings=settings)
