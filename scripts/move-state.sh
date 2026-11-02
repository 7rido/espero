#!/usr/bin/env bash
# Move the account state out of the repo root into the state folder, once.
#
#   ./scripts/move-state.sh            # list what would move; moves nothing
#   ./scripts/move-state.sh --apply    # move it
#
# The state is every *.db with its -wal, -shm and .lock, every ledger *.csv, health.json,
# dashboard.html, KILL and paper-books/. features.db stays: it is a committed fixture.
# --apply refuses while a loop that writes one of these is loaded in launchd, or while any
# of the files is open, because a journal moved under a running process splits its book.
# Stop them first (docs/RUNBOOK.md, "Where the state lives"), move, then reinstall them.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE_DIR="${STATE_DIR:-${ESPERO_STATE_DIR:-$REPO/state}}"
LAUNCHCTL="${LAUNCHCTL:-launchctl}"
WRITERS=(com.espero.daily com.espero.carry-taker com.espero.carry-maker com.espero.hlp com.espero.hlp2 com.espero.paper)

cd "$REPO"
items=()
for f in *.db *.db-wal *.db-shm *.db.lock *.csv health.json dashboard.html KILL; do
    [ -e "$f" ] || continue
    [ "$f" = "features.db" ] && continue
    items+=("$f")
done
[ -d paper-books ] && items+=(paper-books)

if [ ${#items[@]} -eq 0 ]; then
    echo "nothing to move: the root holds no state"
    exit 0
fi

echo "from  $REPO"
echo "to    $STATE_DIR"
for f in "${items[@]}"; do echo "  $f"; done

if [ "${1:-}" != "--apply" ]; then
    echo "dry run: nothing moved. Stop the loops, then: $0 --apply"
    exit 0
fi

if command -v "$LAUNCHCTL" >/dev/null 2>&1; then
    for label in "${WRITERS[@]}"; do
        if "$LAUNCHCTL" print "gui/$(id -u)/$label" >/dev/null 2>&1; then
            echo "refusing: $label is loaded in launchd; uninstall it first (docs/RUNBOOK.md)" >&2
            exit 1
        fi
    done
fi
if command -v lsof >/dev/null 2>&1; then
    for f in "${items[@]}"; do
        if lsof -t -- "$f" >/dev/null 2>&1; then
            echo "refusing: $f is open by pid $(lsof -t -- "$f" | tr '\n' ' ')" >&2
            exit 1
        fi
    done
fi
for f in "${items[@]}"; do
    if [ -e "$STATE_DIR/$f" ]; then
        echo "refusing: $STATE_DIR/$f already exists; nothing moved" >&2
        exit 1
    fi
done

mkdir -p "$STATE_DIR"
for f in "${items[@]}"; do mv -- "$f" "$STATE_DIR/$f"; done
echo "moved ${#items[@]} items into $STATE_DIR"
echo "now reinstall the loops, which will find their books there (docs/RUNBOOK.md, \"Where the state lives\")"
