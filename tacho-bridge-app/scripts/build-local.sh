#!/usr/bin/env bash
# Build the Windows installer on the DH FleetView server itself (used while
# GitHub Actions is unavailable). Everything - toolchains, caches, temp files and
# build output - stays on D:.
#
#   bash tacho-bridge-app/scripts/build-local.sh
#
# Output: src-tauri/target/release/bundle/nsis/*-setup.exe (+ .sig for the updater).
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="/d/tools/node22:/d/tools/rust/cargo/bin:$PATH"
export CARGO_HOME='D:\tools\rust\cargo' RUSTUP_HOME='D:\tools\rust\rustup'
export npm_config_cache='D:\tools\npm-cache'
mkdir -p /d/tools/tmp /d/tools/tauri-cache
export TEMP='D:\tools\tmp' TMP='D:\tools\tmp' LOCALAPPDATA='D:\tools\tauri-cache'
# Updater signature (the matching public key is in tauri.conf.json).
export TAURI_SIGNING_PRIVATE_KEY='D:\DHFleetViewData\tacho\bridge\signing\updater.key'
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=''

bash scripts/check-flespi.sh
[ -d node_modules/@quasar/app-vite ] || npm ci --no-audit --no-fund
npx tauri build --bundles nsis
ls -la src-tauri/target/release/bundle/nsis/
