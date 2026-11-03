#!/usr/bin/env bash
# Run the silence alarm (espero watchdog --once) every minute under launchd. It reads files and launchd's
# state and notifies; it writes only state/watchdog.json and never trades.
#
#   ESPERO_RAW_DIR=/path/to/the/tape ./scripts/install-watchdog-launchd.sh   # install and start it
#   ./scripts/install-watchdog-launchd.sh --uninstall   # stop and remove it (state/watchdog.json stays)
#   ./scripts/install-watchdog-launchd.sh --status      # loaded? last exit?
#   ./scripts/install-watchdog-launchd.sh --print       # render the plist to stdout, change nothing
#
# ESPERO_RAW_DIR is optional: without it the raw tape is not checked. The webhook, when ESPERO_WEBHOOK_URL is
# in .env, is read from the repo (WorkingDirectory). The log goes to ~/Library/Logs/espero/watchdog.log.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.watchdog.plist.template"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
RAW_DIR="${ESPERO_RAW_DIR:-}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.watchdog"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__RAW_DIR__|$RAW_DIR|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        "$TEMPLATE"
}

case "${1:-}" in
    --print)
        render
        exit 0 ;;
    --uninstall)
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $LABEL (state/watchdog.json stays)"
        exit 0 ;;
    --status)
        echo "== $LABEL"
        launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "^\s+(state|pid|last exit code|runs) =" \
            || echo "   not loaded"
        exit 0 ;;
    "") ;;
    *)
        echo "unknown option $1" >&2
        exit 2 ;;
esac

if ! "$PYTHON" -c "import espero.watchdog" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.watchdog; install the package into it first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
render > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
# bootout returns before the old job has gone; loading now can fail, or the late stop can remove the new job
for _ in $(seq 1 30); do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 1
done
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
sleep 2
if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "$LABEL did not stay loaded; run this script once more" >&2
    exit 1
fi
echo "installed $LABEL: every minute, log $LOG_DIR/watchdog.log; espero watchdog --status shows the last checks"
