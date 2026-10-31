#!/usr/bin/env bash
# Run the order-book recorder (espero hlbook --loop) under launchd, so it survives
# closed terminal tabs, app restarts and logins. Public data only: nothing signs or trades.
#
#   ./scripts/install-hlbook-launchd.sh               # install and start it
#   ./scripts/install-hlbook-launchd.sh --uninstall   # stop and remove it (the data stays)
#   ./scripts/install-hlbook-launchd.sh --status      # running? last exit?
#   ./scripts/install-hlbook-launchd.sh --print       # render the plist to stdout, change nothing
#
# Data goes to data/hlbook/ in the repo unless HLBOOK_DATA is set; the log to
# ~/Library/Logs/espero/hlbook.log.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.hlbook.plist.template"
DATA="${HLBOOK_DATA:-$REPO/data/hlbook}"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.hlbook"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__DATA__|$DATA|g" \
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
        echo "removed $LABEL (the data in $DATA stays)"
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

if ! "$PYTHON" -c "import espero.hlbook" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.hlbook; install the package into it first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$DATA" "$HOME/Library/LaunchAgents"
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
echo "installed $LABEL  ->  $DATA, log $LOG_DIR/hlbook.log"
echo "status:  ./scripts/install-hlbook-launchd.sh --status"
echo "follow:  tail -f $LOG_DIR/hlbook.log"
