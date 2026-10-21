"""
Teltonika data protocol (Path A): TCP handshake, Codec 8 / 8-Extended AVL data,
and Codec 12 GPRS commands.

Implemented from the publicly documented Teltonika wire format (original code).
The AVL CRC is CRC-16/IBM (poly 0xA001, init 0) over the data field — distinct
from Path B's CRC. Anchor: crc16_ibm(b"123456789") == 0xBB3D.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CODEC_8 = 0x08
CODEC_8_EXT = 0x8E
CODEC_12 = 0x0C

CMD_TYPE_COMMAND = 0x05
CMD_TYPE_RESPONSE = 0x06

PREAMBLE = b"\x00\x00\x00\x00"


def crc16_ibm(data: bytes, crc: int = 0x0000) -> int:
    """CRC-16/IBM (a.k.a. ARC): reflected, poly 0xA001, init 0."""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


# --- TCP handshake ---

def parse_imei(raw: bytes) -> str:
    length = int.from_bytes(raw[0:2], "big")
    return raw[2:2 + length].decode("ascii")


def build_imei(imei: str) -> bytes:
    b = imei.encode("ascii")
    return len(b).to_bytes(2, "big") + b


IMEI_ACCEPT = b"\x01"
IMEI_REJECT = b"\x00"


# --- AVL data ---

@dataclass
class GpsElement:
    longitude: int
    latitude: int
    altitude: int
    angle: int
    satellites: int
    speed: int


@dataclass
class AvlRecord:
    timestamp_ms: int
    priority: int
    gps: GpsElement
    event_io_id: int
    io: dict[int, int] = field(default_factory=dict)


@dataclass
class AvlPacket:
    codec_id: int
    records: list[AvlRecord]


def _id_size(codec_id: int) -> int:
    return 2 if codec_id == CODEC_8_EXT else 1


def decode_avl_packet(frame: bytes) -> AvlPacket:
    """Decode a full AVL TCP data packet (preamble..CRC)."""
    if frame[0:4] != PREAMBLE:
        raise ValueError("bad preamble")
    data_len = int.from_bytes(frame[4:8], "big")
    data = frame[8:8 + data_len]
    crc_received = int.from_bytes(frame[8 + data_len:12 + data_len], "big")
    if crc16_ibm(data) != crc_received:
        raise ValueError("AVL CRC mismatch")

    codec_id = data[0]
    count = data[1]
    idsz = _id_size(codec_id)
    pos = 2
    records: list[AvlRecord] = []
    for _ in range(count):
        ts = int.from_bytes(data[pos:pos + 8], "big"); pos += 8
        priority = data[pos]; pos += 1
        lon = int.from_bytes(data[pos:pos + 4], "big"); pos += 4
        lat = int.from_bytes(data[pos:pos + 4], "big"); pos += 4
        alt = int.from_bytes(data[pos:pos + 2], "big"); pos += 2
        angle = int.from_bytes(data[pos:pos + 2], "big"); pos += 2
        sats = data[pos]; pos += 1
        speed = int.from_bytes(data[pos:pos + 2], "big"); pos += 2
        gps = GpsElement(lon, lat, alt, angle, sats, speed)

        event_io = int.from_bytes(data[pos:pos + idsz], "big"); pos += idsz
        pos += idsz  # total IO count (not needed for parsing)
        io: dict[int, int] = {}
        for val_size in (1, 2, 4, 8):
            n = int.from_bytes(data[pos:pos + idsz], "big"); pos += idsz
            for _ in range(n):
                io_id = int.from_bytes(data[pos:pos + idsz], "big"); pos += idsz
                io[io_id] = int.from_bytes(data[pos:pos + val_size], "big"); pos += val_size
        records.append(AvlRecord(ts, priority, gps, event_io, io))
    return AvlPacket(codec_id, records)


def encode_avl_packet(packet: AvlPacket) -> bytes:
    """Encode an AVL packet (Codec 8). Used by the mock device and tests."""
    idsz = _id_size(packet.codec_id)
    body = bytearray([packet.codec_id, len(packet.records)])
    for r in packet.records:
        body += r.timestamp_ms.to_bytes(8, "big")
        body.append(r.priority)
        body += r.gps.longitude.to_bytes(4, "big")
        body += r.gps.latitude.to_bytes(4, "big")
        body += r.gps.altitude.to_bytes(2, "big")
        body += r.gps.angle.to_bytes(2, "big")
        body.append(r.gps.satellites)
        body += r.gps.speed.to_bytes(2, "big")
        body += r.event_io_id.to_bytes(idsz, "big")
        body += len(r.io).to_bytes(idsz, "big")
        buckets = {1: [], 2: [], 4: [], 8: []}
        for io_id, val in r.io.items():
            size = 1 if val < 0x100 else 2 if val < 0x10000 else 4 if val < 0x100000000 else 8
            buckets[size].append((io_id, val))
        for size in (1, 2, 4, 8):
            body += len(buckets[size]).to_bytes(idsz, "big")
            for io_id, val in buckets[size]:
                body += io_id.to_bytes(idsz, "big")
                body += val.to_bytes(size, "big")
    body.append(len(packet.records))
    return PREAMBLE + len(body).to_bytes(4, "big") + bytes(body) + crc16_ibm(bytes(body)).to_bytes(4, "big")


def build_avl_ack(count: int) -> bytes:
    """Server ACK: 4-byte number of records accepted."""
    return count.to_bytes(4, "big")


# --- Codec 12 GPRS commands ---

def build_codec12_command(command: str) -> bytes:
    cmd = command.encode("ascii")
    body = bytes([CODEC_12, 0x01, CMD_TYPE_COMMAND]) + len(cmd).to_bytes(4, "big") + cmd + bytes([0x01])
    return PREAMBLE + len(body).to_bytes(4, "big") + body + crc16_ibm(body).to_bytes(4, "big")


def build_codec12_response(response: bytes) -> bytes:
    body = bytes([CODEC_12, 0x01, CMD_TYPE_RESPONSE]) + len(response).to_bytes(4, "big") + response + bytes([0x01])
    return PREAMBLE + len(body).to_bytes(4, "big") + body + crc16_ibm(body).to_bytes(4, "big")


def parse_codec12(frame: bytes) -> tuple[int, bytes]:
    """Return (type, payload) for a Codec 12 command/response frame."""
    data_len = int.from_bytes(frame[4:8], "big")
    data = frame[8:8 + data_len]
    if data[0] != CODEC_12:
        raise ValueError("not a Codec 12 frame")
    msg_type = data[2]
    size = int.from_bytes(data[3:7], "big")
    payload = data[7:7 + size]
    return msg_type, payload
