"""Tacho Bridge App: installer downloads, sign-ins, and the apps, cards and racks online.

Public (no sign-in; the installer holds no secrets):
GET    /bridge/download                     newest installer
GET    /bridge/latest.json                  updater manifest (stable)
GET    /bridge/latest-beta.json             updater manifest (pre-release channel)
GET    /bridge/files/{version}/{name}       installer / signature referenced by the manifests

Office (licence + office user + "tacho" module; each company sees its own):
GET    /api/bridge/overview                 release, sign-ins, apps, cards, racks
POST   /api/bridge/sign-ins                 create a sign-in (the password is shown once)
DELETE /api/bridge/sign-ins/{id}            revoke: the apps using it are disconnected
POST   /api/bridge/cards/{card}/test        check a company card answers through the bridge
DELETE /api/bridge/nodes/{id}               forget an app, card or rack that is offline
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.config import settings
from app.database import get_session
from app.models.bridge import BridgeCredential, BridgeNode
from app.services import modules
from app.services.auth import Principal
from app.services.bridge_server import SELECT_TACHOGRAPH, BridgeError, bridge, new_sign_in, now

public_router = APIRouter(prefix="/bridge", tags=["bridge"])
router = APIRouter(prefix="/api/bridge", tags=["bridge"],
                   dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("tacho"))])

SAFE_NAME = re.compile(r"^[A-Za-z0-9._ -]+$")
SERVER_ADDRESS = "dhfleetview.co.uk:8883"


# ------------------------------------------------------------------ releases
def _release_dir() -> Path:
    return Path(settings.bridge_release_dir)


def _manifest(name: str) -> dict | None:
    path = _release_dir() / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _installer(manifest: dict | None) -> Path | None:
    if not manifest:
        return None
    version = str(manifest.get("version", ""))
    name = manifest.get("installer")
    if not (SAFE_NAME.match(version) and name and SAFE_NAME.match(name)):
        return None
    path = _release_dir() / version / name
    return path if path.is_file() else None


@public_router.get("/latest.json")
async def latest_manifest():
    manifest = _manifest("latest.json")
    if not manifest:
        return JSONResponse({"error": "no release published"}, status_code=404)
    return JSONResponse({k: v for k, v in manifest.items() if k != "installer"}, headers={"Cache-Control": "no-cache"})


@public_router.get("/latest-beta.json")
async def latest_beta_manifest():
    manifest = _manifest("latest-beta.json") or _manifest("latest.json")
    if not manifest:
        return JSONResponse({"error": "no release published"}, status_code=404)
    return JSONResponse({k: v for k, v in manifest.items() if k != "installer"}, headers={"Cache-Control": "no-cache"})


@public_router.get("/download")
async def download_installer():
    path = _installer(_manifest("latest.json"))
    if path is None:
        raise HTTPException(status_code=404, detail="The Tacho Bridge App installer hasn't been published yet.")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name,
                        headers={"Cache-Control": "no-cache"})


@public_router.get("/files/{version}/{name}")
async def release_file(version: str, name: str):
    if not (SAFE_NAME.match(version) and SAFE_NAME.match(name)) or ".." in version or ".." in name:
        raise HTTPException(status_code=404)
    path = _release_dir() / version / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/octet-stream", filename=name)


# ------------------------------------------------------------------ office
def _owner_filter(principal: Principal) -> int | None:
    """None = every company (super administrator)."""
    return None if modules.is_super_admin(principal) else principal.user_id


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/overview")
async def overview(principal: Principal = Depends(require_manager), session: AsyncSession = Depends(get_session)):
    owner = _owner_filter(principal)
    creds_q = select(BridgeCredential).order_by(BridgeCredential.created_at.desc())
    nodes_q = select(BridgeNode).order_by(BridgeNode.kind, BridgeNode.key)
    if owner is not None:
        creds_q = creds_q.where(BridgeCredential.owner_user_id == owner)
        nodes_q = nodes_q.where(BridgeNode.owner_user_id == owner)
    creds = (await session.execute(creds_q)).scalars().all()
    nodes = (await session.execute(nodes_q)).scalars().all()
    owner_names = {c.owner_user_id: c.owner_name for c in creds if c.owner_name}
    live = {(c.owner_user_id, c.client_id): c for c in bridge.connections_for(owner)}

    def node_view(n: BridgeNode) -> dict:
        info = n.info or {}
        conn = live.get((n.owner_user_id, n.key))
        online = conn is not None and not conn.closed if n.kind in ("app", "card") else bool(n.online)
        view = {"id": str(n.id), "kind": n.kind, "key": n.key, "online": online, "last_seen": _iso(n.last_seen),
                "first_seen": _iso(n.first_seen), "company": owner_names.get(n.owner_user_id) if owner is None else None}
        if n.kind == "app":
            report = info.get("settings") or {}
            app = report.get("app_info") or {}
            view.update(version=app.get("version"), os=" ".join(filter(None, [app.get("os"), app.get("os_release")])) or None,
                        server=(report.get("server") or {}).get("host"))
        elif n.kind == "card":
            rack_link = conn.rack_link if conn else None
            view.update(via="rack" if (rack_link or info.get("via") == "rack") else "reader",
                        rack=(rack_link or {}).get("rack") or info.get("rack"),
                        slot=(rack_link or {}).get("slot") or info.get("slot"),
                        atr=info.get("atr"), last_test=info.get("last_test"))
        elif n.kind == "rack":
            view.update(state=info.get("state"), app=info.get("app"), cards=len(info.get("cards") or []))
        return view

    release = _manifest("latest.json")
    return {
        "server": SERVER_ADDRESS,
        "release": {"version": release.get("version"), "pub_date": release.get("pub_date"),
                    "download": "/tacho/bridge/download"} if _installer(release) else None,
        "sign_ins": [{"id": str(c.id), "label": c.label, "username": c.username, "company": c.owner_name if owner is None else None,
                      "created_at": _iso(c.created_at), "created_by": c.created_by, "last_used_at": _iso(c.last_used_at),
                      "revoked": c.revoked_at is not None} for c in creds],
        "apps": [node_view(n) for n in nodes if n.kind == "app"],
        "cards": [node_view(n) for n in nodes if n.kind == "card"],
        "racks": [node_view(n) for n in nodes if n.kind == "rack"],
    }


@router.post("/sign-ins", status_code=201)
async def create_sign_in(body: dict = Body(default={}), principal: Principal = Depends(require_manager),
                         session: AsyncSession = Depends(get_session)):
    if principal.user_id is None:
        raise HTTPException(status_code=400, detail="Sign in with a DH FleetView account to create a bridge sign-in.")
    label = (str(body.get("label") or "").strip() or "Tacho Bridge")[:80]
    active = (await session.execute(select(BridgeCredential).where(
        BridgeCredential.owner_user_id == principal.user_id, BridgeCredential.revoked_at.is_(None)))).scalars().all()
    if len(active) >= 20:
        raise HTTPException(status_code=400, detail="This account already has 20 active bridge sign-ins. Revoke unused ones first.")
    username, password, password_hash = new_sign_in()
    cred = BridgeCredential(owner_user_id=principal.user_id, owner_name=principal.name, label=label, username=username,
                            password_hash=password_hash, created_by=principal.email or principal.name)
    session.add(cred)
    await session.commit()
    return {"id": str(cred.id), "label": label, "username": username, "password": password, "server": SERVER_ADDRESS}


async def _own_credential(session: AsyncSession, principal: Principal, credential_id: str) -> BridgeCredential:
    try:
        cid = uuid.UUID(credential_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Sign-in not found.") from exc
    cred = await session.get(BridgeCredential, cid)
    owner = _owner_filter(principal)
    if cred is None or (owner is not None and cred.owner_user_id != owner):
        raise HTTPException(status_code=404, detail="Sign-in not found.")
    return cred


@router.delete("/sign-ins/{credential_id}")
async def revoke_sign_in(credential_id: str, principal: Principal = Depends(require_manager),
                         session: AsyncSession = Depends(get_session)):
    cred = await _own_credential(session, principal, credential_id)
    if cred.revoked_at is None:
        cred.revoked_at = now()
        await session.commit()
    dropped = await bridge.revoke(cred.id)
    return {"revoked": True, "disconnected": dropped}


@router.post("/cards/{card_number}/test")
async def test_card(card_number: str, owner_user_id: int | None = None, principal: Principal = Depends(require_manager),
                    session: AsyncSession = Depends(get_session)):
    owner = _owner_filter(principal)
    if owner is None:
        owner = owner_user_id
    if owner is None:
        matches = [c for c in bridge.connections.values() if c.kind == "card" and c.client_id == card_number]
        owner = matches[0].owner_user_id if len(matches) == 1 else None
    if owner is None or bridge.card_connection(owner, card_number) is None:
        raise HTTPException(status_code=409, detail="That company card isn't connected to a Tacho Bridge right now.")
    result: dict = {"at": now().isoformat()}
    try:
        async with bridge.card_session(owner, card_number, wait=5) as card:
            started = await card.start()
            result["atr"] = started["atr"]
            result["protocol"] = started.get("protocol")
            reply = await card.apdu(SELECT_TACHOGRAPH)
            status = reply[-2:].hex().upper() if len(reply) >= 2 else ""
            result["select_status"] = status
            result["ok"] = bool(result["atr"]) and status == "9000"
            result["message"] = ("The card answered and its tachograph application is ready." if result["ok"] else
                                 f"The card answered but the tachograph application check returned {status or 'nothing'}.")
    except BridgeError as exc:
        result.update(ok=False, error=exc.code, message=exc.message)
    node = (await session.execute(select(BridgeNode).where(
        BridgeNode.owner_user_id == owner, BridgeNode.kind == "card", BridgeNode.key == card_number))).scalar_one_or_none()
    if node is not None:
        info = dict(node.info or {})
        info["last_test"] = result
        if result.get("atr"):
            info["atr"] = result["atr"]
        node.info = info
        await session.commit()
    return result


@router.delete("/nodes/{node_id}")
async def forget_node(node_id: str, principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)):
    try:
        nid = uuid.UUID(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found.") from exc
    node = await session.get(BridgeNode, nid)
    owner = _owner_filter(principal)
    if node is None or (owner is not None and node.owner_user_id != owner):
        raise HTTPException(status_code=404, detail="Not found.")
    if node.kind in ("app", "card") and (node.owner_user_id, node.key) in bridge.connections:
        raise HTTPException(status_code=409, detail="It's connected right now. It can be removed once it goes offline.")
    await session.execute(delete(BridgeNode).where(BridgeNode.id == nid))
    await session.commit()
    return {"deleted": True}
