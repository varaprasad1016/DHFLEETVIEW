#!/usr/bin/env bash
# Fails if any DH FleetView customisation ("overlay") over upstream Traccar has
# gone missing — so a careless edit, or a cherry-pick from upstream, can never
# silently revert our CNMS video, tachograph, compliance, timezone or map work.
# Run from the repository root.
set -uo pipefail

fail=0
need_file() { if [ ! -f "$1" ]; then echo "::error::Missing overlay file: $1"; fail=1; fi; }
need_grep() { if ! grep -rqs -- "$2" "$1"; then echo "::error::Missing overlay marker in $1: $2"; fail=1; fi; }

# --- Backend: CNMS/CMSV9 video + tachograph integration ---
need_file src/main/java/org/traccar/media/Cmsv9Manager.java
need_file src/main/java/org/traccar/schedule/TaskCnmsSync.java
need_file src/main/java/org/traccar/api/resource/Cmsv9Resource.java
need_file src/main/java/org/traccar/api/resource/TachographResource.java

# --- Frontend: video page + London time + Google-maps default ---
need_file traccar-web/src/other/Cmsv9VideoPage.jsx
need_grep traccar-web/src/common/util/formatter.js "Europe/London"
need_grep traccar-web/src/map/core/MapView.jsx "googleRoad"

# --- Mobile app: our WebView shell downloads + server default ---
need_file traccar-manager/lib/main_screen.dart

if [ "$fail" = "0" ]; then
  echo "OK - DH FleetView overlay is intact over upstream Traccar."
fi
exit $fail
