"""Path A tests: codec correctness + GPRS server end-to-end via the mock device."""

import asyncio

import pytest

from app.protocol.gprs_handler import GprsServer
from app.protocol.teltonika_codec import (
    CODEC_8,
    AvlPacket,
    AvlRecord,
    GpsElement,
    build_codec12_command,
    build_imei,
    crc16_ibm,
    decode_avl_packet,
    encode_avl_packet,
    parse_codec12,
    parse_imei,
)
from tests.test_protocol.mock_teltonika import MockTeltonikaDevice

KNOWN = "356938035643809"


def test_crc16_ibm_vector():
    assert crc16_ibm(b"123456789") == 0xBB3D


def test_imei_roundtrip():
    assert parse_imei(build_imei(KNOWN)) == KNOWN


def test_avl_roundtrip_mixed_io():
    p = AvlPacket(CODEC_8, [
        AvlRecord(1788000000000, 1, GpsElement(190756, 51728460, 0, 194, 11, 0), 0, {1: 1, 66: 24500, 241: 12345678}),
    ])
    d = decode_avl_packet(encode_avl_packet(p))
    assert d.records[0].io == {1: 1, 66: 24500, 241: 12345678}
    assert d.records[0].gps.satellites == 11


def test_codec12_command_roundtrip():
    mtype, payload = parse_codec12(build_codec12_command("web_tacho query_ddd"))
    assert payload == b"web_tacho query_ddd"


async def _server(schedule_present, cap):
    async def lookup(imei):
        return {"imei": imei} if imei == KNOWN else None

    async def get_schedule(device):
        return {"x": 1} if schedule_present else None

    async def on_positions(device, packet):
        cap["packet"] = packet

    async def store_file(device, filename, data):
        cap["filename"], cap["data"] = filename, data

    s = GprsServer(lookup_device=lookup, get_pending_schedule=get_schedule,
                   on_positions=on_positions, store_file=store_file,
                   ddd_command="web_tacho query_ddd", host="127.0.0.1", port=0)
    await s.start()
    return s


@pytest.mark.asyncio
async def test_avl_ingest_and_ack():
    cap = {}
    s = await _server(False, cap)
    packet = AvlPacket(CODEC_8, [
        AvlRecord(1788000000000, 1, GpsElement(1, 2, 0, 0, 8, 0), 0, {1: 1}),
        AvlRecord(1788000060000, 0, GpsElement(3, 4, 0, 0, 9, 40), 0, {}),
    ])
    dev = MockTeltonikaDevice(KNOWN, "avl", avl_packet=packet)
    await asyncio.wait_for(dev.run("127.0.0.1", s.port), timeout=10)
    await s.stop()
    assert dev.accepted and dev.avl_ack == 2
    assert len(cap["packet"].records) == 2


@pytest.mark.asyncio
async def test_query_ddd_download():
    cap = {}
    s = await _server(True, cap)
    payload = bytes(range(256)) * 16
    dev = MockTeltonikaDevice(KNOWN, "ddd", ddd_filename="M_1.DDD", ddd_payload=payload)
    await asyncio.wait_for(dev.run("127.0.0.1", s.port), timeout=10)
    await s.stop()
    assert dev.received_command == b"web_tacho query_ddd"
    assert cap["data"] == payload and cap["filename"] == "M_1.DDD"


@pytest.mark.asyncio
async def test_unknown_imei_rejected():
    cap = {}
    s = await _server(False, cap)
    dev = MockTeltonikaDevice("000000000000000", "avl",
                              avl_packet=AvlPacket(CODEC_8, []))
    await asyncio.wait_for(dev.run("127.0.0.1", s.port), timeout=10)
    await s.stop()
    assert dev.accepted is False and "packet" not in cap
