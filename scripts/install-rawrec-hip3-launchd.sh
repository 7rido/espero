#!/usr/bin/env bash
# Run the second raw recorder (espero hip3rec --loop) under launchd: trade.xyz's books and trades, for #74.
# One public websocket feed: nothing signs or trades. The first recorder and its tape are not touched.
#
#   ESPERO_RAW_DIR_HIP3=/its/own/folder ./scripts/install-rawrec-hip3-launchd.sh   # install and start it
#   ./scripts/install-rawrec-hip3-launchd.sh --uninstall   # stop and remove it (the recordings stay)
#   ./scripts/install-rawrec-hip3-launchd.sh --status      # running? last exit?
#   ./scripts/install-rawrec-hip3-launchd.sh --print       # render the plist to stdout, change nothing
#
# ESPERO_RAW_DIR_HIP3 is required. It must not be under the repo's data/, and must not be, hold or sit inside
# the first recorder's folder (ESPERO_RAW_DIR, passed on when set so the recorder can check it too). The log
# goes to ~/Library/Logs/espero/rawrec-hip3.log.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.rawrec-hip3.plist.template"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
LABEL="com.espero.rawrec-hip3"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-}" in
    --uninstall)
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$PLIST"
        echo "removed $LABEL (the recordings in ESPERO_RAW_DIR_HIP3 stay)"
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

RAW_HIP3="${ESPERO_RAW_DIR_HIP3:-}"
RAW_FIRST="${ESPERO_RAW_DIR:-}"
if [ -z "$RAW_HIP3" ]; then
    echo "ESPERO_RAW_DIR_HIP3 is not set: this recorder writes only to a folder of its own, named there" >&2
    exit 1
fi
case "$RAW_HIP3" in
    "$REPO/data"|"$REPO/data/"*)
        echo "ESPERO_RAW_DIR_HIP3=$RAW_HIP3 is under $REPO/data: launchd's hlcollect and hlbook own that folder" >&2
        exit 1 ;;
esac
if [ -n "$RAW_FIRST" ]; then
    case "$RAW_HIP3/" in "$RAW_FIRST/"*)
        echo "ESPERO_RAW_DIR_HIP3=$RAW_HIP3 is the first recorder's folder or inside it ($RAW_FIRST)" >&2
        exit 1 ;;
    esac
    case "$RAW_FIRST/" in "$RAW_HIP3/"*)
        echo "ESPERO_RAW_DIR_HIP3=$RAW_HIP3 holds the first recorder's folder ($RAW_FIRST)" >&2
        exit 1 ;;
    esac
fi

render() {
    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__RAW_DIR_HIP3__|$RAW_HIP3|g" \
        -e "s|__RAW_DIR__|$RAW_FIRST|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        "$TEMPLATE"
}

if [ "${1:-}" = "--print" ]; then
    render
    exit 0
fi

if ! "$PYTHON" -c "import espero.hip3rec, zstandard, websockets" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero.hip3rec with zstandard and websockets; pip install -e '.[raw]' first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$RAW_HIP3" "$HOME/Library/LaunchAgents"
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
echo "installed $LABEL  ->  $RAW_HIP3, log $LOG_DIR/rawrec-hip3.log"
echo "status:  ./scripts/install-rawrec-hip3-launchd.sh --status"
