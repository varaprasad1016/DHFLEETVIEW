#!/usr/bin/env bash
# Pull upstream Tacho Bridge App updates into this fork's tacho-bridge-app/ subtree,
# keeping OUR WebSocket transport + DH FleetView server config and NO flespi.
#
# Run from the REPOSITORY ROOT, on the `tacho-bridge-app` branch, with a clean
# working tree:
#     bash tacho-bridge-app/scripts/sync-upstream.sh [upstream-branch]
#
# Upstream is the flespi app, so a sync brings their code in; you then resolve
# conflicts in OUR favour for the transport/config and the guard confirms nothing
# flespi shipped. Review every sync — this is intentionally not fully automatic.
set -euo pipefail

UPSTREAM_URL="https://github.com/flespi-software/Tacho-Bridge-App.git"
BRANCH="${1:-master}"
PREFIX="tacho-bridge-app"

if [ ! -d "$PREFIX" ]; then
  echo "Run this from the repository root (where $PREFIX/ lives)." >&2
  exit 1
fi

git remote get-url upstream-tba >/dev/null 2>&1 || git remote add upstream-tba "$UPSTREAM_URL"
git fetch upstream-tba "$BRANCH"

echo ">> Merging upstream-tba/$BRANCH into $PREFIX/ (git subtree)..."
echo "   (First sync of a vendored folder can be conflict-heavy — that is normal.)"
git subtree pull --prefix="$PREFIX" upstream-tba "$BRANCH" \
  -m "Merge upstream Tacho Bridge ($BRANCH) into fork"

echo
echo ">> Merge complete. Before building:"
echo "   1) Resolve conflicts in OUR favour: keep src-tauri/src/websocket.rs and the"
echo "      server config; DO NOT bring back MQTT (mqtt.rs / app_connect.rs / rumqttc)."
echo "   2) Verify nothing flespi slipped in:"
echo "        ( cd $PREFIX && bash scripts/check-flespi.sh )"
echo "   3) Bump the version in $PREFIX/src-tauri/Cargo.toml + tauri.conf.json."
echo "   4) Cut a build + deploy by pushing a tag:  git tag tba-vX.Y.Z && git push origin tba-vX.Y.Z"
