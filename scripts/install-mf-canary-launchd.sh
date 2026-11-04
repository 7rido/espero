#!/usr/bin/env bash
# Run rule 8's plumbing canary (espero mf-canary --loop) under launchd: research/CANARY_MF.md. It proposes each entry
# for your yes (espero approve, or the home screen) and places approved orders on Hyperliquid's TESTNET only. Needs
# HL_NETWORK=testnet, ESPERO_ALLOW_HL_TESTNET=1, the testnet key and ESPERO_OPERATOR_TOTP in .env. To stop new
# entries and sell what the canary holds, create state/mf-canary.stop.
#
#   ./scripts/install-mf-canary-launchd.sh               # install and start it
#   ./scripts/install-mf-canary-launchd.sh --uninstall   # stop and remove it (the journal stays)
#   ./scripts/install-mf-canary-launchd.sh --status      # running? last exit?
#   ./scripts/install-mf-canary-launchd.sh --print       # render the plist to stdout, change nothing
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.mf-canary.plist.template"
STATE_DIR="${STATE_DIR:-${ESPERO_STATE_DIR:-$REPO/state}}"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.mf-canary"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__STATE_DIR__|$STATE_DIR|g" \
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
        echo "removed $LABEL (the journal $STATE_DIR/mf-canary.db stays)"
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

if ! "$PYTHON" -c "import espero.mf_canary" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.mf_canary; install the package into it first" >&2
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
echo "installed $LABEL: journal $STATE_DIR/mf-canary.db, log $LOG_DIR/mf-canary.log"
