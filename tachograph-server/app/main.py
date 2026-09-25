"""FastAPI entrypoint. /health works standalone; the protocol listeners are
wired in once the persistence + services layers land (Phase 4)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.config import settings
from app.api.license import router as license_router
from app.api.walkaround import router as walkaround_router
from app.api.tacho import router as tacho_router
from app.api.reminders import router as reminders_router
from app.api.caz import router as caz_router
from app.api.customers import router as customers_router
from app.api.shifts import router as shifts_router
from app.api.driver import router as driver_router
from app.api.modules import router as modules_router
from app.api.admin import router as admin_router
from app.api.maintenance import router as maintenance_router
from app.api.driver_records import router as driver_records_router
from app.api.earned_recognition import router as earned_recognition_router
from app.api.tacho_live import ingest_router as tacho_live_ingest_router, router as tacho_live_router
from app.api.driver_accounts import accounts_router as driver_accounts_router, auth_router as driver_auth_router
from app.api.bridge import public_router as bridge_public_router, router as bridge_router
from app.api.dvr import router as dvr_router
from app.api.billing import public_router as billing_public_router, router as billing_router
from app.api.mail import router as mail_router
from app.api.sims import router as sims_router
from app.api.sms_inbound import public_router as sms_public_router, router as sms_router
from app.services import download_server, scheduler, sms_sender
from app.services.auth import allowed_origins
from app.services.bridge_server import bridge


_tacho_log = logging.getLogger("tacho")
if not _tacho_log.handlers:
    # uvicorn configures only its own loggers, so without this everything the
    # platform does of its own accord - emailing an invoice, sending a week of
    # driver reports - would happen with nothing in the log to show for it.
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _tacho_log.addHandler(_log_handler)
    _tacho_log.setLevel(logging.INFO)
    _tacho_log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The Tacho Bridge App endpoint (company cards and card racks) runs inside
    # the API process. Path A / Path B download listeners are still to come.
    if settings.bridge_enabled:
        try:
            await bridge.start()
        except Exception:  # noqa: BLE001 - the API must still come up
            logging.getLogger("tacho.bridge").exception("Tacho Bridge endpoint failed to start")

    # The listeners a vehicle sends its own tachograph file to. Off by default;
    # see services/download_server for why.
    downloads = []
    for label, server in download_server.build_servers():
        try:
            await server.start()
            downloads.append(server)
            logging.getLogger("tacho.download").info("listening for downloads on %s", label)
        except Exception:  # noqa: BLE001 - the API must still come up
            logging.getLogger("tacho.download").exception("%s failed to start", label)

    # Camera setup commands go out through the SIM provider when one is set up.
    sender = asyncio.create_task(sms_sender.run()) if settings.sms_url else None
    # Invoices every quarter and driver reports every Monday morning.
    clock = asyncio.create_task(scheduler.run()) if settings.schedule_enabled else None
    yield
    for task in (sender, clock):
        if task:
            task.cancel()
    for server in downloads:
        try:
            await server.stop()
        except Exception:  # noqa: BLE001 - shutting down must not raise
            logging.getLogger("tacho.download").exception("a download listener would not stop")
    await bridge.stop()


app = FastAPI(title="Tachograph Server", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Pages are same-origin; only our own site may make credentialed cross-origin calls.
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(license_router)
app.include_router(walkaround_router)
app.include_router(tacho_router)
app.include_router(reminders_router)
app.include_router(caz_router)
app.include_router(customers_router)
app.include_router(shifts_router)
app.include_router(driver_auth_router)
app.include_router(driver_router)
app.include_router(driver_accounts_router)
app.include_router(modules_router)
app.include_router(bridge_router)
app.include_router(dvr_router)
app.include_router(billing_router)
app.include_router(billing_public_router)
app.include_router(mail_router)
app.include_router(sims_router)
app.include_router(sms_router)
app.include_router(sms_public_router)
app.include_router(bridge_public_router)
app.include_router(admin_router)
app.include_router(maintenance_router)
app.include_router(driver_records_router)
app.include_router(earned_recognition_router)
app.include_router(tacho_live_ingest_router)
app.include_router(tacho_live_router)


_STATIC = Path(__file__).parent / "static"


@app.get("/approver", response_class=HTMLResponse)
async def approver() -> str:
    """The phone approver PWA (same-origin, so no CORS/CSP issues)."""
    return _with_theme((_STATIC / "approver.html").read_text(encoding="utf-8"))


_THEME_HEAD = '<link rel="stylesheet" href="assets/theme.css">\n<script src="assets/theme.js"></script>\n'
_AUTH_HEAD = '<script src="assets/auth.js"></script>\n'
_ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


def _with_theme(html: str) -> str:
    """Every page gets the shared light/dark theme; injected last in <head> so its
    [data-theme] rules sit after the page's own :root palette."""
    return html.replace("</head>", _THEME_HEAD + "</head>", 1)


@app.get("/assets/{name}")
async def asset(name: str) -> Response:
    path = _STATIC / "assets" / name
    if "/" in name or "\\" in name or path.suffix not in _ASSET_TYPES or not path.is_file():
        raise HTTPException(status_code=404)
    return Response(path.read_bytes(), media_type=_ASSET_TYPES[path.suffix],
                    headers={"Cache-Control": "no-cache"})


def _page(name: str) -> str:
    html = (_STATIC / name).read_text(encoding="utf-8")
    # Substitute white-label placeholders same as Traccar OverrideTextFilter
    from app.config import settings as _cfg
    title = getattr(_cfg, 'white_label_title', None) or 'DH FleetView'
    description = getattr(_cfg, 'white_label_description', None) or 'Fleet tracking & compliance'
    color_primary = getattr(_cfg, 'white_label_color_primary', None) or '#0b1220'
    html = html.replace('${title}', title).replace('${description}', description).replace('${colorPrimary}', color_primary)
    if name != "driver.html":  # the driver app has its own sign-in
        html = html.replace("</head>", _AUTH_HEAD + "</head>", 1)
    return _with_theme(html)


@app.get("/compliance", response_class=HTMLResponse)
async def compliance_page() -> str:
    return _page("compliance.html")


@app.get("/walkaround")
async def walkaround_page() -> RedirectResponse:
    """Walkaround checks are done in the driver app now."""
    return RedirectResponse("driver", status_code=302)


@app.get("/defects", response_class=HTMLResponse)
async def defects_page() -> str:
    return _page("defects.html")


@app.get("/walkaround-reports", response_class=HTMLResponse)
async def walkaround_reports_page() -> str:
    return _page("walkaround-reports.html")


@app.get("/earned-recognition", response_class=HTMLResponse)
async def earned_recognition_page() -> str:
    return _page("earned-recognition.html")


@app.get("/driver-records", response_class=HTMLResponse)
async def driver_records_page() -> str:
    return _page("driver-records.html")


@app.get("/maintenance", response_class=HTMLResponse)
async def maintenance_page() -> str:
    return _page("maintenance.html")


@app.get("/report-settings", response_class=HTMLResponse)
async def report_settings_page() -> str:
    return _page("report-settings.html")


@app.get("/tacho-live", response_class=HTMLResponse)
async def tacho_live_page() -> str:
    return _page("tacho-live.html")


@app.get("/hours", response_class=HTMLResponse)
async def hours_page() -> str:
    return _page("hours.html")


@app.get("/reminders", response_class=HTMLResponse)
async def reminders_page() -> str:
    return _page("reminders.html")


@app.get("/caz", response_class=HTMLResponse)
async def caz_page() -> str:
    return _page("caz.html")


@app.get("/driver", response_class=HTMLResponse)
@app.get("/driver-shift", response_class=HTMLResponse)
async def driver_page() -> str:
    """Driver mobile app: shift start/end, walkaround checks, jobs, fuel, faults, paperwork."""
    return _page("driver.html")


@app.get("/drivers")
async def drivers_page() -> RedirectResponse:
    """Drivers and their app PINs are managed on the DH FleetView Drivers page."""
    return RedirectResponse("/settings/drivers", status_code=302)


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page() -> str:
    return _page("jobs.html")


@app.get("/shifts", response_class=HTMLResponse)
async def shifts_page() -> str:
    return _page("shifts.html")


@app.get("/driver/manifest.webmanifest")
async def driver_manifest() -> JSONResponse:
    title = getattr(settings, "white_label_title", None) or "DH FleetView"
    return JSONResponse(
        {
            "name": f"{title} Driver",
            "short_name": "Driver",
            "start_url": "../driver#/live",
            "scope": "../",
            "display": "standalone",
            "background_color": "#f2f4f8",
            "theme_color": "#4f5de8",
            "icons": [],
        },
        media_type="application/manifest+json",
    )


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
