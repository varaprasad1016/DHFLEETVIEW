"""Tacho Bridge endpoint: where the DH FleetView Tacho Bridge App connects.

The app (a fork of the MIT Tacho Bridge App, kept protocol-identical to upstream)
opens MQTT v5 connections to this server over TLS:

* one app connection per running app (client id ``TBA`` + 13 digits). It
  reports the app's settings and carries the traffic of any Lisle card rack on
  the PC's COM ports (``rack/<serial>/...``);
* one connection per company card in a reader (client id = company card number).
  The server drives company-card authentication on it:
  ``request/<id>/<sender>`` ``{"finish":false,"payload":"<apdu hex>"}`` ->
  ``response/<id>/<sender>`` ``{"payload":"<response hex>"}``.

Every connection signs in with a bridge sign-in created on the Tachograph page;
the sign-in decides which company the app, its cards and its racks belong to.
The full wire contract is upstream's ``communication_protocol.md``.

The card rack's own serial protocol is built by the server. It is not public, so
racks are tracked (linked, cards reported) but not driven until it is added.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import SessionLocal
from app.models.bridge import BridgeCredential, BridgeNode
from app.services import mqtt_codec as mq

logger = logging.getLogger("tacho.bridge")
if not logger.handlers:
    # uvicorn only configures its own loggers; connection events belong in the API log too.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s BRIDGE %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

APP_ID = re.compile(r"^TBA\d{13}$")
CARD_ID = re.compile(r"^[0-9A-Za-z]{8,32}$")
RACK_TOPIC = re.compile(r"^rack/([0-9A-Z]{1,40})/(.+)$")
SW_TECHNICAL_PROBLEM = "6F00"
# SELECT the tachograph application by name (DF Tachograph, AID FF 54 41 43 48 4F).
SELECT_TACHOGRAPH = bytes.fromhex("00A4040C06FF544143484F")


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ sign-ins
def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def _check_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_password(password, salt), stored)


def new_sign_in() -> tuple[str, str, str]:
    """(username, password, password_hash) for a new bridge sign-in."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    username = "dhfv-" + "".join(secrets.choice(alphabet) for _ in range(10))
    password = secrets.token_urlsafe(18)
    return username, password, _hash_password(password)


# ------------------------------------------------------------------ connections
@dataclass
class Connection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    client_id: str
    kind: str                       # app | card | rack (legacy per-rack connection)
    owner_user_id: int
    credential_id: object
    remote: str
    keep_alive: int
    max_packet: int = mq.MAX_PACKET
    connected_at: datetime = field(default_factory=now)
    info: dict = field(default_factory=dict)
    racks: dict = field(default_factory=dict)          # app: rack id -> state
    rack_link: dict | None = None                      # card: rack slot binding
    request_counter: int = 0
    packet_counter: int = 0
    pending: dict = field(default_factory=dict)        # reply topic -> Future
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False

    @property
    def key(self) -> tuple[int, str]:
        return (self.owner_user_id, self.client_id)

    def next_request_id(self) -> int:
        self.request_counter += 1
        return self.request_counter

    async def send(self, data: bytes) -> None:
        if self.closed:
            raise BridgeError("offline", "The Tacho Bridge connection has closed.")
        if len(data) > self.max_packet:
            raise BridgeError("too_large", "Message is larger than the app accepts.")
        async with self.write_lock:
            self.writer.write(data)
            await self.writer.drain()

    async def publish(self, topic: str, payload: dict | bytes, qos: int = 1) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        self.packet_counter = self.packet_counter % 65535 + 1
        await self.send(mq.publish(topic, body, qos, self.packet_counter))

    def close(self) -> None:
        self.closed = True
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(BridgeError("offline", "The Tacho Bridge connection closed during the exchange."))
        self.pending.clear()
        with contextlib.suppress(Exception):
            self.writer.close()


class CardSession:
    """One authentication session on a company card: ATR, APDUs, finish."""

    def __init__(self, server: "BridgeServer", owner_user_id: int, card_number: str, sender: str):
        self.server, self.owner_user_id, self.card_number, self.sender = server, owner_user_id, card_number, sender
        self.started = False

    def _conn(self) -> Connection:
        conn = self.server.card_connection(self.owner_user_id, self.card_number)
        if conn is None:
            raise BridgeError("card_offline", "The company card is not connected to the Tacho Bridge.")
        if conn.rack_link:
            raise BridgeError("rack_card", "This card is in a card rack. Rack cards need the rack protocol on the server, which is not available yet.")
        return conn

    async def start(self, protocol: str | None = None) -> dict:
        body: dict = {"finish": False, "payload": ""}
        if protocol in ("T0", "T1"):
            body["protocol"] = protocol
        reply = await self.server.request(self._conn(), body, self.sender)
        self.started = True
        return {"atr": (reply.get("payload") or "").upper(), "protocol": reply.get("protocol")}

    async def apdu(self, command: bytes) -> bytes:
        reply = await self.server.request(self._conn(), {"finish": False, "payload": command.hex().upper()}, self.sender)
        try:
            return bytes.fromhex(reply.get("payload") or SW_TECHNICAL_PROBLEM)
        except ValueError:
            return bytes.fromhex(SW_TECHNICAL_PROBLEM)

    async def finish(self) -> None:
        if not self.started:
            return
        self.started = False
        with contextlib.suppress(BridgeError):
            await self.server.request(self._conn(), {"finish": True}, self.sender)


class BridgeServer:
    REQUEST_TIMEOUT = 15.0
    FAILED_AUTH_LIMIT = 10
    FAILED_AUTH_WINDOW = 600

    def __init__(self):
        self.connections: dict[tuple[int, str], Connection] = {}
        self._servers: list[asyncio.base_events.Server] = []
        self._card_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._auth_cache: dict[str, tuple[float, str, object, int]] = {}
        self._failed: dict[str, list[float]] = {}
        self._tls: ssl.SSLContext | None = None
        self._tls_mtime = 0.0
        self._tasks: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self._mark_all_offline()
        host = settings.bridge_host
        if settings.bridge_tls_port:
            self._tls = self._load_tls()
            if self._tls is None:
                logger.error("Tacho Bridge TLS certificate not found; secure port %s not started", settings.bridge_tls_port)
            else:
                self._servers.append(await asyncio.start_server(self._client, host, settings.bridge_tls_port, ssl=self._tls))
                logger.info("Tacho Bridge endpoint listening on %s:%s (TLS)", host, settings.bridge_tls_port)
                self._spawn(self._reload_tls_loop())
        if settings.bridge_plain_port:
            self._servers.append(await asyncio.start_server(self._client, settings.bridge_plain_host, settings.bridge_plain_port))
            logger.info("Tacho Bridge endpoint listening on %s:%s (plain)", settings.bridge_plain_host, settings.bridge_plain_port)

    async def stop(self) -> None:
        for server in self._servers:
            server.close()
        for conn in list(self.connections.values()):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(conn.send(mq.disconnect(mq.SUCCESS)), 1)
            conn.close()
        for task in list(self._tasks):
            task.cancel()
        self.connections.clear()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _load_tls(self) -> ssl.SSLContext | None:
        cert, key = settings.bridge_tls_cert, settings.bridge_tls_key
        if not (os.path.isfile(cert) and os.path.isfile(key)):
            return None
        ctx = self._tls or ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        self._tls_mtime = os.path.getmtime(cert)
        return ctx

    async def _reload_tls_loop(self) -> None:
        # The certificate is renewed in place; new handshakes pick up the new one.
        while True:
            await asyncio.sleep(3600)
            with contextlib.suppress(Exception):
                if os.path.getmtime(settings.bridge_tls_cert) != self._tls_mtime:
                    self._load_tls()
                    logger.info("Tacho Bridge TLS certificate reloaded")

    # ---------------------------------------------------------------- lookups
    def card_connection(self, owner_user_id: int, card_number: str) -> Connection | None:
        conn = self.connections.get((owner_user_id, card_number))
        return conn if conn and conn.kind == "card" and not conn.closed else None

    def connections_for(self, owner_user_id: int | None) -> list[Connection]:
        return [c for c in self.connections.values() if owner_user_id is None or c.owner_user_id == owner_user_id]

    @contextlib.asynccontextmanager
    async def card_session(self, owner_user_id: int, card_number: str, sender: str = "0", wait: float = 30.0):
        """Exclusive authentication session on one company card."""
        lock = self._card_locks.setdefault((owner_user_id, card_number), asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), wait)
        except asyncio.TimeoutError as exc:
            raise BridgeError("card_busy", "The company card is busy with another download. Try again shortly.") from exc
        session = CardSession(self, owner_user_id, card_number, sender)
        try:
            yield session
        finally:
            try:
                await session.finish()
            finally:
                lock.release()

    async def request(self, conn: Connection, body: dict, sender: str = "0", timeout: float | None = None) -> dict:
        """Server command on a card connection; resends the same request id once on a slow reply."""
        request_id = conn.next_request_id()
        topic = f"request/{request_id}/{sender}"
        reply_topic = f"response/{request_id}/{sender}"
        return await self._exchange(conn, topic, reply_topic, body, timeout)

    async def app_command(self, conn: Connection, name: str, timeout: float | None = None, **fields) -> dict:
        request_id = conn.next_request_id()
        reply_kind = {"get_settings": "settings", "debug_log": "debug", "set_server": "server",
                      "set_credentials": "credentials"}.get(name, name)
        return await self._exchange(conn, f"request/{request_id}/0", f"{reply_kind}/{request_id}/done",
                                    {"name": name, **fields}, timeout)

    async def _exchange(self, conn: Connection, topic: str, reply_topic: str, body: dict, timeout: float | None) -> dict:
        timeout = timeout or self.REQUEST_TIMEOUT
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.pending[reply_topic] = fut
        try:
            for attempt in range(2):
                await conn.publish(topic, body)
                try:
                    raw = await asyncio.wait_for(asyncio.shield(fut), timeout / 2 if attempt == 0 else timeout / 2)
                    break
                except asyncio.TimeoutError:
                    if attempt == 1:
                        raise BridgeError("timeout", "The Tacho Bridge App did not answer in time.")
                    logger.info("bridge %s: no reply on %s yet, re-sending", conn.client_id, topic)
            try:
                reply = json.loads(raw.decode() or "{}")
            except (ValueError, UnicodeDecodeError) as exc:
                raise BridgeError("bad_reply", "The Tacho Bridge App sent an unreadable reply.") from exc
            if isinstance(reply, dict) and reply.get("error"):
                raise BridgeError("app_error", str(reply["error"]))
            return reply if isinstance(reply, dict) else {}
        finally:
            conn.pending.pop(reply_topic, None)

    # ---------------------------------------------------------------- auth
    def _rate_limited(self, ip: str) -> bool:
        cutoff = time.monotonic() - self.FAILED_AUTH_WINDOW
        recent = [t for t in self._failed.get(ip, []) if t > cutoff]
        self._failed[ip] = recent
        return len(recent) >= self.FAILED_AUTH_LIMIT

    async def authenticate(self, username: str | None, password: bytes | None, ip: str) -> tuple[object, int] | None:
        if not username or password is None or self._rate_limited(ip):
            return None
        pw = password.decode("utf-8", "replace")
        fingerprint = hashlib.sha256(f"{username}\0{pw}".encode()).hexdigest()
        hit = self._auth_cache.get(username)
        if hit and hit[0] > time.monotonic() and hmac.compare_digest(hit[1], fingerprint):
            return hit[2], hit[3]
        async with SessionLocal() as session:
            cred = (await session.execute(select(BridgeCredential).where(
                BridgeCredential.username == username, BridgeCredential.revoked_at.is_(None)))).scalar_one_or_none()
            ok = cred is not None and await asyncio.to_thread(_check_password, pw, cred.password_hash)
            if not ok:
                self._failed.setdefault(ip, []).append(time.monotonic())
                return None
            cred.last_used_at = now()
            await session.commit()
            self._auth_cache[username] = (time.monotonic() + 600, fingerprint, cred.id, cred.owner_user_id)
            return cred.id, cred.owner_user_id

    async def revoke(self, credential_id) -> int:
        """Forget a revoked sign-in and drop everything connected with it."""
        for name, hit in list(self._auth_cache.items()):
            if hit[2] == credential_id:
                self._auth_cache.pop(name, None)
        dropped = 0
        for conn in list(self.connections.values()):
            if conn.credential_id == credential_id:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(conn.send(mq.disconnect(mq.NOT_AUTHORIZED, "sign-in revoked")), 2)
                conn.close()
                dropped += 1
        return dropped

    # ---------------------------------------------------------------- persistence
    async def _mark_all_offline(self) -> None:
        with contextlib.suppress(Exception):
            async with SessionLocal() as session:
                await session.execute(update(BridgeNode).where(BridgeNode.online.is_(True)).values(online=False))
                await session.commit()

    async def _save_node(self, owner: int, kind: str, key: str, online: bool, info: dict | None = None,
                         credential_id=None, remote: str | None = None, replace_info: bool = False) -> None:
        try:
            async with SessionLocal() as session:
                values = {"owner_user_id": owner, "kind": kind, "key": key, "online": online, "last_seen": now()}
                if credential_id is not None:
                    values["credential_id"] = credential_id
                if remote is not None:
                    values["remote_addr"] = remote
                stmt = insert(BridgeNode).values(**values, info=info or {})
                updates = {k: stmt.excluded[k] for k in values if k not in ("owner_user_id", "kind", "key")}
                if info is not None:
                    updates["info"] = stmt.excluded.info if replace_info else BridgeNode.info.op("||")(stmt.excluded.info)
                await session.execute(stmt.on_conflict_do_update(constraint="uq_bridge_nodes_owner_kind_key", set_=updates))
                await session.commit()
        except Exception:  # noqa: BLE001 - the bridge keeps working without the status record
            logger.exception("bridge: could not save %s %s", kind, key)

    # ---------------------------------------------------------------- connection handling
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername") or ("?", 0)
        ip = str(peer[0])
        conn: Connection | None = None
        # Logged so a bridge that never gets in can be told apart from one that
        # never reaches the server at all.
        logger.info("bridge: connection from %s", ip)
        try:
            first = await asyncio.wait_for(mq.read_packet(reader, 64 * 1024), 20)
            if first.type != mq.CONNECT:
                logger.info("bridge: %s sent packet type %s before signing in", ip, first.type)
                return
            connect = mq.decode_connect(first)
            if connect.protocol_version != 5:
                logger.info("bridge: %s speaks MQTT v%s, not v5", ip, connect.protocol_version)
                writer.write(mq.connack(mq.UNSUPPORTED_PROTOCOL_VERSION))
                await writer.drain()
                return
            client_id = connect.client_id
            if APP_ID.match(client_id):
                kind = "app"
            elif client_id.startswith("RACK"):
                kind = "rack"
            elif CARD_ID.match(client_id):
                kind = "card"
            else:
                logger.info("bridge: %s used an unusable client id %r", ip, client_id[:40])
                writer.write(mq.connack(mq.CLIENT_ID_NOT_VALID))
                await writer.drain()
                return
            auth = await self.authenticate(connect.username, connect.password, ip)
            if auth is None:
                logger.info("bridge: sign-in refused for %s from %s", client_id, ip)
                writer.write(mq.connack(mq.NOT_AUTHORIZED, props={mq.PROP_REASON_STRING: "credentials not set or invalid"}))
                await writer.drain()
                return
            credential_id, owner = auth
            conn = Connection(reader, writer, client_id, kind, owner, credential_id, ip, connect.keep_alive,
                              max_packet=connect.properties.get(mq.PROP_MAX_PACKET_SIZE, mq.MAX_PACKET))
            previous = self.connections.get(conn.key)
            if previous:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(previous.send(mq.disconnect(mq.SESSION_TAKEN_OVER, "another connection took over")), 1)
                previous.close()
            self.connections[conn.key] = conn
            await conn.send(mq.connack(mq.SUCCESS, props={mq.PROP_RECEIVE_MAXIMUM: 100}))
            logger.info("bridge: %s %s connected for account %s from %s", kind, client_id, owner, ip)
            if kind in ("app", "card"):
                await self._save_node(owner, kind, client_id, True, info={"connected_at": conn.connected_at.isoformat()},
                                      credential_id=credential_id, remote=ip)
            await self._serve(conn)
        except ssl.SSLError as exc:
            # A client that can't complete TLS (wrong port, old TLS, certificate
            # not trusted) never reaches the sign-in, so say so plainly.
            logger.info("bridge: TLS failed for %s: %s", ip, exc)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, OSError) as exc:
            if conn is None:
                logger.info("bridge: %s disconnected before signing in (%s)", ip, type(exc).__name__)
        except mq.MalformedPacket as exc:
            logger.info("bridge: malformed packet from %s: %s", ip, exc)
            with contextlib.suppress(Exception):
                writer.write(mq.disconnect(mq.MALFORMED_PACKET))
        except Exception:  # noqa: BLE001
            logger.exception("bridge: connection error from %s", ip)
        finally:
            if conn is not None:
                conn.close()
                if self.connections.get(conn.key) is conn:
                    self.connections.pop(conn.key, None)
                    logger.info("bridge: %s %s disconnected", conn.kind, conn.client_id)
                    if conn.kind in ("app", "card"):
                        await self._save_node(conn.owner_user_id, conn.kind, conn.client_id, False)
                    for rack_id in conn.racks:
                        await self._save_node(conn.owner_user_id, "rack", rack_id, False, info={"state": "down"})
            else:
                with contextlib.suppress(Exception):
                    writer.close()

    async def _serve(self, conn: Connection) -> None:
        idle = conn.keep_alive * 1.5 if conn.keep_alive else None
        while not conn.closed:
            packet = await asyncio.wait_for(mq.read_packet(conn.reader), idle) if idle else await mq.read_packet(conn.reader)
            if packet.type == mq.PUBLISH:
                pub = mq.decode_publish(packet)
                if pub.qos == 1 and pub.packet_id is not None:
                    await conn.send(mq.puback(pub.packet_id))
                elif pub.qos == 2:
                    await conn.send(mq.disconnect(mq.PROTOCOL_ERROR, "QoS 2 is not supported"))
                    return
                await self._on_publish(conn, pub)
            elif packet.type == mq.PINGREQ:
                await conn.send(mq.pingresp())
            elif packet.type == mq.SUBSCRIBE:
                packet_id, topics = mq.decode_subscribe(packet)
                await conn.send(mq.suback(packet_id, len(topics)))
            elif packet.type == mq.UNSUBSCRIBE:
                packet_id, topics = mq.decode_unsubscribe(packet)
                await conn.send(mq.unsuback(packet_id, len(topics)))
            elif packet.type == mq.DISCONNECT:
                return
            elif packet.type in (mq.PUBACK, mq.PUBREC, mq.PUBCOMP):
                continue
            else:
                await conn.send(mq.disconnect(mq.PROTOCOL_ERROR))
                return

    async def _on_publish(self, conn: Connection, pub: mq.Publish) -> None:
        topic = pub.topic
        fut = conn.pending.get(topic)
        if fut is not None:
            if not fut.done():
                fut.set_result(pub.payload)
            return
        if conn.kind == "card":
            if topic == "rack":
                with contextlib.suppress(ValueError, UnicodeDecodeError):
                    conn.rack_link = json.loads(pub.payload.decode())
                    await self._save_node(conn.owner_user_id, "card", conn.client_id, True,
                                          info={"via": "rack", "rack": (conn.rack_link or {}).get("rack"),
                                                "slot": (conn.rack_link or {}).get("slot")})
                return
            logger.debug("bridge card %s: unexpected topic %s", conn.client_id, topic)
            return
        if conn.kind != "app":
            return
        if topic == "settings":
            with contextlib.suppress(ValueError, UnicodeDecodeError):
                report = json.loads(pub.payload.decode())
                if isinstance(report, dict):
                    report.get("authentication", {}).pop("password", None)
                    conn.info = report
                    await self._save_node(conn.owner_user_id, "app", conn.client_id, True, info={"settings": report})
            return
        match = RACK_TOPIC.match(topic)
        if match:
            rack_id, tail = match.groups()
            if tail == "link":
                with contextlib.suppress(ValueError, UnicodeDecodeError):
                    link = json.loads(pub.payload.decode())
                    state = link.get("state") if isinstance(link, dict) else None
                    if state in ("up", "down"):
                        conn.racks[rack_id] = {"state": state, "cards": link.get("cards") or [], "at": now().isoformat()}
                        await self._save_node(conn.owner_user_id, "rack", rack_id, state == "up", replace_info=True,
                                              info={"state": state, "app": conn.client_id,
                                                    "cards": link.get("cards") or [],
                                                    "capabilities": {k: v for k, v in link.items() if k not in ("state", "cards")}},
                                              credential_id=conn.credential_id, remote=conn.remote)
                        logger.info("bridge: rack %s link %s on app %s", rack_id, state, conn.client_id)
            return
        logger.debug("bridge app %s: unhandled topic %s", conn.client_id, topic)

    # ---------------------------------------------------------------- websocket
    async def serve_websocket(self, websocket) -> None:
        """The same protocol over a WebSocket, so the app can reach us on 443.

        Hosting firewalls (and depot networks) often allow nothing but 80 and
        443, which leaves the plain MQTT port unreachable. MQTT over WebSocket
        rides the site's own HTTPS port through Apache, so the app connects
        wherever a browser would.
        """
        client = getattr(websocket, "client", None)
        peer = (getattr(client, "host", "?"), getattr(client, "port", 0))
        reader = asyncio.StreamReader(limit=mq.MAX_PACKET)
        writer = _WebSocketWriter(websocket, peer)

        async def pump() -> None:
            try:
                while True:
                    message = await websocket.receive_bytes()
                    reader.feed_data(message)
            except Exception:  # noqa: BLE001 - any end of the socket ends the stream
                reader.feed_eof()

        pumping = asyncio.create_task(pump())
        try:
            await self._client(reader, writer)
        finally:
            pumping.cancel()
            with contextlib.suppress(Exception):
                await websocket.close()


class _WebSocketWriter:
    """The writer half of a WebSocket, shaped like an asyncio stream writer."""

    def __init__(self, websocket, peer):
        self._websocket = websocket
        self._peer = peer
        self._buffer = bytearray()
        self._closed = False

    def write(self, data: bytes) -> None:
        self._buffer += data

    async def drain(self) -> None:
        if self._buffer and not self._closed:
            payload, self._buffer = bytes(self._buffer), bytearray()
            await self._websocket.send_bytes(payload)

    def close(self) -> None:
        self._closed = True

    def get_extra_info(self, name: str, default=None):
        return self._peer if name == "peername" else default


bridge = BridgeServer()
