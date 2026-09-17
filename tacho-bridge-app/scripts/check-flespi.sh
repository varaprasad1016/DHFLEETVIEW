#!/usr/bin/env bash
# Fail if this fork could talk to flespi. Run from the tacho-bridge-app/
# directory (the CI guard, the sync workflow and build-local.sh all call it).
#
# Since 0.8 the fork keeps upstream's MQTT protocol unchanged (it carries the
# card sessions and the Lisle card rack) and talks to the DH FleetView server's
# bridge endpoint instead of flespi. What must never come back is any flespi
# address, update source, bundle identity or wording.
set -uo pipefail

fail=0
patterns='flespi|gurtam'

# Source + build config (LICENSE keeps upstream's MIT copyright notice by law;
# CHANGELOG.md and communication_protocol.md are upstream history/docs).
if grep -rIniE "$patterns" src src-tauri/src src-tauri/Cargo.toml src-tauri/tauri.conf.json package.json index.html public 2>/dev/null; then
  echo "::error::Found a flespi association above. This fork must talk only to the DH FleetView server."
  fail=1
fi

# The server, update feed and bundle identity must be ours.
grep -q '"identifier": "com.dhfleetview.tachobridge"' src-tauri/tauri.conf.json || { echo "::error::bundle identifier is not com.dhfleetview.tachobridge"; fail=1; }
grep -q 'https://dhfleetview.co.uk/tacho/bridge/latest.json' src-tauri/tauri.conf.json || { echo "::error::updater endpoint is not the DH FleetView server"; fail=1; }
grep -q 'DEFAULT_SERVER_HOST: &str = "dhfleetview.co.uk:8883"' src-tauri/src/config.rs || { echo "::error::default server is not dhfleetview.co.uk:8883"; fail=1; }
grep -q 'MQTT_TLS_PORT' src-tauri/src/mqtt.rs || { echo "::error::TLS for the secure port was dropped from mqtt.rs"; fail=1; }

if [ "$fail" = "0" ]; then
  echo "OK - fork is flespi-free; it talks only to the DH FleetView server."
fi
exit $fail
