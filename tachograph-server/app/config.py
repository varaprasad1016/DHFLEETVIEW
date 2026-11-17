"""Application settings, env-driven. Every port and path is configurable."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Listener ports (all configurable) ---
    tachosync_port: int = 29000   # Path B: TachoSync binary protocol
    gprs_port: int = 21756        # Path A: Teltonika data protocol (query_ddd)
    # Both listeners are off until a real unit has been through them. Path A's
    # DDD framing is reconstructed rather than documented (see
    # protocol/gprs_handler), so the first FMC650 fitted may need it corrected -
    # and a listener nobody has tested against hardware should not be holding a
    # public port open in the meantime.
    gprs_enabled: bool = False
    tachosync_enabled: bool = False
    download_host: str = "0.0.0.0"
    # Whether to ask a unit for a download when one is due. Off means we accept
    # what a unit sends but never request anything, which is the safer half to
    # switch on first.
    download_request_enabled: bool = False
    tba_ws_port: int = 8765       # legacy WebSocket bridge (pre-0.8 app), unused

    # --- Tacho Bridge App endpoint (MQTT v5, the app's own protocol) ---
    bridge_enabled: bool = True
    bridge_host: str = "0.0.0.0"
    bridge_tls_port: int = 8883   # what the app connects to (dhfleetview.co.uk:8883)
    bridge_tls_cert: str = "D:/CMSServer/cert/dhfleetview/dhfleetview-chain.pem"
    bridge_tls_key: str = "D:/CMSServer/cert/dhfleetview/dhfleetview-key.pem"
    bridge_plain_port: int = 0    # unencrypted listener for local testing only (0 = off)
    bridge_plain_host: str = "127.0.0.1"
    # Built installers + updater manifests (scripts/publish_bridge_release.py writes here)
    bridge_release_dir: str = "D:/DHFleetViewData/tacho/bridge/releases"
    bridge_public_url: str = "https://dhfleetview.co.uk/tacho"

    # --- DVR setup by SMS (a spare Android phone polls the queue and sends) ---
    dvr_sms_key: str = ""          # the phone signs in with this; blank = the queue is closed
    dvr_sms_from: str = ""         # the sending phone's own number, shown in the office UI
    # Sending through the SIM provider's portal instead. Blank sms_url = off, and
    # the queue waits for something to collect it. See services/sms_sender.py.
    sms_url: str = ""
    sms_provider: str = "caburn"   # "caburn" speaks their XML API; "template" is anyone else
    sms_method: str = "POST"
    sms_username: str = ""
    sms_password: str = ""
    # Only used by the "template" provider, for a portal that is not Caburn's.
    sms_auth_header: str = "Authorization"
    sms_auth_value: str = ""
    sms_content_type: str = "application/json"
    sms_body_template: str = '{"to": "{to}", "message": "{text}"}'
    sms_success_contains: str = ""  # a send that answers 200 but did not send
    # Caburn post camera replies and delivery receipts to us; they include this
    # passphrase so the endpoint can tell their posts from anyone else's.
    sms_post_passphrase: str = ""

    # --- Invoicing ---
    company_name: str = "D&H Group Ltd"
    company_address: str = ("6 Renaissance Apartments, 20 Heritage Road, "
                            "Rainham, Essex, RM13 8QQ")
    # Placeholders until the real ones arrive. invoicing.not_ready() refuses to
    # email anything while these are still in place, so a placeholder cannot
    # reach a customer.
    company_vat_number: str = "GB 000 0000 00"
    company_number: str = "00000000"
    invoice_logo_path: str = "D:/DHFleetViewData/tacho/branding/logo.png"
    invoice_payment_terms: str = "Payment due within 30 days of the invoice date."
    invoice_number_prefix: str = "DH"
    invoice_vat_rate: float = 0.20
    # Standard monthly rates per vehicle, unless an account sets its own.
    # A vehicle is on one package, not a list of parts: the tacho package
    # already includes the live view, at a price agreed for the pair.
    rate_live: float = 10.00        # live view (and tracking)
    rate_tacho: float = 20.00       # tacho tracking + live view
    # Sending the invoices. No mail server anywhere yet, so this is off.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "invoices@dhfleetview.co.uk"
    smtp_from_name: str = "D&H Group Ltd"
    smtp_starttls: bool = True
    smtp_reply_to: str = ""
    # Invoices go out by themselves, on the first morning after a period
    # closes. Nothing can actually reach a customer until the rates, VAT number
    # and mail server are real - see invoicing.not_ready(), which is checked
    # before every send - so this being on is safe while they are placeholders.
    invoice_auto_send: bool = True
    # Customers are invoiced every three months, on the first morning of the
    # new quarter, for the quarter that has just ended. Set to 1 for monthly.
    # Periods are anchored to the calendar year, so they line up with VAT
    # quarters rather than drifting from whenever the server was last started.
    invoice_every_months: int = 3

    # --- Scheduled email ------------------------------------------------------
    # Everything the platform sends by itself is timed in this zone, so 6 a.m.
    # stays 6 a.m. through the March and October clock changes.
    schedule_timezone: str = "Europe/London"
    schedule_enabled: bool = True
    # The weekly driver report: Monday (1) at 6 a.m., to each account's own
    # registered email address.
    driver_report_auto_send: bool = True
    driver_report_weekday: int = 1        # 1 = Monday ... 7 = Sunday
    driver_report_hour: int = 6
    invoice_send_hour: int = 6
    # No more than this many driver reports attached to one weekly email; the
    # rest are listed in it and stay on the Hours page.
    driver_report_max_attachments: int = 25
    # Background jobs have nobody signed in, so they carry their own DH
    # FleetView identity: an API token generated by an administrator under
    # Settings -> Account. Blank = the scheduled jobs stand down and say so.
    traccar_api_token: str = ""
    # Accounts that should see every vehicle on the platform. A vehicle added
    # by anyone, in any way, is granted to these within a couple of minutes -
    # see services/fleet_access.py. An address that is a DH FleetView
    # administrator needs no grant and is left alone. Blank = off.
    # Set in .env: these are real people's addresses and do not belong in
    # the repository, which is also the source of the white-label copy.
    auto_share_emails: str = ""
    auto_share_seconds: int = 120
    # Accounts that must keep their administrator rights and must not vanish.
    # Checked every minute; rights taken away are put back, and anything that
    # happens is emailed - see services/account_guard.py.
    protected_accounts: str = ""   # set in .env, for the same reason
    account_guard_seconds: int = 60
    # Photos of DVR labels, and where CNMS keeps its own database details.
    dvr_label_dir: str = "D:/DHFleetViewData/tacho/labels"
    cnms_database_ini: str = "D:/CMSServer/Database.ini"
    cnms_default_company: str = "DH Group Fleet View"
    # CNMS is the live video platform's own database. Adding a camera there is
    # off unless this is set, so it cannot happen by accident on a test box.
    cnms_write_enabled: bool = False
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

    # --- Live tacho data (FMC650 via DH FleetView position forwarding) ---
    # Shared key DH FleetView sends in the X-Tacho-Live-Key header; blank = forwarding refused.
    tacho_live_key: str = ""

    # Written by scripts/backup.ps1; shown to the super administrator on the compliance hub.
    backup_status_file: str = "D:/Backups/dhfleetview/last-backup.json"
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

    # --- Driver app ---
    # Contacts tab, "Name|Role|Phone" entries separated by ';', e.g.
    # "Transport Office|Planning|01234 567890;Workshop|Defects|07700 900123"
    driver_contacts: str = ""

    # --- Access control ---
    # Office staff sign in to DH FleetView (Traccar); the tacho API checks that
    # session with Traccar. Role needed: "admin", "manager" (admin or a Traccar
    # manager, i.e. userLimit != 0) or "user" (any enabled account).
    traccar_url: str = "http://127.0.0.1:8090"
    manager_role: str = "manager"
    # Browser origins allowed to call the API with a DH FleetView session cookie.
    allowed_origins: str = "https://dhfleetview.co.uk,https://www.dhfleetview.co.uk"
    driver_session_days: int = 90
    # Who may switch modules on/off. Empty = any DH FleetView administrator;
    # otherwise a comma-separated list of administrator emails.
    super_admin_emails: str = ""


settings = Settings()
