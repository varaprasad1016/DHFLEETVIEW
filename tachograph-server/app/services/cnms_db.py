"""What CNMS knows about a camera, and how a new one is put there.

CNMS has no supported API for its device list (the endpoint exists in its source
but is commented out), so its own database is used directly. Reading answers
"does CNMS already have this device, and which companies can it go under".
Creating writes the same three rows CNMS writes when a camera is added by hand:
the SIM, the device, and the vehicle that ties them to a registration.

This is a live vendor database that the whole fleet's video depends on, so
creating is kept deliberately narrow:

  * it refuses outright if the device ID is already there - it never updates or
    deletes a camera that exists;
  * if any of the three rows fails, the ones already written are removed again,
    so a half-made camera cannot be left behind. These tables are MyISAM, which
    has no transactions at all, so this is done by hand rather than by rollback;
  * the only existing row it ever touches is the company's device allowance,
    and only to raise it - put back if the camera then fails;
  * it is off unless cnms_write_enabled is set.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

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


def _undo(connection, steps: list[tuple[str, tuple]], device_id: str) -> None:
    """Take back what was written before a camera failed halfway.

    MyISAM cannot roll back, so the rows are removed in the order opposite to
    the one they were written in. If even this fails there is nothing more to be
    done automatically, so it is logged loudly with the device ID to look for.
    """
    for sql, args in reversed(steps):
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, args)
        except Exception:  # noqa: BLE001
            logger.exception("could not undo part of a failed CNMS camera - check %s by hand "
                             "in CNMS for a half-made device", device_id)


def create_vehicle(device_id: str, registration: str, sim_no: str = "", company: str = "",
                   channels: int = 4) -> dict:
    """Put a new camera into CNMS, the way the CNMS screens would.

    Returns what was created. Raises CnmsError if writing is switched off, the
    company is unknown, or the camera is already there - none of which should
    reach here, because the page checks all three first.
    """
    if not settings.cnms_write_enabled:
        raise CnmsError("Creating cameras in CNMS is switched off on this server.")
    device_id, registration = device_id.strip(), registration.strip().upper()
    if not device_id or not registration:
        raise CnmsError("A device ID and a registration are needed.")
    if not 1 <= channels <= 16:
        raise CnmsError("That is not a sensible number of channels.")

    company = company.strip() or settings.cnms_default_company
    now = datetime.now()
    connection = _connect()
    undo: list[tuple[str, tuple]] = []   # what to put back if this goes wrong
    try:
        with connection.cursor() as cursor:
            cursor.execute("select id, cMaxDevNum, "
                           "(select count(*) from gps_devices d where d.dCompanyID = c.id) "
                           "from gps_companys c where c.cName = %s", (company,))
            row = cursor.fetchone()
            if row is None:
                raise CnmsError(f"CNMS has no company called {company}.")
            company_id, limit, used = row

            # Never touch a camera that is already there - say so and stop.
            cursor.execute("select id from gps_devices where dName = %s", (device_id,))
            if cursor.fetchone():
                raise CnmsError(f"CNMS already has device {device_id}.")

            if used >= (limit or 0):
                cursor.execute("update gps_companys set cMaxDevNum = %s where id = %s",
                               (used + 5, company_id))
                undo.append(("update gps_companys set cMaxDevNum = %s where id = %s",
                             (limit or 0, company_id)))
                logger.info("raised the CNMS device allowance for %s to %s", company, used + 5)

            cursor.execute(
                "insert into gps_sims (sCompanyID, sNo, sMonthFlow, sMonthDay, sRegTime, sState, "
                "sRemark, sAddTime) values (%s, %s, '3072', 1, %s, 1, '', %s)",
                (company_id, sim_no or device_id, now, now))
            sim_id = cursor.lastrowid
            undo.append(("delete from gps_sims where id = %s", (sim_id,)))

            cursor.execute(
                "insert into gps_devices (dCompanyID, dSimID, dManufactureId, dType, dName, "
                "dChannelNum, dPara, dInstallationTime, dIsInstallation, dAddTime) "
                "values (%s, %s, '81803', 1, %s, %s, %s, %s, 1, %s)",
                (company_id, sim_id, device_id, channels,
                 ",".join(f"CH{n}" for n in range(1, channels + 1)),
                 now.strftime("%Y-%m-%d %H:%M:%S"), now))
            device_key = cursor.lastrowid
            undo.append(("delete from gps_devices where id = %s", (device_key,)))

            cursor.execute(
                "insert into gps_vehicles (vPlate, vPlateColorID, vCompanyID, vBobyColor, vDeviceID, "
                "vDeviceName, vSimID, vSimNo, vOwnerName, vOwnerBobyNo, vOwnerAddress, vOwnerSex, "
                "vOwnerEmail, vOwnerLinkTel, vFrameNo, vEngineNo, vInstaller, vStartServDate, "
                "vStopServDate, vIcoID, vState, vRegisterNo, vMore, vEdtorID, vLastUpdated, vScore, "
                "vVehType, vBeginMonthScore, vOnlineStatus) "
                "values (%s, 0, %s, '', %s, %s, %s, %s, '', '', '', 'Male', '', '', '', '', '', %s, "
                "%s, 4, 1, %s, '', 1, %s, 1000, 2, 1000, 6)",
                (registration, company_id, device_key, device_id, sim_id, sim_no,
                 now.replace(hour=0, minute=0, second=0, microsecond=0),
                 now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=365 * 50),
                 device_id, now))
            vehicle_id = cursor.lastrowid
    except Exception:
        _undo(connection, undo, device_id)
        raise
    finally:
        connection.close()

    logger.info("created CNMS camera %s (%s) under %s", device_id, registration, company)
    return {"id": device_key, "sim_id": sim_id, "vehicle_id": vehicle_id,
            "company": company, "company_id": company_id, "plate": registration}


def find_device(device_id: str) -> dict | None:
    """The CNMS device with this ID, if it is already there."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("select d.id, d.dCompanyID, c.cName, v.vPlate from gps_devices d "
                           "left join gps_companys c on c.id = d.dCompanyID "
                           "left join gps_vehicles v on v.vDeviceID = d.id where d.dName = %s", (device_id,))
            row = cursor.fetchone()
    return {"id": row[0], "company_id": row[1], "company": row[2], "plate": row[3]} if row else None
