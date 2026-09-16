r"""Admin recovery: unpair the licence phone and rotate the pairing PIN.

Use when the paired phone's signing key is lost (site data cleared, new phone,
different browser). The approved cycle is kept; only the phone binding is
cleared, so the next phone to pair with the new PIN takes control.

Run on the server, then restart the tacho-api task so it loads the new PIN:
    .venv\Scripts\python -m scripts.reset_pairing
"""

from __future__ import annotations

import asyncio
import re
import secrets
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


def _rotate_pin() -> str:
    pin = f"{secrets.randbelow(10**8):08d}"
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^LICENSE_PAIRING_PIN=.*$", f"LICENSE_PAIRING_PIN={pin}", text)
    if n == 0:
        text = text.rstrip("\n") + f"\nLICENSE_PAIRING_PIN={pin}\n"
    env.write_text(text, encoding="utf-8")
    (ROOT / ".runtime" / "PAIRING_PIN.txt").write_text(pin + "\n", encoding="utf-8")
    return pin


async def _unpair() -> str | None:
    from app.config import settings
    from app.database import SessionLocal
    from app.models.licensing import LicenseState

    async with SessionLocal() as session:
        state = (
            await session.execute(
                select(LicenseState).where(LicenseState.server_id == settings.license_server_id)
            )
        ).scalar_one_or_none()
        if state is None or not state.public_key:
            return None
        old = state.public_key[:16]
        state.public_key = None
        state.paired_at = None
        await session.commit()
        return old


def main() -> None:
    old = asyncio.run(_unpair())
    print(f"Unpaired key {old}…" if old else "Server was not paired.")
    print(f"New pairing PIN: {_rotate_pin()}")
    print("Restart tacho-api so the new PIN takes effect.")


if __name__ == "__main__":
    main()
