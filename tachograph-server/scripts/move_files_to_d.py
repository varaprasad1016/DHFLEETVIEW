r"""Point stored file paths at the new data drive after the tacho files folder moves.

    .venv\Scripts\python -m scripts.move_files_to_d --old C:\tachograph-server\data --new D:\DHFleetViewData\tacho\files [--apply]

Without --apply it only reports. With --apply it rewrites the paths in one
transaction, then checks every referenced file exists at its new location.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

COLUMNS = [
    ("tacho_files", "storage_path"), ("walkaround_photos", "storage_path"), ("walkaround_checks", "signature_path"),
    ("walkaround_defects", "photo_key"), ("shift_photos", "storage_path"), ("fuel_logs", "receipt_path"),
    ("driver_paperwork", "storage_path"), ("infringement_reviews", "driver_signature_path"),
    ("maintenance_records", "document_path"), ("driver_cpc_courses", "certificate_path"),
]


def rewrite(value: str, old: str, new: str, project: str) -> str | None:
    """New path for a stored path under the old folder (absolute or project-relative), else None."""
    v = value.replace("/", "\\")
    old_n = old.rstrip("\\") + "\\"
    rel_prefix = Path(old).resolve().relative_to(Path(project).resolve()).as_posix().replace("/", "\\") + "\\"
    if v.lower().startswith(old_n.lower()):
        return new.rstrip("\\") + "\\" + v[len(old_n):]
    if v.lower().startswith(rel_prefix.lower()):
        return new.rstrip("\\") + "\\" + v[len(rel_prefix):]
    return None


async def main() -> None:
    from app.database import SessionLocal

    p = argparse.ArgumentParser()
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--project", default=r"C:\tachograph-server")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    async with SessionLocal() as session:
        changes = []
        for table, column in COLUMNS:
            exists = (await session.execute(text(
                "select 1 from information_schema.columns where table_name=:t and column_name=:c"), {"t": table, "c": column})).first()
            if not exists:
                continue
            rows = (await session.execute(text(f"select id, {column} from {table} where {column} is not null"))).all()
            moved = [(rid, old, rewrite(old, args.old, args.new, args.project)) for rid, old in rows]
            moved = [m for m in moved if m[2]]
            print(f"{table}.{column}: {len(rows)} paths, {len(moved)} under the old folder")
            changes += [(table, column, rid, new) for rid, _, new in moved]
        missing = [new for *_, new in changes if not Path(new).exists()]
        print(f"{len(changes)} paths to rewrite; {len(missing)} not found at the new location")
        for m in missing[:10]:
            print("  missing:", m)
        if not args.apply:
            return
        if missing:
            raise SystemExit("Not applying: copy the files first (some are missing at the new location).")
        for table, column, rid, new in changes:
            await session.execute(text(f"update {table} set {column}=:v where id=:id"), {"v": new, "id": rid})
        await session.commit()
        print("applied")


if __name__ == "__main__":
    asyncio.run(main())
