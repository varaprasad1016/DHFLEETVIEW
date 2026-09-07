"""
Card access manager.

One company card = one serial bottleneck: only one download may use a given card
at a time. Waiting requests are served in priority order (overdue before warning
before routine), then FIFO within a priority. Supports several cards (a card
hotel) in parallel — the serialisation is per card_id.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
from uuid import uuid4

from app.services.tba_bridge import TBABridge

logger = logging.getLogger(__name__)

# Lower value = more urgent (heap pops smallest first).
PRIORITY_OVERDUE = 0
PRIORITY_WARNING = 1
PRIORITY_ROUTINE = 2


class CardSession:
    """Exclusive hold on one card. Use as an async context manager."""

    def __init__(self, card_id: str, session_id: str, manager: "CardSessionManager"):
        self.card_id = card_id
        self.session_id = session_id
        self._manager = manager

    async def __aenter__(self) -> "CardSession":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._manager.release(self)


class CardSessionManager:
    def __init__(self, tba: TBABridge):
        self._tba = tba
        self._busy: set[str] = set()
        self._waiters: dict[str, list] = {}   # card_id -> heap of (priority, seq, future)
        self._seq = 0
        self._lock = asyncio.Lock()

    async def acquire(self, card_id: str, priority: int = PRIORITY_ROUTINE) -> CardSession:
        """Wait until the card is free (respecting priority), then hold it."""
        async with self._lock:
            if card_id not in self._busy:
                self._busy.add(card_id)
                return await self._open(card_id)
            self._seq += 1
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            heapq.heappush(self._waiters.setdefault(card_id, []), (priority, self._seq, fut))

        await fut  # resolved by release(); the card is already marked busy for us
        return await self._open(card_id)

    async def release(self, session: CardSession) -> None:
        """Release the card. If a request is waiting, hand it over directly."""
        async with self._lock:
            heap = self._waiters.get(session.card_id)
            if heap:
                _, _, fut = heapq.heappop(heap)
                if not heap:
                    self._waiters.pop(session.card_id, None)
                if not fut.done():
                    fut.set_result(None)  # card stays busy, ownership transfers
                    logger.debug("Card %s handed to next waiter", session.card_id)
                    return
            self._busy.discard(session.card_id)
        try:
            await self._tba.session_end(session.card_id, session.session_id)
        except Exception as exc:  # noqa: BLE001 - best-effort, card is already free
            logger.debug("session_end notify failed for %s: %s", session.card_id, exc)

    async def _open(self, card_id: str) -> CardSession:
        session = CardSession(card_id, str(uuid4()), self)
        try:
            await self._tba.session_start(card_id, session.session_id)
        except Exception as exc:  # noqa: BLE001 - notify is best-effort
            logger.debug("session_start notify failed for %s: %s", card_id, exc)
        return session

    def is_busy(self, card_id: str) -> bool:
        return card_id in self._busy
