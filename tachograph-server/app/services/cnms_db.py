"""What CNMS knows about a camera.

CNMS has no supported API for its device list (the endpoint exists in its source
but is commented out), so its own database is read directly. This module is
read-only on purpose: it answers "does CNMS already have this device, and which
companies can it go under" so the platform can tell the operator what to expect
before anything is created.
"""

from __future__ import annotations

import logging
import re

from app.config import settings

logger = logging.getLogger("tacho.cnms")


class CnmsError(Exception):
    pass


def _settings() -> dict:
    """CNMS keeps its database details in Database.ini next to the server."""
    try:
        text = open(settings.cnms_database_ini, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        raise CnmsError("CNMS database settings were not found on this server.") from exc

    def value(key: str, default: str = "") -> str:
        match = re.search(rf"(?mi)^{key}\s*=\s*(.*)$", text)
        return match.group(1).strip() if match else default

    return {"host": value("DBIP", "127.0.0.1"), "port": int(value("DBPort", "3306") or 3306),
            "user": value("DBUserName"), "password": value("DBPassword"), "database": value("DBName")}


def _connect():
    import pymysql

    details = _settings()
    if not details["user"] or not details["database"]:
        raise CnmsError("CNMS database settings are incomplete on this server.")
    return pymysql.connect(host=details["host"], port=details["port"], user=details["user"],
                           password=details["password"], database=details["database"],
                           charset="utf8mb4", autocommit=True, connect_timeout=8)


def available() -> bool:
    """Whether CNMS can be reached from here at all."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
        return True
    except Exception:  # noqa: BLE001 - the page simply offers less
        return False


def companies() -> list[dict]:
    """The companies a camera can belong to in CNMS, and how full each one is."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("select c.id, c.cName, c.cMaxDevNum, "
                           "(select count(*) from gps_devices d where d.dCompanyID = c.id) "
                           "from gps_companys c order by c.cName")
            rows = cursor.fetchall()
    return [{"id": row[0], "name": row[1], "limit": row[2], "used": row[3]} for row in rows]


def find_device(device_id: str) -> dict | None:
    """The CNMS device with this ID, if it is already there."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("select d.id, d.dCompanyID, c.cName, v.vPlate from gps_devices d "
                           "left join gps_companys c on c.id = d.dCompanyID "
                           "left join gps_vehicles v on v.vDeviceID = d.id where d.dName = %s", (device_id,))
            row = cursor.fetchone()
    return {"id": row[0], "company_id": row[1], "company": row[2], "plate": row[3]} if row else None
