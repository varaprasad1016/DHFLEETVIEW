"""
Mock Tacho Bridge App for testing without the real (Rust) TBA or a reader.

`InMemoryMockTBA` pairs directly with a `TBABridge` by acting as its sender: the
bridge "sends" JSON to the mock, which computes an APDU response and feeds it
back via `bridge.handle_message`. This exercises the full request/response
correlation and card-status logic with no sockets at all.
"""

from __future__ import annotations

import json
from typing import Callable

from app.services.tba_bridge import TBABridge

# responder(card_id, apdu_bytes) -> (sw1_hex, sw2_hex, data_bytes)
Responder = Callable[[str, bytes], tuple[str, bytes]]


def default_responder(card_id: str, apdu: bytes) -> tuple[str, str, bytes]:
    """Echo the command data, always 90 00 (success)."""
    # data payload after the 5-byte header, if any
    payload = apdu[5:] if len(apdu) > 5 else b""
    return "90", "00", payload


class InMemoryMockTBA:
    def __init__(self, cards: list[dict], responder=default_responder):
        self.cards = cards          # e.g. [{"card_id": "card-001", "present": True, "busy": False}]
        self._responder = responder
        self.bridge: TBABridge | None = None
        self.received: list[dict] = []

    def attach(self, bridge: TBABridge) -> None:
        self.bridge = bridge
        bridge.bind_sender(self.receive)

    async def receive(self, raw: str) -> None:
        """Bridge -> mock. React to apdu_request; record session messages."""
        msg = json.loads(raw)
        self.received.append(msg)
        if msg.get("type") == "apdu_request":
            sw1, sw2, data = self._responder(msg["card_id"], bytes.fromhex(msg["apdu"]))
            assert self.bridge is not None
            await self.bridge.handle_message(json.dumps({
                "type": "apdu_response",
                "request_id": msg["request_id"],
                "card_id": msg["card_id"],
                "sw1": sw1,
                "sw2": sw2,
                "data": data.hex(),
            }))

    async def push_status(self) -> None:
        """Deliver a heartbeat/status snapshot to the bridge."""
        assert self.bridge is not None
        await self.bridge.handle_message(json.dumps({
            "type": "status", "tba_id": "mock-tba", "cards": self.cards,
        }))
