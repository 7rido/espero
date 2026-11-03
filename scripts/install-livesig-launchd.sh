#!/usr/bin/env bash
# Run #71's streaming engine (espero livesig --loop) under launchd. It reads the raw tape the recorder writes
# (ESPERO_RAW_DIR) and appends events to state/livesig_events.csv; it opens no connection and never trades.
#
#   ESPERO_RAW_DIR=/path/to/the/tape ./scripts/install-livesig-launchd.sh   # install and start it
#   ./scripts/install-livesig-launchd.sh --uninstall   # stop and remove it (the events file stays)
#   ./scripts/install-livesig-launchd.sh --status      # running? last exit?
#   ./scripts/install-livesig-launchd.sh --print       # render the plist to stdout, change nothing
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.livesig.plist.template"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
RAW_DIR="${ESPERO_RAW_DIR:-}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.livesig"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__RAW_DIR__|$RAW_DIR|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        "$TEMPLATE"
}

case "${1:-}" in
    --uninstall)
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $LABEL (state/livesig_events.csv stays)"
        exit 0 ;;
    --status)
        echo "== $LABEL"
        launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "^\s+(state|pid|last exit code|runs) =" \
            || echo "   not loaded"
        exit 0 ;;
    --print|"") ;;
    *)
        echo "unknown option $1" >&2
        exit 2 ;;
esac

if [ -z "$RAW_DIR" ]; then
    echo "ESPERO_RAW_DIR is not set: the engine reads the tape the recorder writes there" >&2
    exit 1
fi
if [ "${1:-}" = "--print" ]; then
    render
    exit 0
fi
if ! "$PYTHON" -c "import espero.livesig, zstandard" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.livesig with zstandard; pip install -e '.[raw]' first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
render > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
echo "installed $LABEL: events in state/livesig_events.csv, log $LOG_DIR/livesig.log"
