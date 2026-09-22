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
from app.models.shifts import Shift, ShiftPhoto, Job, JobMessage, ShiftJob
from app.models.driver_app import FuelLog, DriverPaperwork
from app.models.driver_auth import DriverAccount, DriverMembership, DriverSession
from app.models.settings import AppSetting
from app.models.tacho_live import TachoLiveActivity, TachoLiveAlert, TachoLiveStatus
from app.models.infringement_review import InfringementReview
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule
from app.models.driver_records import DriverCpcCourse, DriverRecord
from app.models.bridge import BridgeCredential, BridgeNode
from app.models.dvr import DvrCommand, DvrMessage
from app.models.billing import BillingAccount, Invoice, InvoiceLine
from app.models.sms_inbound import SmsInbound
from app.models.sim import SimCard

__all__ = [
    "Base",
    "BillingAccount",
    "SmsInbound",
    "SimCard",
    "Invoice",
    "InvoiceLine",
    "BridgeCredential",
    "DvrCommand",
    "DvrMessage",
    "BridgeNode",
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
    "Shift",
    "ShiftPhoto",
    "Job",
    "ShiftJob",
    "JobMessage",
    "FuelLog",
    "DriverPaperwork",
    "DriverAccount",
    "DriverSession",
    "DriverMembership",
    "AppSetting",
    "TachoLiveStatus",
    "TachoLiveActivity",
    "TachoLiveAlert",
    "InfringementReview",
    "MaintenanceSchedule",
    "MaintenanceRecord",
    "DriverRecord",
    "DriverCpcCourse",
]
