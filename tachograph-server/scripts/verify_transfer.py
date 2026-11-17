"""
End-to-end Phase 1 check with no infra: start the TachoSync server with mock
dependencies, connect the mock device, transfer a multi-chunk file, and assert
the server stored exactly what the device sent.

Run: python scripts/verify_transfer.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.protocol.fields import Metadata  # noqa: E402
from app.protocol.tacho_server import TachoSyncServer  # noqa: E402
from tests.test_protocol.mock_device import MockDevice  # noqa: E402

KNOWN_IMEI = "0123456789abcdef"


async def main() -> int:
    stored: dict[str, object] = {}

    async def lookup_device(imei: str):
        return {"imei": imei, "id": "dev-1"} if imei == KNOWN_IMEI else None

    async def get_pending_schedule(device):
        return {"file_type": 1} if device else None

    async def store_file(device, meta: Metadata, data: bytes):
        stored["device"] = device
        stored["meta"] = meta
        stored["data"] = data

    server = TachoSyncServer(
        lookup_device=lookup_device,
        get_pending_schedule=get_pending_schedule,
        store_file=store_file,
        host="127.0.0.1",
        port=0,
    )
    await server.start()

    # ~2.5 chunks, so chunking + reassembly is genuinely exercised.
    payload = bytes((i * 7) & 0xFF for i in range(2600))
    device = MockDevice(KNOWN_IMEI, "C_20260906_1.DDD", payload, file_type=1)
    await asyncio.wait_for(device.run("127.0.0.1", server.port), timeout=10)
    await server.stop()

    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    check("device closed cleanly", device.closed_cleanly)
    check("file was stored", "data" in stored)
    check("stored bytes == sent bytes", stored.get("data") == payload)
    check("filename preserved", getattr(stored.get("meta"), "filename", None) == "C_20260906_1.DDD")
    check("metadata size matches", getattr(stored.get("meta"), "size", None) == len(payload))

    # Unknown IMEI must be closed with no schedule (no store).
    stored.clear()
    unknown = MockDevice("ffffffffffffffff", "x.DDD", b"nope")
    await asyncio.wait_for(unknown.run("127.0.0.1", (await restart(server)).port), timeout=10)
    await server.stop()
    check("unknown device: nothing stored", "data" not in stored)
    check("unknown device: closed cleanly", unknown.closed_cleanly)

    print(f"\nRESULT: {'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


async def restart(server: TachoSyncServer) -> TachoSyncServer:
    await server.start()
    return server


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
