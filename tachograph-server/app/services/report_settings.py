"""Which infringement types appear on the driver weekly report.

Each office user chooses for their own reports. The super administrator can set
the default that everyone without their own choice gets. Hiding a type only
affects the weekly report (page and PDF); the infringement list keeps everything.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import AppSetting

# (rule code, title, group) — codes are the rules engine's (services/tacho_rules.py).
RULES: list[tuple[str, str, str]] = [
    ("continuous_driving", "Driving over 4h30 without a break", "Driving time"),
    ("daily_driving", "Daily driving over 10h", "Driving time"),
    ("daily_driving_extension", "More than two 10h driving days in the week", "Driving time"),
    ("weekly_driving", "Weekly driving over 56h", "Driving time"),
    ("fortnightly_driving", "Two-week driving over 90h", "Driving time"),
    ("daily_rest_short", "Daily rest under 9h", "Rest periods"),
    ("daily_rest_24h", "Daily rest not taken within 24 hours", "Rest periods"),
    ("daily_rest_reduction", "More than three reduced daily rests in the week", "Rest periods"),
    ("weekly_rest_period", "Weekly rest not taken within six 24-hour periods", "Rest periods"),
    ("wtd_break", "Over 6h working time without a break", "Working time"),
    ("wtd_daily_break", "Too little break in the working day", "Working time"),
    ("country_start", "No country entered at the start of work", "Records & card use"),
    ("country_end", "No country entered at the end of work", "Records & card use"),
    ("card_withdrawal", "Card withdrawn before the end of the working day", "Records & card use"),
]
CODES = {code for code, _, _ in RULES}
DEFAULT_KEY = "report_rules:default"


def user_key(user_id: int) -> str:
    return f"report_rules:user:{int(user_id)}"


async def _stored(session: AsyncSession, key: str) -> list[str] | None:
    row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return None
    return [c for c in row.value.get("hidden", []) if c in CODES]


async def hidden_for(session: AsyncSession, user_id: int | None) -> tuple[set[str], str]:
    """(hidden rule codes, where the choice came from: "yours" | "default" | "standard")."""
    if user_id is not None:
        mine = await _stored(session, user_key(user_id))
        if mine is not None:
            return set(mine), "yours"
    default = await _stored(session, DEFAULT_KEY)
    if default is not None:
        return set(default), "default"
    return set(), "standard"


async def save(session: AsyncSession, key: str, hidden: list[str], updated_by: str) -> list[str]:
    clean = sorted({c for c in hidden if c in CODES})
    row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    if row is None:
        session.add(AppSetting(key=key, value={"hidden": clean}, updated_by=updated_by))
    else:
        row.value = {"hidden": clean}
        row.updated_by = updated_by
    await session.commit()
    return clean


async def clear(session: AsyncSession, key: str) -> None:
    row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()
