#!/usr/bin/env bash
# Run the raw stream recorder (espero rawrec --loop) under launchd, so it survives closed terminal
# tabs, app restarts and logins. Public websocket data only: nothing signs or trades.
#
#   ESPERO_RAW_DIR=/path/outside/data ./scripts/install-rawrec-launchd.sh   # install and start it
#   ./scripts/install-rawrec-launchd.sh --uninstall   # stop and remove it (the recordings stay)
#   ./scripts/install-rawrec-launchd.sh --status      # running? last exit?
#   ./scripts/install-rawrec-launchd.sh --print       # render the plist to stdout, change nothing
#
# ESPERO_RAW_DIR is required and must not be under the repo's data/ (launchd's hlcollect and hlbook
# own that folder). The log goes to ~/Library/Logs/espero/rawrec.log.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.rawrec.plist.template"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.rawrec"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-}" in
    --uninstall)
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $LABEL (the recordings in ESPERO_RAW_DIR stay)"
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

RAW_DIR="${ESPERO_RAW_DIR:-}"
if [ -z "$RAW_DIR" ]; then
    echo "ESPERO_RAW_DIR is not set: the recorder writes only to a folder named there, never data/" >&2
    exit 1
fi
case "$RAW_DIR" in
    "$REPO/data"|"$REPO/data/"*)
        echo "ESPERO_RAW_DIR=$RAW_DIR is under $REPO/data: launchd's hlcollect and hlbook own that folder" >&2
        exit 1 ;;
esac

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__RAW_DIR__|$RAW_DIR|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        "$TEMPLATE"
}

if [ "${1:-}" = "--print" ]; then
    render
    exit 0
fi

if ! "$PYTHON" -c "import espero.rawrec, zstandard, websockets" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.rawrec with zstandard and websockets; pip install -e '.[raw]' first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$RAW_DIR" "$HOME/Library/LaunchAgents"
render > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
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
echo "installed $LABEL  ->  $RAW_DIR, log $LOG_DIR/rawrec.log"
echo "status:  ./scripts/install-rawrec-launchd.sh --status"
echo "follow:  tail -f $LOG_DIR/rawrec.log"
