"""
Higher-level payload structures carried inside Path B packets.

# ASSUMED encodings — reconstructed, not confirmed against Teltonika's spec.
# Kept separate from framing so a correction here never touches crc.py/packets.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# File types (ASSUMED)
FILE_TYPE_DRIVER_CARD_1 = 1
FILE_TYPE_DRIVER_CARD_2 = 2
FILE_TYPE_VEHICLE = 3


@dataclass
class Metadata:
    size: int
    file_type: int
    filename: str


def build_metadata(m: Metadata) -> bytes:
    """size(4) + file_type(1) + name_len(2) + name(utf-8)."""
    name = m.filename.encode("utf-8")
    return m.size.to_bytes(4, "big") + bytes([m.file_type & 0xFF]) + len(name).to_bytes(2, "big") + name


def parse_metadata(data: bytes) -> Metadata:
    if len(data) < 7:
        raise ValueError("metadata too short")
    size = int.from_bytes(data[0:4], "big")
    file_type = data[4]
    name_len = int.from_bytes(data[5:7], "big")
    filename = data[7:7 + name_len].decode("utf-8", errors="replace")
    return Metadata(size=size, file_type=file_type, filename=filename)


def build_packet_count(n: int) -> bytes:
    return n.to_bytes(4, "big")


def parse_packet_count(data: bytes) -> int:
    return int.from_bytes(data[0:4], "big")


def build_offset(offset: int) -> bytes:
    return offset.to_bytes(4, "big")
