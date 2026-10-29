"""Tests for the TBA bridge, APDU relay, and card session priority ordering."""

import asyncio

import pytest

from app.services.apdu import APDUSequencer
from app.services.card_session import (
    PRIORITY_OVERDUE,
    PRIORITY_ROUTINE,
    PRIORITY_WARNING,
    CardSessionManager,
)
from app.services.tba_bridge import TBABridge
from tests.test_services.mock_tba import InMemoryMockTBA


def _wired_bridge():
    bridge = TBABridge()
    mock = InMemoryMockTBA(cards=[
        {"card_id": "card-001", "present": True, "busy": False},
        {"card_id": "card-002", "present": True, "busy": True},
    ])
    mock.attach(bridge)
    return bridge, mock


@pytest.mark.asyncio
async def test_status_and_available_cards():
    bridge, mock = _wired_bridge()
    await mock.push_status()
    assert bridge.connected
    assert bridge.available_cards == ["card-001"]
    assert bridge.card_status("card-002").busy is True


@pytest.mark.asyncio
async def test_apdu_relay_roundtrip():
    bridge, _ = _wired_bridge()
    apdu = APDUSequencer.select_applet(bytes.fromhex("3F0001010000"))
    resp = await bridge.send_apdu("card-001", apdu)
    assert resp.ok
    assert resp.data == bytes.fromhex("3F0001010000")


@pytest.mark.asyncio
async def test_card_session_priority_order():
    bridge, _ = _wired_bridge()
    mgr = CardSessionManager(bridge)
    held = await mgr.acquire("card-001", PRIORITY_ROUTINE)
    order = []

    async def waiter(priority):
        session = await mgr.acquire("card-001", priority)
        order.append(priority)
        await mgr.release(session)

    tasks = [
        asyncio.create_task(waiter(PRIORITY_ROUTINE)),
        asyncio.create_task(waiter(PRIORITY_OVERDUE)),
        asyncio.create_task(waiter(PRIORITY_WARNING)),
    ]
    await asyncio.sleep(0.05)
    assert mgr.is_busy("card-001")
    await mgr.release(held)
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    assert order == [PRIORITY_OVERDUE, PRIORITY_WARNING, PRIORITY_ROUTINE]
    assert not mgr.is_busy("card-001")


@pytest.mark.asyncio
async def test_apdu_timeout_when_no_response():
    bridge = TBABridge()

    async def blackhole(_):
        return None  # never feeds a response back

    bridge.bind_sender(blackhole)
    from app.services.tba_bridge import TBAError
    with pytest.raises(TBAError):
        await bridge.send_apdu("card-001", b"\x00", timeout_ms=50)
