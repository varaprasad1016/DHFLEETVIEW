"""
ISO 7816-4 APDU build/parse.

The forked TBA is a transparent APDU proxy and the tracker firmware drives the
tachograph auth sequence, so most of the time we only *relay* APDUs. These
helpers are for the cases where WE initiate — card health checks, and any
server-driven step in Path B.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class APDUResponse:
    sw1: str  # hex, e.g. "90"
    sw2: str  # hex, e.g. "00"
    data: bytes

    @property
    def status(self) -> str:
        return f"{self.sw1}{self.sw2}".upper()

    @property
    def ok(self) -> bool:
        return self.status == "9000"


class APDUSequencer:
    """Builds/parses ISO 7816-4 command/response APDUs."""

    @staticmethod
    def select_applet(aid: bytes) -> bytes:
        """A0 A4 00 00 [len] [aid]"""
        return bytes([0xA0, 0xA4, 0x00, 0x00, len(aid)]) + aid

    @staticmethod
    def external_authenticate(challenge: bytes) -> bytes:
        """82 00 [len] [challenge] 00"""
        return bytes([0x82, 0x00, len(challenge)]) + challenge + b"\x00"

    @staticmethod
    def get_response(length: int = 0) -> bytes:
        """C0 00 [length] 00"""
        return bytes([0xC0, 0x00, length & 0xFF, 0x00])

    @staticmethod
    def read_binary(offset: int, length: int) -> bytes:
        """B0 [offset_hi] [offset_lo] [length]"""
        return bytes([0xB0, (offset >> 8) & 0xFF, offset & 0xFF, length & 0xFF])

    @staticmethod
    def parse_response(raw: bytes) -> APDUResponse:
        """[data...] + SW1 + SW2"""
        if len(raw) < 2:
            raise ValueError("APDU response too short (need at least SW1 SW2)")
        return APDUResponse(f"{raw[-2]:02X}", f"{raw[-1]:02X}", raw[:-2])
