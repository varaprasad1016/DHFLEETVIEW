"""All ORM models. Importing this registers every table on Base.metadata."""

from app.database import Base
from app.models.core import (
    Company,
    CompanyCard,
    Device,
    Driver,
    DriverAssignment,
    DriverCompany,
    TbaInstance,
    Vehicle,
)
from app.models.integrations import (
    CardEvent,
    SftpClient,
    Webhook,
    WebhookDelivery,
)
from app.models.operations import (
    ComplianceState,
    FileRecord,
    Schedule,
)
from app.models.licensing import LicenseState
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect, WalkaroundPhoto
from app.models.tacho import TachoActivity, TachoFile, Infringement
from app.models.vehicle import VehicleStatus

__all__ = [
    "Base",
    "Company",
    "Device",
    "Vehicle",
    "Driver",
    "DriverAssignment",
    "DriverCompany",
    "CompanyCard",
    "TbaInstance",
    "Schedule",
    "FileRecord",
    "ComplianceState",
    "SftpClient",
    "Webhook",
    "WebhookDelivery",
    "CardEvent",
    "LicenseState",
    "WalkaroundCheck",
    "WalkaroundDefect",
    "WalkaroundPhoto",
    "TachoActivity",
    "TachoFile",
    "Infringement",
    "VehicleStatus",
]
