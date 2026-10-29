"""Tests for TachoSync packet framing (ASSUMED protocol)."""

import pytest

from app.protocol.crc import INIT_DEFAULT
from app.protocol.packets import (
    CMD_DATA,
    MAX_DATA_LEN,
    decode_init_packet,
    decode_packet,
    encode_packet,
)


def test_encode_decode_roundtrip():
    frame, crc = encode_packet(CMD_DATA, b"\x01\x02\x03\x04", INIT_DEFAULT)
    pkt = decode_packet(frame, INIT_DEFAULT)
    assert pkt.cmd_id == CMD_DATA
    assert pkt.data == b"\x01\x02\x03\x04"
    assert pkt.crc == crc


def test_chained_two_packets():
    f1, c1 = encode_packet(CMD_DATA, b"aaaa", INIT_DEFAULT)
    f2, c2 = encode_packet(CMD_DATA, b"bbbb", c1)
    assert decode_packet(f1, INIT_DEFAULT).data == b"aaaa"
    assert decode_packet(f2, c1).data == b"bbbb"
    # A wrong seed on the second packet must fail the CRC check.
    with pytest.raises(ValueError):
        decode_packet(f2, INIT_DEFAULT)


def test_corruption_detected():
    frame, _ = encode_packet(CMD_DATA, b"payload", INIT_DEFAULT)
    corrupt = bytearray(frame)
    corrupt[5] ^= 0xFF
    with pytest.raises(ValueError):
        decode_packet(bytes(corrupt), INIT_DEFAULT)


def test_oversized_data_rejected():
    with pytest.raises(ValueError):
        encode_packet(CMD_DATA, b"\x00" * (MAX_DATA_LEN + 1), INIT_DEFAULT)


def test_init_packet_parse():
    raw = (
        b"\x00\x00"              # header 0x0000
        + b"\x00\x05"           # protocol id 5
        + bytes.fromhex("0123456789abcdef")  # 8-byte IMEI (encoding ASSUMED)
        + b"\x00\x00\x00\x0f"   # settings bitmask
    )
    init = decode_init_packet(raw)
    assert init.protocol_id == 5
    assert init.imei == "0123456789abcdef"
    assert init.settings == 0x0F
