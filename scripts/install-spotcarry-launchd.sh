#!/usr/bin/env bash
# Run the #83 spot carry paper book (espero spotcarry --once) every hour under launchd: funding carry on BTC and
# ETH, both legs on Hyperliquid, paper only. It reads public books and funding, paced, and writes only
# state/spotcarry.db, state/spotcarry.json and state/spotcarry/; nothing signs or trades.
#
#   ./scripts/install-spotcarry-launchd.sh               # install and start it
#   ./scripts/install-spotcarry-launchd.sh --uninstall   # stop and remove it (state/spotcarry.db stays)
#   ./scripts/install-spotcarry-launchd.sh --status      # loaded? last exit?
#   ./scripts/install-spotcarry-launchd.sh --print       # render the plist to stdout, change nothing
#
# The log goes to ~/Library/Logs/espero/spotcarry.log.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.spotcarry.plist.template"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.spotcarry"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
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
        echo "removed $LABEL (state/spotcarry.db stays)"
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

if ! "$PYTHON" -c "import espero.spotcarry" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.spotcarry; install the package into it first" >&2
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
echo "installed $LABEL: every hour at minute 33, log $LOG_DIR/spotcarry.log; espero spotcarry shows the book"
