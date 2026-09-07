"""Tests for the TachoSync CRC-16 core."""

from app.protocol.crc import crc16_update, crc16_x25


def test_x25_known_vector():
    # CRC-16/X.25 of the canonical check string is 0x906E.
    assert crc16_x25(b"123456789") == 0x906E


def test_chaining_matches_single_pass():
    a, b = b"hello", b"world"
    single = crc16_update(a + b)
    chained = crc16_update(b, crc16_update(a))
    assert single == chained


def test_empty_input_returns_seed():
    assert crc16_update(b"", 0x1234) == 0x1234


def test_result_is_16_bit():
    assert 0 <= crc16_update(bytes(range(256))) <= 0xFFFF
