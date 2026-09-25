"""Remove driver-card material that was only ever test data.

Takes out the archived .ddd cards, the activity spans read from them, the
infringements the engine found, and the debrief records attached to those
infringements - including any signature image, which lives on disk rather than
in the database and would otherwise be left behind.

Driver app accounts are deliberately left alone. They are logins with PINs
rather than card data, and removing one locks that driver out of the app; say
so explicitly with --accounts if that is wanted.

Everything is copied to a dated folder on D: before anything is deleted.

    .venv\\Scripts\\python.exe scripts\\remove_card_dataset.py [--apply] [--accounts]

Without --apply it reports what it would remove and changes nothing.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text                                     # noqa: E402
from app.database import SessionLocal                           # noqa: E402

BACKUPS = Path("D:/DHFleetViewData/tacho/backups")


async def main(apply: bool, accounts: bool) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUPS / f"removed-card-dataset-{stamp}"

    async with SessionLocal() as session:
        async def rows(sql: str, **kw):
            return (await session.execute(text(sql), kw)).mappings().all()

        files = await rows("select * from tacho_files where file_kind = 'driver_card'")
        if not files:
            print("No driver-card files are archived. Nothing to do.")
            return
        ids = [r["id"] for r in files]

        acts = (await session.execute(text(
            "select count(*) from tacho_activities where source_file_id = any(:ids)"),
            {"ids": ids})).scalar()
        infringements = await rows(
            "select * from infringements where source_file_id = any(:ids)", ids=ids)
        reviews = await rows(
            """select r.* from infringement_reviews r
               join infringements i on i.id = r.infringement_id
               where i.source_file_id = any(:ids)""", ids=ids)
        signatures = [r["driver_signature_path"] for r in reviews
                      if r.get("driver_signature_path")]
        driver_accounts = await rows("select * from driver_accounts") if accounts else []

        print(f"driver-card files : {len(files)}")
        print(f"activities        : {acts}")
        print(f"infringements     : {len(infringements)}")
        print(f"debrief records   : {len(reviews)}  (signature images: {len(signatures)})")
        print(f"driver app accounts: {len(driver_accounts)}"
              f"{'' if accounts else '  (kept - pass --accounts to remove)'}")

        if not apply:
            print("\ndry run - nothing was removed (pass --apply to remove)")
            return

        out.mkdir(parents=True, exist_ok=True)
        (out / "rows.json").write_text(json.dumps({
            "taken_at": datetime.now().isoformat(),
            "why": "driver-card material used only for testing, removed on request",
            "files": [{k: str(v) for k, v in r.items()} for r in files],
            "infringements": [{k: str(v) for k, v in r.items()} for r in infringements],
            "reviews": [{k: str(v) for k, v in r.items()} for r in reviews],
            "driver_accounts": [{k: str(v) for k, v in r.items()} for r in driver_accounts],
            "activity_count": acts,
        }, indent=2), encoding="utf-8")

        kept = out / "archive"
        kept.mkdir(exist_ok=True)
        saved = 0
        for row in files:
            source = Path(str(row["storage_path"]))
            if source.is_file():
                shutil.copy2(source, kept / source.name)
                saved += 1
        for path in signatures:
            source = Path(str(path))
            if source.is_file():
                shutil.copy2(source, kept / source.name)
                saved += 1
        print(f"\nbacked up to {out}  ({saved} file(s) copied)")

        # Reviews cascade from infringements, but the rows are deleted first so
        # the count reported is the count actually removed.
        await session.execute(text(
            """delete from infringement_reviews where infringement_id in
               (select id from infringements where source_file_id = any(:ids))"""), {"ids": ids})
        await session.execute(text("delete from infringements where source_file_id = any(:ids)"), {"ids": ids})
        await session.execute(text("delete from tacho_activities where source_file_id = any(:ids)"), {"ids": ids})
        await session.execute(text("delete from tacho_files where id = any(:ids)"), {"ids": ids})
        if accounts and driver_accounts:
            await session.execute(text("delete from driver_sessions"))
            await session.execute(text("delete from driver_accounts"))
        await session.commit()

        removed = 0
        for path in [str(r["storage_path"]) for r in files] + [str(p) for p in signatures]:
            source = Path(path)
            if source.is_file():
                source.unlink()
                removed += 1
        print(f"removed {len(files)} card file(s), {acts} activity row(s), "
              f"{len(infringements)} infringement(s), {len(reviews)} debrief record(s)"
              + (f", {len(driver_accounts)} app account(s)" if accounts else "")
              + f", and {removed} file(s) from disk")


asyncio.run(main("--apply" in sys.argv, "--accounts" in sys.argv))
