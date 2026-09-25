"""Remove a vehicle-unit dataset that was only ever test material.

Everything that came out of the named operator's downloads goes: the archived
.ddd files, the rows parsed from them, the vehicle they created, and the
operator record itself. Driver-card data is deliberately untouched, even where
a card happens to mention one of these registrations - those are real drivers'
records and the registration there is only text.

Everything removed is written to a dated folder on D: first, the archived files
included, so the whole set can be put back if it turns out to be wanted.

    .venv\\Scripts\\python.exe scripts\\remove_vu_dataset.py "OPERATOR NAME" [--apply]

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


async def main(operator_name: str, apply: bool) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUPS / f"removed-vu-dataset-{stamp}"

    async with SessionLocal() as session:
        async def rows(sql: str, **kw):
            return (await session.execute(text(sql), kw)).mappings().all()

        files = await rows(
            """select f.* from tacho_files f join operators o on o.id = f.operator_id
               where o.name = :name and f.file_kind = 'vehicle_unit'""",
            name=operator_name)
        if not files:
            print(f"No vehicle-unit files belong to {operator_name!r}. Nothing to do.")
            return
        ids = [r["id"] for r in files]

        acts = (await session.execute(text(
            "select count(*) from tacho_activities where source_file_id = any(:ids)"),
            {"ids": ids})).scalar()
        infs = (await session.execute(text(
            "select count(*) from infringements where source_file_id = any(:ids)"),
            {"ids": ids})).scalar()
        vehicles = await rows(
            """select v.* from vehicles v join operators o on o.id = v.operator_id
               where o.name = :name""", name=operator_name)
        operators_rows = await rows("select * from operators where name = :name",
                                    name=operator_name)

        # Driver-card records that merely mention one of these registrations are
        # real and stay; counted here so the report can say so out loud.
        regs = [v["registration"] for v in vehicles]
        mentioned = (await session.execute(text(
            """select count(*) from tacho_activities a
               join tacho_files f on f.id = a.source_file_id
               where f.file_kind = 'driver_card'
                 and replace(upper(a.vehicle_ref), ' ', '') = any(:regs)"""),
            {"regs": regs})).scalar() if regs else 0

        print(f"operator          : {operator_name}")
        print(f"vehicle-unit files: {len(files)}")
        print(f"activities on them: {acts}")
        print(f"infringements     : {infs}")
        print(f"vehicles          : {regs}")
        print(f"operator records  : {len(operators_rows)}")
        print(f"\ndriver-card rows mentioning those registrations: {mentioned} (kept)")

        if not apply:
            print("\ndry run - nothing was removed (pass --apply to remove)")
            return

        # Back up everything first, the archived files included.
        out.mkdir(parents=True, exist_ok=True)
        (out / "rows.json").write_text(json.dumps({
            "taken_at": datetime.now().isoformat(),
            "operator": operator_name,
            "why": "vehicle-unit dataset used only for testing, removed on request",
            "files": [{k: str(v) for k, v in r.items()} for r in files],
            "vehicles": [{k: str(v) for k, v in r.items()} for r in vehicles],
            "operators": [{k: str(v) for k, v in r.items()} for r in operators_rows],
            "activity_count": acts, "infringement_count": infs,
        }, indent=2), encoding="utf-8")

        saved = 0
        archive_dir = out / "archive"
        archive_dir.mkdir(exist_ok=True)
        for row in files:
            source = Path(str(row["storage_path"]))
            if source.is_file():
                shutil.copy2(source, archive_dir / source.name)
                saved += 1
        print(f"\nbacked up to {out}  ({saved} archived file(s) copied)")

        # Children first: the foreign keys onto vehicles are NO ACTION.
        await session.execute(text("delete from tacho_activities where source_file_id = any(:ids)"), {"ids": ids})
        await session.execute(text("delete from infringements where source_file_id = any(:ids)"), {"ids": ids})
        await session.execute(text("delete from tacho_files where id = any(:ids)"), {"ids": ids})
        if vehicles:
            await session.execute(text("delete from vehicles where id = any(:vids)"),
                                  {"vids": [v["id"] for v in vehicles]})
        await session.execute(text("delete from operators where name = :name"), {"name": operator_name})
        await session.commit()

        removed = 0
        for row in files:
            source = Path(str(row["storage_path"]))
            if source.is_file():
                source.unlink()
                removed += 1
        print(f"removed {len(files)} file row(s), {acts} activity row(s), "
              f"{len(vehicles)} vehicle(s), {len(operators_rows)} operator record(s), "
              f"and {removed} archived file(s) from disk")


if len(sys.argv) < 2:
    print(__doc__)
    raise SystemExit(1)
asyncio.run(main(sys.argv[1], "--apply" in sys.argv))
