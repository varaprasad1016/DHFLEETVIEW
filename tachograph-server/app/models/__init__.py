"""All ORM models. Importing this registers every table on Base.metadata."""

from app.database import Base
from app.models.core import (
    CompanyCard,
    Device,
    Driver,
    DriverAssignment,
    TbaInstance,
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
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect

__all__ = [
    "Base",
    "Device",
    "Driver",
    "DriverAssignment",
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
]
