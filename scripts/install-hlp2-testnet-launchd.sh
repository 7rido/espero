#!/usr/bin/env bash
# Run #59's testnet executor (espero hlp-testnet --loop) under launchd. It places real orders on
# Hyperliquid's TESTNET only, from #59's paper journal; mainnet is not reachable from it. Needs
# HL_NETWORK=testnet, ESPERO_ALLOW_HL_TESTNET=1 and the testnet key in .env. To stop new entries and
# sell everything open, create state/hlp2-testnet.stop.
#
#   ./scripts/install-hlp2-testnet-launchd.sh               # install and start it
#   ./scripts/install-hlp2-testnet-launchd.sh --uninstall   # stop and remove it (the journal stays)
#   ./scripts/install-hlp2-testnet-launchd.sh --status      # running? last exit?
#   ./scripts/install-hlp2-testnet-launchd.sh --print       # render the plist to stdout, change nothing
#
# It reads hlp2-book.db and writes hlp2-testnet.db, both in state/ under the repo (STATE_DIR or
# ESPERO_STATE_DIR to change that); the log ~/Library/Logs/espero/hlp2-testnet.log.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
TEMPLATE="$REPO/deploy/launchd/com.espero.hlp2-testnet.plist.template"
STATE_DIR="${STATE_DIR:-${ESPERO_STATE_DIR:-$REPO/state}}"
BOOK="$STATE_DIR/hlp2-book.db"
STATE="$STATE_DIR/hlp2-testnet.db"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"
LABEL="com.espero.hlp2-testnet"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__STATE__|$STATE|g" \
        -e "s|__BOOK__|$BOOK|g" \
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

if ! "$PYTHON" -c "import espero.hlp_testnet" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.hlp_testnet; install the package into it first" >&2
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
echo "installed $LABEL  ->  $STATE, log $LOG_DIR/hlp2-testnet.log"
echo "status:  ./scripts/install-hlp2-testnet-launchd.sh --status"
echo "follow:  tail -f $LOG_DIR/hlp2-testnet.log"
