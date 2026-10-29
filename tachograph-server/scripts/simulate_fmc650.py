r"""Send simulated FMC650 tachograph live data, shaped exactly like DH FleetView's
position forwarding, so the live tacho features can be tried before trackers are
fitted.

A shift: 15 min other work, driving, a 45 min break, more driving. The tachograph
figures (continuous driving, daily/weekly driving, time left) are worked out as a
real tachograph would report them.

    .venv\Scripts\python -m scripts.simulate_fmc650 --card DB07190162033713 --reg "PN19 HNR" ^
        --minutes 360 --start-minutes-ago 360

    --no-card     drive without a card inserted
    --step 5      minutes of simulated time between records
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timedelta, timezone


def id_parts(card: str) -> tuple[int, int]:
    card = card.ljust(16)[:16]
    return (int.from_bytes(card[:8][::-1].encode("latin-1"), "big"),
            int.from_bytes(card[8:][::-1].encode("latin-1"), "big"))


def name_hex(text: str) -> str:
    return "01" + text.encode("latin-1").hex()


def plan(first_drive: int, total: int) -> list[tuple[int, int, str]]:
    """(start minute, end minute, activity)"""
    segments, t = [(0, 15, "work")], 15
    segments.append((t, t + first_drive, "drive")); t += first_drive
    segments.append((t, t + 45, "rest")); t += 45
    if t < total:
        segments.append((t, total, "drive"))
    return [(a, min(b, total), k) for a, b, k in segments if a < total]


STATE = {"rest": 0, "available": 1, "work": 2, "drive": 3}


def records(args) -> list[dict]:
    start = datetime.now(timezone.utc) - timedelta(minutes=args.start_minutes_ago)
    msb, lsb = id_parts(args.card)
    segs = plan(args.first_drive, args.minutes)
    out = []
    continuous = daily = 0
    brk = 0
    for minute in range(0, args.minutes + 1, args.step):
        seg = next((s for s in segs if s[0] <= minute < s[1]), segs[-1])
        kind = seg[2]
        # accumulate over the step just finished
        if minute:
            prev = next((s for s in segs if s[0] <= minute - args.step < s[1]), segs[-1])
            if prev[2] == "drive":
                continuous += args.step
                daily += args.step
                brk = 0
            elif prev[2] == "rest":
                brk += args.step
                if brk >= 45:
                    continuous = 0
        time_state = 0
        if continuous >= 270:
            time_state = 2
        elif continuous >= 255:
            time_state = 1
        attrs = {
            "io184": STATE[kind],
            "io187": 0 if args.no_card else 1,
            "io189": time_state,
            "io56": continuous, "io58": brk, "io60": minute - seg[0],
            "io10507": daily, "io10508": args.week_so_far + daily, "io69": args.fortnight_so_far + daily,
            "io10510": 0,
            "io10530": max(0, 270 - continuous),
            "io10533": max(0, 540 - daily),
            "io10534": max(0, 3360 - args.week_so_far - daily),
            "io10509": max(0, 13 * 60 - minute),
            "io10528": 45 if continuous else 0,
        }
        if args.no_card:
            attrs["io52"] = 1 if kind == "drive" else 0
        else:
            attrs.update({"io195": msb, "io196": lsb, "io10518": name_hex(args.first_name), "io10519": name_hex(args.surname)})
        ts = (start + timedelta(minutes=minute)).isoformat()
        out.append({
            "position": {"deviceId": args.device_id, "deviceTime": ts, "fixTime": ts, "attributes": attrs},
            "device": {"id": args.device_id, "uniqueId": args.imei, "name": args.reg, "model": "FMC650",
                       "attributes": {"registration": args.reg}},
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8000/api/tacho-live/ingest")
    p.add_argument("--key", help="TACHO_LIVE_KEY (default: read from .env)")
    p.add_argument("--card", default="DB07190162033713")
    p.add_argument("--first-name", default="ANDREW")
    p.add_argument("--surname", default="DALBY")
    p.add_argument("--imei", default="350000000000650")
    p.add_argument("--device-id", type=int, default=990650)
    p.add_argument("--reg", default="PN19 HNR")
    p.add_argument("--minutes", type=int, default=360)
    p.add_argument("--start-minutes-ago", type=int, default=360)
    p.add_argument("--first-drive", type=int, default=260)
    p.add_argument("--week-so-far", type=int, default=1200)
    p.add_argument("--fortnight-so-far", type=int, default=2800)
    p.add_argument("--step", type=int, default=5)
    p.add_argument("--no-card", action="store_true")
    args = p.parse_args()
    key = args.key
    if not key:
        for line in open(".env", encoding="utf-8"):
            if line.startswith("TACHO_LIVE_KEY="):
                key = line.split("=", 1)[1].strip()
    sent = 0
    for record in records(args):
        req = urllib.request.Request(args.url, data=json.dumps(record).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Tacho-Live-Key": key or ""})
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        sent += 1
    print(f"sent {sent} records for {args.reg} ({'no card' if args.no_card else 'card …' + args.card[-4:]})")


if __name__ == "__main__":
    main()
