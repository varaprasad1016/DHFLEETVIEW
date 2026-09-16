"""Application settings, env-driven. Every port and path is configurable."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Listener ports (all configurable) ---
    tachosync_port: int = 29000   # Path B: TachoSync binary protocol
    gprs_port: int = 21756        # Path A: Teltonika data protocol (query_ddd)
    tba_ws_port: int = 8765       # forked Tacho Bridge App connects here
    api_port: int = 8000

    # --- Infrastructure ---
    database_url: str = "postgresql+asyncpg://tacho:tacho@postgres:5432/tacho"
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "tacho-files"
    minio_secure: bool = False

    # --- Compliance windows (EU 561/2006), in days ---
    driver_interval_days: int = 28
    vehicle_interval_days: int = 90
    driver_warning_days: int = 25
    vehicle_warning_days: int = 85

    # --- Driver-card parsing -------------------------------------------------
    # The MIT tachograph-go CLI is the preferred reader when installed. The
    # built-in Gen1 reader remains a deliberately explicit fallback so an
    # installation without the optional binary can still archive and analyse
    # cards.
    tacho_parser_enabled: bool = True
    tacho_parser_binary: str = ""
    tacho_parser_timeout: int = 30
    tacho_parser_authenticate: bool = False
    tacho_parser_fallback: bool = False

    # Uploads are assigned to the company belonging to the signed-in account.
    # Until the account-authentication layer is connected, deployments can set
    # this UUID explicitly; when it is blank, a single active company is used.
    tacho_account_company_id: str = ""

    # --- Tacho file archive (native deploy: local filesystem, not MinIO) ---
    archive_path: str = "data/archive"
    archive_retention_months: int = 12  # DVSA: keep card & VU data at least 12 months

    # --- DVLA / DVSA vehicle data (MOT, tax, Euro status by registration) ---
    # Free DVLA Vehicle Enquiry Service (VES) API key; register at
    # register-for-ves.driver-vehicle-licensing.api.gov.uk. Blank => feature shows
    # "not configured" and never calls out.
    dvla_ves_api_key: str = ""
    dvla_ves_url: str = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
    reminder_due_soon_days: int = 30   # flag MOT/tax due within this many days

    # --- White-label branding (substituted into static HTML pages) ---
    white_label_title: str = "DH FleetView"
    white_label_description: str = "Fleet tracking & compliance"
    white_label_color_primary: str = "#0b1220"

    # --- Security ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 720

    # --- Monthly licence (phone-approved killswitch) ---
    # Tacho downloads are gated on a monthly approval only the owner's phone
    # can produce (ECDSA P-256; the server holds only the public key). Each
    # cycle runs from the 15th 00:00 UTC to the next 15th; a missed renewal
    # hard-suspends tacho downloads at the boundary. GPS is unaffected.
    license_enforce: bool = True
    license_server_id: str = "dhfleetview-tacho"
    # One-time pairing PIN: the phone registers its public key once, while the
    # server is unpaired and this PIN matches; then the PIN is spent. Set a
    # fresh value in .env for setup; blank disables new pairing.
    license_pairing_pin: str = ""
    # How fresh a signed approval timestamp must be, to blunt replay.
    license_approval_window_seconds: int = 900
    license_renew_day: int = 15

    # --- TLS (optional on external TCP/WS) ---
    tls_enabled: bool = False
    tls_cert_path: str = ""
    tls_key_path: str = ""


settings = Settings()
