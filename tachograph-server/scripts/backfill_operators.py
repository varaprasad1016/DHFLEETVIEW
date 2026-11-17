"""Read the operating company off every vehicle-unit file already archived.

The operator was only captured from downloads after the fact, so files taken
before that carry no name even though the name is sitting in the file. This
reads each one again, records the company, and attaches it to the vehicle.

Nothing is overwritten: a vehicle already assigned to an operator keeps it, and
any disagreement is printed for a person to settle rather than applied.

    .venv\\Scripts\\python.exe scripts\\backfill_operators.py [--apply]

Without --apply it reports what it would do and changes nothing.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from sqlalchemy import select                                   # noqa: E402
from app.database import SessionLocal                           # noqa: E402
from app.models.core import Vehicle                             # noqa: E402
from app.models.tacho import TachoFile                          # noqa: E402
from app.services import archive, ddd_parser, operators         # noqa: E402


async def main(apply: bool) -> None:
    tally: Counter = Counter()
    names: Counter = Counter()
    conflicts: list[str] = []

    async with SessionLocal() as session:
        files = (await session.execute(
            select(TachoFile).where(TachoFile.file_kind == "vehicle_unit")
            .order_by(TachoFile.created_at))).scalars().all()
        print(f"{len(files)} vehicle-unit file(s) archived\n")

        for tf in files:
            try:
                raw = ddd_parser.parse_vehicle_unit_company(archive.read(tf.storage_path))
            except Exception as exc:                            # noqa: BLE001
                tally["unreadable"] += 1
                print(f"  {tf.vehicle_ref or tf.id}: could not be read ({exc})")
                continue

            name = operators.clean_name(raw)
            if name is None:
                tally["no name in the file"] += 1
                continue
            names[name] += 1

            operator = await operators.resolve(session, name)
            if operator is None:
                tally["no name in the file"] += 1
                continue

            if tf.operator_id != operator.id:
                tf.operator_id = operator.id
                tf.company_name = name
                tally["file tagged"] += 1

            if tf.vehicle_id:
                vehicle = await session.get(Vehicle, tf.vehicle_id)
                outcome = await operators.note_vehicle(vehicle, operator)
                tally[f"vehicle {outcome}"] += 1
                if outcome == "conflict":
                    conflicts.append(f"{vehicle.registration}: the unit says {name}")

        if apply:
            await session.commit()
            print("changes saved\n")
        else:
            await session.rollback()
            print("dry run - nothing was saved (pass --apply to save)\n")

    print("operating companies found:")
    for name, count in names.most_common():
        print(f"  {name}  ({count} file(s))")
    print("\nwhat happened:")
    for what, count in sorted(tally.items()):
        print(f"  {what}: {count}")
    if conflicts:
        print("\nneeds a decision - the unit names a different company:")
        for line in conflicts:
            print(f"  {line}")


asyncio.run(main("--apply" in sys.argv))
