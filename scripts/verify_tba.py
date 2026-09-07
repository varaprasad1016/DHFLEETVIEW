"""
Phase 2 end-to-end check with no sockets/reader: wire a TBABridge to the
in-memory mock TBA, verify APDU relay + card status, then verify the
CardSessionManager serialises a card and serves waiters in priority order.

Run: python scripts/verify_tba.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.apdu import APDUSequencer  # noqa: E402
from app.services.card_session import (  # noqa: E402
    PRIORITY_OVERDUE,
    PRIORITY_ROUTINE,
    PRIORITY_WARNING,
    CardSessionManager,
)
from app.services.tba_bridge import TBABridge  # noqa: E402
from tests.test_services.mock_tba import InMemoryMockTBA  # noqa: E402

results: list[tuple[str, bool]] = []


def check(label: str, cond: bool) -> None:
    results.append((label, bool(cond)))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


async def main() -> int:
    bridge = TBABridge()
    mock = InMemoryMockTBA(cards=[
        {"card_id": "card-001", "present": True, "busy": False, "atr": "3B9F..."},
        {"card_id": "card-002", "present": True, "busy": True, "atr": "3B8F..."},
    ])
    mock.attach(bridge)

    # --- card status / heartbeat ---
    await mock.push_status()
    check("bridge connected", bridge.connected)
    check("available cards excludes busy one", bridge.available_cards == ["card-001"])
    check("card-002 reported busy", bridge.card_status("card-002").busy is True)

    # --- APDU relay round-trip ---
    apdu = APDUSequencer.select_applet(bytes.fromhex("3F0001010000"))
    resp = await bridge.send_apdu("card-001", apdu)
    check("APDU response ok (9000)", resp.ok)
    check("APDU echoes command payload", resp.data == bytes.fromhex("3F0001010000"))

    # --- card session priority ordering ---
    mgr = CardSessionManager(bridge)
    held = await mgr.acquire("card-001", PRIORITY_ROUTINE)  # main holds it
    order: list[int] = []

    async def waiter(priority: int):
        session = await mgr.acquire("card-001", priority)
        order.append(priority)
        await mgr.release(session)

    tasks = [
        asyncio.create_task(waiter(PRIORITY_ROUTINE)),
        asyncio.create_task(waiter(PRIORITY_OVERDUE)),
        asyncio.create_task(waiter(PRIORITY_WARNING)),
    ]
    await asyncio.sleep(0.05)          # let all three queue behind the held card
    check("card is serialised (busy)", mgr.is_busy("card-001"))
    await mgr.release(held)            # triggers the priority-ordered handoff
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    check(
        "waiters served overdue -> warning -> routine",
        order == [PRIORITY_OVERDUE, PRIORITY_WARNING, PRIORITY_ROUTINE],
    )
    check("card free after all released", not mgr.is_busy("card-001"))

    ok = all(c for _, c in results)
    print(f"\nRESULT: {'ALL PASS' if ok else 'FAILURES'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
