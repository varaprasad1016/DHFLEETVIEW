"""End-to-end tests for the Path B TachoSync server, using the mock device."""

import asyncio

import pytest

from app.protocol.fields import Metadata
from app.protocol.tacho_server import TachoSyncServer
from tests.test_protocol.mock_device import MockDevice

KNOWN_IMEI = "0123456789abcdef"


def _make_server(stored):
    async def lookup_device(imei):
        return {"imei": imei} if imei == KNOWN_IMEI else None

    async def get_pending_schedule(device):
        return {"file_type": 1} if device else None

    async def store_file(device, meta: Metadata, data: bytes):
        stored["meta"] = meta
        stored["data"] = data

    return TachoSyncServer(
        lookup_device=lookup_device,
        get_pending_schedule=get_pending_schedule,
        store_file=store_file,
        host="127.0.0.1",
        port=0,
    )


@pytest.mark.asyncio
async def test_multichunk_transfer_roundtrip():
    stored = {}
    server = _make_server(stored)
    await server.start()
    payload = bytes((i * 7) & 0xFF for i in range(2600))  # > 2 chunks
    device = MockDevice(KNOWN_IMEI, "C_20260906_1.DDD", payload)
    await asyncio.wait_for(device.run("127.0.0.1", server.port), timeout=10)
    await server.stop()

    assert device.closed_cleanly
    assert stored["data"] == payload
    assert stored["meta"].filename == "C_20260906_1.DDD"
    assert stored["meta"].size == len(payload)


@pytest.mark.asyncio
async def test_unknown_device_closed_without_store():
    stored = {}
    server = _make_server(stored)
    await server.start()
    device = MockDevice("ffffffffffffffff", "x.DDD", b"data")
    await asyncio.wait_for(device.run("127.0.0.1", server.port), timeout=10)
    await server.stop()

    assert device.closed_cleanly
    assert "data" not in stored
