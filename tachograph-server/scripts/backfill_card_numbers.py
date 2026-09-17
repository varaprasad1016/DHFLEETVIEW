r"""Fill tacho_files.card_number for driver-card files uploaded before it was stored.

Reads each archived driver-card file, parses it and saves only the card number,
so drivers can see their own tachograph data in the driver app. Safe to re-run.

    .venv\Scripts\python -m scripts.backfill_card_numbers
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select


async def main() -> None:
    from app.api.tacho import _parse_driver_card
    from app.database import SessionLocal
    from app.models.tacho import TachoFile
    from app.services import archive

    async with SessionLocal() as session:
        files = (await session.execute(
            select(TachoFile).where(TachoFile.file_kind == "driver_card", TachoFile.card_number.is_(None))
        )).scalars().all()
        filled = failed = 0
        for tf in files:
            try:
                parsed, _ = _parse_driver_card(archive.read(tf.storage_path))
            except Exception as exc:  # unreadable or missing archive file
                failed += 1
                print(f"skip {tf.filename}: {str(exc)[:120]}")
                continue
            if parsed.get("card_number"):
                tf.card_number = parsed["card_number"]
                filled += 1
                print(f"{tf.filename}: {tf.driver_ref} -> card ending {parsed['card_number'][-4:]}")
        await session.commit()
        print(f"filled {filled}, skipped {failed}, of {len(files)} driver-card files")


if __name__ == "__main__":
    asyncio.run(main())
