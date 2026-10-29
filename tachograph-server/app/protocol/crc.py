"""
CRC-16 for the Teltonika TachoSync (Path B) binary protocol.

Polynomial 0x8408 — the reflected form of 0x1021 (the CRC-CCITT / X.25 family).
The file transfer uses a *chained* CRC: each packet's checksum is seeded with
the previous packet's CRC value rather than a fixed init. The first packet uses
INIT_DEFAULT.

# ASSUMED: the exact seed/xor conventions are reconstructed from the closest
# public reference (the DSM/ADAS file-transfer protocol) and MUST be confirmed
# against Teltonika's proprietary TachoSync specification before production use.
# Every constant a future correction would touch lives in this module.
"""

from __future__ import annotations

POLY = 0x8408
INIT_DEFAULT = 0xFFFF


def crc16_update(data: bytes, crc: int = INIT_DEFAULT) -> int:
    """Running, reflected CRC-16 (poly 0x8408).

    Pass the value returned for the previous packet as ``crc`` to chain the
    checksum across packets. No final XOR is applied, so the return value can be
    fed straight into the next call.
    """
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ POLY
            else:
                crc >>= 1
    return crc & 0xFFFF


def crc16_x25(data: bytes) -> int:
    """Standard CRC-16/X.25 (init 0xFFFF, reflected, final XOR 0xFFFF).

    Kept as a known-answer anchor so the core routine is provably correct:
    ``crc16_x25(b"123456789") == 0x906E``.
    """
    return crc16_update(data, INIT_DEFAULT) ^ 0xFFFF
