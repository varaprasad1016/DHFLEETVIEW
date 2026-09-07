"""
Phase 3 end-to-end check (Path A), no hardware: exercise the GPRS server against
the mock Teltonika device across three scenarios — AVL ingest, query_ddd file
download, and handshake rejection of an unknown IMEI.

Run: python scripts/verify_gprs.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.protocol.gprs_handler import GprsServer  # noqa: E402
from app.protocol.teltonika_codec import AvlPacket, AvlRecord, GpsElement, CODEC_8  # noqa: E402
from tests.test_protocol.mock_teltonika import MockTeltonikaDevice  # noqa: E402

KNOWN = "356938035643809"
DDD_COMMAND = "web_tacho query_ddd"
results = []


def check(label, cond):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


async def make_server(schedule_present, captures):
    async def lookup(imei):
        return {"imei": imei} if imei == KNOWN else None

    async def get_schedule(device):
        return {"file_type": "vehicle"} if schedule_present else None

    async def on_positions(device, packet):
        captures["packet"] = packet

    async def store_file(device, filename, data):
        captures["filename"] = filename
        captures["data"] = data

    server = GprsServer(
        lookup_device=lookup,
        get_pending_schedule=get_schedule,
        on_positions=on_positions,
        store_file=store_file,
        ddd_command=DDD_COMMAND,
        host="127.0.0.1",
        port=0,
    )
    await server.start()
    return server


async def main() -> int:
    # --- Scenario 1: AVL ingest ---
    cap = {}
    server = await make_server(False, cap)
    packet = AvlPacket(CODEC_8, [
        AvlRecord(1788000000000, 1, GpsElement(190756, 51728460, 0, 194, 11, 0), 0, {1: 1, 66: 24500}),
        AvlRecord(1788000060000, 0, GpsElement(190800, 51728500, 5, 90, 9, 40), 66, {1: 0}),
    ])
    dev = MockTeltonikaDevice(KNOWN, "avl", avl_packet=packet)
    await asyncio.wait_for(dev.run("127.0.0.1", server.port), timeout=10)
    await server.stop()
    check("AVL: handshake accepted", dev.accepted)
    check("AVL: server ACKed 2 records", dev.avl_ack == 2)
    check("AVL: server parsed both records", len(cap.get("packet").records) == 2)
    check("AVL: IO decoded", cap["packet"].records[0].io == {1: 1, 66: 24500})

    # --- Scenario 2: query_ddd download ---
    cap = {}
    server = await make_server(True, cap)
    payload = bytes((i * 5) & 0xFF for i in range(4096))
    dev = MockTeltonikaDevice(KNOWN, "ddd", ddd_filename="M_20260906_1.DDD", ddd_payload=payload)
    await asyncio.wait_for(dev.run("127.0.0.1", server.port), timeout=10)
    await server.stop()
    check("DDD: device got query_ddd command", dev.received_command == DDD_COMMAND.encode())
    check("DDD: file stored byte-identical", cap.get("data") == payload)
    check("DDD: filename preserved", cap.get("filename") == "M_20260906_1.DDD")

    # --- Scenario 3: unknown IMEI rejected ---
    cap = {}
    server = await make_server(False, cap)
    dev = MockTeltonikaDevice("000000000000000", "avl", avl_packet=packet)
    await asyncio.wait_for(dev.run("127.0.0.1", server.port), timeout=10)
    await server.stop()
    check("Reject: unknown IMEI not accepted", dev.accepted is False)
    check("Reject: nothing ingested", "packet" not in cap)

    ok = all(results)
    print(f"\nRESULT: {'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
