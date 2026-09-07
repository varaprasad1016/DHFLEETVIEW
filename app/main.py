"""FastAPI entrypoint. /health works standalone; the protocol listeners are
wired in once the persistence + services layers land (Phase 4)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.api.license import router as license_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 4 wires the DB-backed dependencies and starts the Path A / Path B /
    # TBA listeners here. Kept minimal so the API boots without infra during
    # early phases.
    yield


app = FastAPI(title="Tachograph Server", version="0.1.0", lifespan=lifespan)
app.include_router(license_router)


_STATIC = Path(__file__).parent / "static"


@app.get("/approver", response_class=HTMLResponse)
async def approver() -> str:
    """The phone approver PWA (same-origin, so no CORS/CSP issues)."""
    return (_STATIC / "approver.html").read_text(encoding="utf-8")


@app.get("/approver/manifest.webmanifest")
async def approver_manifest() -> JSONResponse:
    icon = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'"
        "%3E%3Crect width='192' height='192' rx='42' fill='%230b1220'/%3E%3Ccircle cx='96'"
        " cy='96' r='40' fill='none' stroke='%2338bdf8' stroke-width='12'/%3E%3Cpath d='M96 70v28'"
        " stroke='%2338bdf8' stroke-width='12' stroke-linecap='round'/%3E%3C/svg%3E"
    )
    return JSONResponse({
        "name": "Tacho Licence",
        "short_name": "Tacho",
        "start_url": "../approver",
        "scope": "../approver",
        "display": "standalone",
        "background_color": "#0b1220",
        "theme_color": "#0b1220",
        "icons": [{"src": icon, "sizes": "192x192", "type": "image/svg+xml", "purpose": "any"}],
    })


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": app.version,
        "ports": {
            "api": settings.api_port,
            "tachosync_path_b": settings.tachosync_port,
            "gprs_path_a": settings.gprs_port,
            "tba_ws": settings.tba_ws_port,
        },
    }
