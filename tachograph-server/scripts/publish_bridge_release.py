"""Publish a built Tacho Bridge App installer to the download button and the in-app updater.

    .venv\\Scripts\\python -m scripts.publish_bridge_release <nsis bundle dir> [--channel stable|beta] [--notes "..."]

Copies ``*-setup.exe`` and its ``.sig`` (from ``tauri build`` with the updater key) to
``BRIDGE_RELEASE_DIR/<version>/`` on D: and rewrites ``latest.json`` (stable: the
Tachograph page download button + apps on the stable channel) and/or
``latest-beta.json`` (apps that opted into pre-releases). Stable also updates beta.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

SETUP = re.compile(r"^(?P<product>.+)_(?P<version>\d+\.\d+\.\d+[0-9A-Za-z.\-]*)_x64-setup\.exe$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle_dir")
    ap.add_argument("--channel", choices=["stable", "beta"], default="stable")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    bundle = Path(args.bundle_dir)
    setups = sorted((p for p in bundle.glob("*-setup.exe") if SETUP.match(p.name)), key=lambda p: p.stat().st_mtime)
    if not setups:
        print(f"no *_x64-setup.exe in {bundle}", file=sys.stderr)
        return 1
    setup = setups[-1]
    sig = setup.with_name(setup.name + ".sig")
    if not sig.is_file():
        print(f"missing updater signature {sig.name} (build with TAURI_SIGNING_PRIVATE_KEY set)", file=sys.stderr)
        return 1
    version = SETUP.match(setup.name)["version"]
    # A plain file name for downloads and URLs: DH-FleetView-Tacho-Bridge_<version>_x64-setup.exe
    public_name = f"DH-FleetView-Tacho-Bridge_{version}_x64-setup.exe"

    root = Path(settings.bridge_release_dir)
    target = root / version
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(setup, target / public_name)
    shutil.copy2(sig, target / (public_name + ".sig"))

    url = f"{settings.bridge_public_url}/bridge/files/{version}/{public_name}"
    platform = {"signature": sig.read_text(encoding="utf-8").strip(), "url": url}
    manifest = {
        "version": version,
        "notes": args.notes or f"DH FleetView Tacho Bridge {version}",
        "pub_date": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "platforms": {"windows-x86_64": platform, "windows-x86_64-nsis": platform},
        "installer": public_name,
    }
    names = ["latest-beta.json"] if args.channel == "beta" else ["latest.json", "latest-beta.json"]
    for name in names:
        tmp = root / (name + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp.replace(root / name)
    print(f"published {version} ({args.channel}) -> {target / public_name}")
    print(f"manifests: {', '.join(names)}; download: {settings.bridge_public_url}/bridge/download")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
