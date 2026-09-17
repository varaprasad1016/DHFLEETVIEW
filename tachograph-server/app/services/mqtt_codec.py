"""Minimal MQTT v5 packet codec for the Tacho Bridge endpoint.

Only what the Tacho Bridge App uses: CONNECT/CONNACK, PUBLISH at QoS 0/1 with
PUBACK, SUBSCRIBE/SUBACK, PINGREQ/PINGRESP and DISCONNECT. No broker semantics:
the bridge server addresses each connection directly, the way the app expects.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field

CONNECT, CONNACK, PUBLISH, PUBACK, PUBREC, PUBREL, PUBCOMP = 1, 2, 3, 4, 5, 6, 7
SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK, PINGREQ, PINGRESP, DISCONNECT, AUTH = 8, 9, 10, 11, 12, 13, 14, 15

# CONNACK / DISCONNECT reason codes
SUCCESS = 0x00
UNSPECIFIED_ERROR = 0x80
MALFORMED_PACKET = 0x81
PROTOCOL_ERROR = 0x82
UNSUPPORTED_PROTOCOL_VERSION = 0x84
CLIENT_ID_NOT_VALID = 0x85
BAD_USERNAME_OR_PASSWORD = 0x86
NOT_AUTHORIZED = 0x87
SERVER_BUSY = 0x89
SESSION_TAKEN_OVER = 0x8E
KEEP_ALIVE_TIMEOUT = 0x8D
PACKET_TOO_LARGE = 0x95

MAX_PACKET = 4 * 1024 * 1024  # log chunks are up to 1 MiB

# Property id -> wire type
_BYTE, _U16, _U32, _VARINT, _STR, _BIN, _PAIR = range(7)
_PROPS = {
    0x01: _BYTE, 0x02: _U32, 0x03: _STR, 0x08: _STR, 0x09: _BIN, 0x0B: _VARINT, 0x11: _U32,
    0x12: _STR, 0x13: _U16, 0x15: _STR, 0x16: _BIN, 0x17: _BYTE, 0x18: _U32, 0x19: _BYTE,
    0x1A: _STR, 0x1C: _STR, 0x1F: _STR, 0x21: _U16, 0x22: _U16, 0x23: _U16, 0x24: _BYTE,
    0x25: _BYTE, 0x26: _PAIR, 0x27: _U32, 0x28: _BYTE, 0x29: _BYTE, 0x2A: _BYTE,
}
PROP_SESSION_EXPIRY = 0x11
PROP_RECEIVE_MAXIMUM = 0x21
PROP_MAX_PACKET_SIZE = 0x27
PROP_TOPIC_ALIAS = 0x23
PROP_REASON_STRING = 0x1F


class MalformedPacket(Exception):
    pass


@dataclass
class Packet:
    type: int
    flags: int
    body: bytes


@dataclass
class Connect:
    protocol_version: int
    client_id: str
    keep_alive: int
    clean_start: bool
    username: str | None
    password: bytes | None
    properties: dict = field(default_factory=dict)


@dataclass
class Publish:
    topic: str
    payload: bytes
    qos: int = 0
    packet_id: int | None = None
    retain: bool = False
    dup: bool = False
    properties: dict = field(default_factory=dict)


# ---------------------------------------------------------------- primitives
def encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


class Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise MalformedPacket("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def byte(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def varint(self) -> int:
        mult, value = 1, 0
        for _ in range(4):
            b = self.byte()
            value += (b & 0x7F) * mult
            if not b & 0x80:
                return value
            mult *= 128
        raise MalformedPacket("varint too long")

    def string(self) -> str:
        try:
            return self.take(self.u16()).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedPacket("bad utf-8") from exc

    def binary(self) -> bytes:
        return self.take(self.u16())

    def rest(self) -> bytes:
        chunk = self.data[self.pos:]
        self.pos = len(self.data)
        return chunk

    def properties(self) -> dict:
        end = self.varint()
        end += self.pos
        if end > len(self.data):
            raise MalformedPacket("properties overrun")
        props: dict = {}
        while self.pos < end:
            pid = self.varint()
            kind = _PROPS.get(pid)
            if kind is None:
                raise MalformedPacket(f"unknown property {pid:#x}")
            if kind == _BYTE:
                value = self.byte()
            elif kind == _U16:
                value = self.u16()
            elif kind == _U32:
                value = self.u32()
            elif kind == _VARINT:
                value = self.varint()
            elif kind == _STR:
                value = self.string()
            elif kind == _BIN:
                value = self.binary()
            else:
                value = (self.string(), self.string())
            if kind == _PAIR:
                props.setdefault(pid, []).append(value)
            else:
                props[pid] = value
        return props


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def _props(props: dict | None) -> bytes:
    out = bytearray()
    for pid, value in (props or {}).items():
        kind = _PROPS[pid]
        values = value if kind == _PAIR else [value]
        for v in values:
            out += encode_varint(pid)
            if kind == _BYTE:
                out.append(v)
            elif kind == _U16:
                out += struct.pack(">H", v)
            elif kind == _U32:
                out += struct.pack(">I", v)
            elif kind == _VARINT:
                out += encode_varint(v)
            elif kind == _STR:
                out += _str(v)
            elif kind == _BIN:
                out += struct.pack(">H", len(v)) + v
            else:
                out += _str(v[0]) + _str(v[1])
    return encode_varint(len(out)) + bytes(out)


def _packet(ptype: int, flags: int, body: bytes) -> bytes:
    return bytes([(ptype << 4) | flags]) + encode_varint(len(body)) + body


# ---------------------------------------------------------------- stream IO
async def read_packet(reader: asyncio.StreamReader, max_size: int = MAX_PACKET) -> Packet:
    first = await reader.readexactly(1)
    mult, length = 1, 0
    for _ in range(4):
        b = (await reader.readexactly(1))[0]
        length += (b & 0x7F) * mult
        if not b & 0x80:
            break
        mult *= 128
    else:
        raise MalformedPacket("remaining length too long")
    if length > max_size:
        raise MalformedPacket("packet too large")
    body = await reader.readexactly(length) if length else b""
    return Packet(first[0] >> 4, first[0] & 0x0F, body)


# ---------------------------------------------------------------- decoders
def decode_connect(p: Packet) -> Connect:
    r = Reader(p.body)
    if r.string() not in ("MQTT", "MQIsdp"):
        raise MalformedPacket("not MQTT")
    version = r.byte()
    flags = r.byte()
    keep_alive = r.u16()
    props = r.properties() if version == 5 else {}
    client_id = r.string()
    if flags & 0x04:  # will
        if version == 5:
            r.properties()
        r.string()
        r.binary()
    username = r.string() if flags & 0x80 else None
    password = r.binary() if flags & 0x40 else None
    return Connect(version, client_id, keep_alive, bool(flags & 0x02), username, password, props)


def decode_publish(p: Packet) -> Publish:
    r = Reader(p.body)
    qos = (p.flags >> 1) & 0x03
    if qos == 3:
        raise MalformedPacket("qos 3")
    topic = r.string()
    packet_id = r.u16() if qos else None
    props = r.properties()
    return Publish(topic, r.rest(), qos, packet_id, bool(p.flags & 0x01), bool(p.flags & 0x08), props)


def decode_packet_id(p: Packet) -> int:
    return Reader(p.body).u16()


def decode_subscribe(p: Packet) -> tuple[int, list[str]]:
    r = Reader(p.body)
    packet_id = r.u16()
    r.properties()
    topics = []
    while r.pos < len(r.data):
        topics.append(r.string())
        r.byte()
    return packet_id, topics


def decode_unsubscribe(p: Packet) -> tuple[int, list[str]]:
    r = Reader(p.body)
    packet_id = r.u16()
    r.properties()
    topics = []
    while r.pos < len(r.data):
        topics.append(r.string())
    return packet_id, topics


# ---------------------------------------------------------------- encoders
def connack(reason: int, session_present: bool = False, props: dict | None = None) -> bytes:
    return _packet(CONNACK, 0, bytes([1 if session_present else 0, reason]) + _props(props))


def publish(topic: str, payload: bytes, qos: int = 1, packet_id: int | None = None) -> bytes:
    body = _str(topic)
    if qos:
        body += struct.pack(">H", packet_id or 1)
    body += _props(None) + payload
    return _packet(PUBLISH, qos << 1, body)


def puback(packet_id: int, reason: int = SUCCESS) -> bytes:
    if reason == SUCCESS:
        return _packet(PUBACK, 0, struct.pack(">H", packet_id))
    return _packet(PUBACK, 0, struct.pack(">HB", packet_id, reason) + _props(None))


def suback(packet_id: int, count: int, granted_qos: int = 1) -> bytes:
    return _packet(SUBACK, 0, struct.pack(">H", packet_id) + _props(None) + bytes([granted_qos] * count))


def unsuback(packet_id: int, count: int) -> bytes:
    return _packet(UNSUBACK, 0, struct.pack(">H", packet_id) + _props(None) + bytes([0] * count))


def pingresp() -> bytes:
    return _packet(PINGRESP, 0, b"")


def disconnect(reason: int = SUCCESS, message: str | None = None) -> bytes:
    props = {PROP_REASON_STRING: message} if message else None
    return _packet(DISCONNECT, 0, bytes([reason]) + _props(props))
