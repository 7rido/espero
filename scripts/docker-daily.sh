#!/usr/bin/env bash
# The daily job's scheduler inside the container: run `espero daily` once per UTC day, at or after
# ESPERO_DAILY_UTC (default 07:30). It checks every 10 minutes, so a day missed while the machine
# slept or the container was down runs as soon as it is back, like launchd's catch-up.
set -euo pipefail

STATE="${STATE_DIR:-/app/state}"
AT="${ESPERO_DAILY_UTC:-07:30}"
MARK="$STATE/.last-daily-utc"
mkdir -p "$STATE"

while true; do
    today="$(date -u +%Y-%m-%d)"
    now="$(date -u +%H:%M)"
    last="$(cat "$MARK" 2>/dev/null || true)"
    if [ "$last" != "$today" ] && [[ ! "$now" < "$AT" ]]; then
        echo "$(date -u +%FT%TZ) daily run for $today"
        # a failed step still counts as the day's run: health.json records it, and the job
        # retries nothing on its own, the same as under launchd
        espero daily --state-dir "$STATE" || echo "daily run exited $?"
        echo "$today" > "$MARK"
    fi
    sleep 600
done
