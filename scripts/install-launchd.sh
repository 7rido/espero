#!/usr/bin/env bash
# Install (or remove) the launchd agent that runs `espero daily` every morning.
#
#   ./scripts/install-launchd.sh             # install, 07:30 local time
#   HOUR=8 MINUTE=15 ./scripts/install-launchd.sh
#   ./scripts/install-launchd.sh --uninstall
#   ./scripts/install-launchd.sh --run-now   # install and kick one run immediately
#
# State (tsmom.db, xs.db, dashboard.html, health.json) lives in state/ under the repo unless
# STATE_DIR or ESPERO_STATE_DIR says otherwise. Logs go to ~/Library/Logs/espero/.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.espero.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$REPO/deploy/launchd/$LABEL.plist.template"
STATE_DIR="${STATE_DIR:-${ESPERO_STATE_DIR:-$REPO/state}}"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
HOUR="${HOUR:-7}"
MINUTE="${MINUTE:-30}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"

uninstall() {
    "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
}

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    exit 0
fi

if [ ! -x "$PYTHON" ]; then
    echo "no python at $PYTHON" >&2
    echo "create one:  uv venv .venv && uv pip install -e '.[chart,tui,dev]' --python .venv/bin/python" >&2
    echo "or point at one:  PYTHON=/path/to/python $0" >&2
    exit 1
fi
if ! "$PYTHON" -c "import espero" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero; install the package into it first" >&2
    exit 1
fi

# a book left in the root would be abandoned for a fresh one; move it first
for f in tsmom.db xs.db mf.db; do
    if [ -e "$REPO/$f" ] && [ ! -e "$STATE_DIR/$f" ]; then
        echo "$REPO/$f exists but $STATE_DIR/$f does not: run ./scripts/move-state.sh first" >&2
        exit 1
    fi
done
mkdir -p "$LOG_DIR" "$STATE_DIR" "$HOME/Library/LaunchAgents"

sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__REPO__|$REPO|g" \
    -e "s|__STATE_DIR__|$STATE_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    -e "s|__HOUR__|$HOUR|g" \
    -e "s|__MINUTE__|$MINUTE|g" \
    "$TEMPLATE" > "$PLIST"
plutil -lint "$PLIST" >/dev/null

# preflight with the exact interpreter launchd will use
"$PYTHON" -m espero daily --dry-run --state-dir "$STATE_DIR" >/dev/null

"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" 2>/dev/null || true
"$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST"
"$LAUNCHCTL" enable "$DOMAIN/$LABEL"

echo "installed $LABEL"
echo "  runs     daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE") local time"
echo "  python   $PYTHON"
echo "  state    $STATE_DIR"
echo "  logs     $LOG_DIR/daily.log"
echo "  status   launchctl print $DOMAIN/$LABEL | grep -E 'state|last exit'"

if [ "${1:-}" = "--run-now" ]; then
    "$LAUNCHCTL" kickstart "$DOMAIN/$LABEL"
    echo "kicked one run; tail -f $LOG_DIR/daily.log"
fi
