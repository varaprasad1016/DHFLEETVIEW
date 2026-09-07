"""
Connection to the forked Tacho Bridge App.

Transport-abstracted on purpose: all message handling (request/response
correlation, card-status tracking) is decoupled from the actual WebSocket, so it
is fully testable in-process against a mock. The real WebSocket loop (`run`)
imports `websockets` lazily and is a thin wrapper over `handle_message`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional
from uuid import uuid4

from app.services.apdu import APDUResponse

logger = logging.getLogger(__name__)

Sender = Callable[[str], Awaitable[None]]


class TBAError(Exception):
    pass


@dataclass
class CardStatus:
    card_id: str
    present: bool
    busy: bool
    atr: Optional[str] = None


class TBABridge:
    def __init__(self, ws_url: str = "ws://localhost:8765"):
        self._url = ws_url
        self._pending: dict[str, asyncio.Future] = {}
        self._cards: dict[str, CardStatus] = {}
        self._send: Optional[Sender] = None
        self._connected: bool = False

    # --- transport binding (a real WS or a mock supplies the sender) ---
    def bind_sender(self, sender: Sender) -> None:
        self._send = sender
        self._connected = True

    def unbind(self) -> None:
        self._send = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def available_cards(self) -> list[str]:
        return [cid for cid, s in self._cards.items() if s.present and not s.busy]

    def card_status(self, card_id: str) -> Optional[CardStatus]:
        return self._cards.get(card_id)

    # --- outbound ---
    async def send_apdu(self, card_id: str, apdu: bytes, timeout_ms: int = 5000) -> APDUResponse:
        if self._send is None:
            raise TBAError("TBA not connected")
        request_id = str(uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        await self._send(json.dumps({
            "type": "apdu_request",
            "request_id": request_id,
            "card_id": card_id,
            "apdu": apdu.hex(),
            "timeout_ms": timeout_ms,
        }))
        try:
            return await asyncio.wait_for(fut, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError as exc:
            raise TBAError(f"APDU timeout for card {card_id}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def session_start(self, card_id: str, session_id: str) -> None:
        await self._require_send(json.dumps(
            {"type": "session_start", "session_id": session_id, "card_id": card_id}))

    async def session_end(self, card_id: str, session_id: str) -> None:
        await self._require_send(json.dumps(
            {"type": "session_end", "session_id": session_id, "card_id": card_id}))

    async def _require_send(self, payload: str) -> None:
        if self._send is None:
            raise TBAError("TBA not connected")
        await self._send(payload)

    # --- inbound (fed by the WS loop or a mock) ---
    async def handle_message(self, raw: str) -> None:
        msg = json.loads(raw)
        mtype = msg.get("type")
        if mtype == "apdu_response":
            fut = self._pending.get(msg["request_id"])
            if fut and not fut.done():
                data = bytes.fromhex(msg.get("data") or "")
                fut.set_result(APDUResponse(msg["sw1"], msg["sw2"], data))
        elif mtype == "status":
            self._cards = {
                c["card_id"]: CardStatus(
                    card_id=c["card_id"],
                    present=bool(c.get("present", False)),
                    busy=bool(c.get("busy", False)),
                    atr=c.get("atr"),
                )
                for c in msg.get("cards", [])
            }
        else:
            logger.debug("Ignoring TBA message type=%s", mtype)

    # --- real transport (thin wrapper; websockets imported lazily) ---
    async def run(self) -> None:
        import websockets  # local import so the module loads without the dep

        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self._url) as ws:
                    self.bind_sender(ws.send)
                    logger.info("Connected to TBA at %s", self._url)
                    backoff = 1.0
                    async for raw in ws:
                        await self.handle_message(raw)
            except Exception as exc:  # noqa: BLE001 - reconnect on any error
                logger.warning("TBA connection lost: %s", exc)
            finally:
                self.unbind()
            await asyncio.sleep(min(backoff, 30.0))
            backoff *= 2
