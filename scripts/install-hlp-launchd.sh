#!/usr/bin/env bash
# Run #58's paper book (espero hlp --loop) under launchd, so it survives closed terminal tabs,
# app restarts and logins. Simulated fills only: nothing signs or trades.
#
#   ./scripts/install-hlp-launchd.sh               # install and start it
#   ./scripts/install-hlp-launchd.sh --uninstall   # stop and remove it (the journal stays)
#   ./scripts/install-hlp-launchd.sh --status      # running? last exit?
#   ./scripts/install-hlp-launchd.sh --print       # render the plist to stdout, change nothing
#
# The journal is hlp-book.db in state/ under the repo (STATE_DIR or ESPERO_STATE_DIR to change
# that); the log ~/Library/Logs/espero/hlp.log.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
TEMPLATE="$REPO/deploy/launchd/com.espero.hlp.plist.template"
STATE_DIR="${STATE_DIR:-${ESPERO_STATE_DIR:-$REPO/state}}"
STATE="$STATE_DIR/hlp-book.db"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"
LABEL="com.espero.hlp"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__STATE__|$STATE|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        "$TEMPLATE"
}

case "${1:-}" in
    --print)
        render
        exit 0 ;;
    --uninstall)
        "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $LABEL (the journal $STATE stays)"
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

if ! "$PYTHON" -c "import espero.hlpbook" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.hlpbook; install the package into it first" >&2
    exit 1
fi
# a journal left in the root would be abandoned for a fresh one; move it first
if [ -e "$REPO/$(basename "$STATE")" ] && [ ! -e "$STATE" ]; then
    echo "$REPO/$(basename "$STATE") exists but $STATE does not: run ./scripts/move-state.sh first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$STATE_DIR" "$HOME/Library/LaunchAgents"
render > "$PLIST"
plutil -lint "$PLIST" >/dev/null
"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" 2>/dev/null || true
"$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST"
"$LAUNCHCTL" enable "$DOMAIN/$LABEL"
echo "installed $LABEL  ->  $STATE, log $LOG_DIR/hlp.log"
echo "status:  ./scripts/install-hlp-launchd.sh --status"
echo "follow:  tail -f $LOG_DIR/hlp.log"
