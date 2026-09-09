#!/usr/bin/env bash
# Fail if this fork has ANY flespi / MQTT association. Run from the
# tacho-bridge-app/ directory (the CI guard and sync script both call it).
#
# This is what enforces "no association with flespi servers" on every change and
# on every upstream sync: the fork must talk only to the DH FleetView server over
# the WebSocket transport (src-tauri/src/websocket.rs).
set -uo pipefail

fail=0
patterns='flespi\.io|mqtt\.flespi|rumqttc|flespi-software/Tacho-Bridge-App|com\.flespi\.|git\.gurtam\.net'

# Source + build config (NOT Cargo.lock: transitive lock entries are pruned on build).
if grep -rInE "$patterns" src src-tauri/src src-tauri/Cargo.toml src-tauri/tauri.conf.json 2>/dev/null; then
  echo "::error::Found a flespi/MQTT association above. This fork must talk only to the DH FleetView server."
  fail=1
fi

# The upstream flespi MQTT transport files must stay deleted.
for f in src-tauri/src/mqtt.rs src-tauri/src/app_connect.rs; do
  if [ -f "$f" ]; then
    echo "::error::$f was reintroduced (flespi MQTT transport). Delete it and keep websocket.rs."
    fail=1
  fi
done

if [ "$fail" = "0" ]; then
  echo "OK - fork is flespi-free; it talks only to the DH FleetView server."
fi
exit $fail
