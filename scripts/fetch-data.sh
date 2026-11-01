#!/usr/bin/env bash
# Get the data that isn't in git. Public endpoints only: no key, no account.
#
#   ./scripts/fetch-data.sh live              # the maintainer's live recordings (~20 MB), from the
#                                             # latest GitHub release; never overwrites a local file
#   ./scripts/fetch-data.sh archives          # every public archive the research scripts use (~2.3 GB)
#   ./scripts/fetch-data.sh archives --no-oi  # the same without #25's open interest (~680 MB less)
#   ./scripts/fetch-data.sh status            # what is on disk
#
# Why each folder is needed: docs/DATA.md. Safe to re-run: downloads resume from the cache.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GH_REPO="${GH_REPO:-7rido/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
NAME="espero-live-data.tar.gz"
URL="https://github.com/$GH_REPO/releases/latest/download"
LIVE=(data/hlcollect data/hlbook data/book data/lows/forward data/aggr/forward data/aggr/forward5m)

cd "$REPO"

live() {
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    echo "downloading $URL/$NAME ..."
    curl -fsSL -o "$tmp/$NAME" "$URL/$NAME"
    curl -fsSL -o "$tmp/$NAME.sha256" "$URL/$NAME.sha256"
    (cd "$tmp" && shasum -a 256 -c "$NAME.sha256")
    # -k: a file that already exists here is kept, so a local recording is never overwritten
    tar -xzkf "$tmp/$NAME" -C "$REPO" 2>/dev/null || true
    echo "extracted into data/ (existing files kept)"
    # a local file that was kept may differ from the release's; that is reported, not an error
    present=()
    for p in "${LIVE[@]}"; do [ -f "$p/MANIFEST.sha256" ] && present+=("$p"); done
    if [ ${#present[@]} -gt 0 ] && [ -x "$PYTHON" ]; then
        "$PYTHON" -m espero.manifest check "${present[@]}" || echo "a file in the release is missing here" >&2
    fi
    status
}

archives() {
    skip_oi="${1:-}"
    [ -x "$PYTHON" ] || { echo "no virtualenv at $PYTHON: see the README's Quickstart" >&2; exit 1; }
    # lows first: liq2, oi, levetf and bids read its 5-minute cache instead of downloading it again
    steps=(lows liq liq2 settle levetf bids polyhour)
    [ "$skip_oi" = "--no-oi" ] || steps+=(oi)
    for s in "${steps[@]}"; do
        echo "== research/$s.py"
        "$PYTHON" "research/$s.py"
    done
    for s in markout markout_small; do
        echo "== research/$s.py fetch"
        "$PYTHON" "research/$s.py" fetch
    done
    status
}

status() {
    for p in "${LIVE[@]}" \
             data/lows data/liq data/liq2 data/oi data/settle data/levetf data/bids \
             data/markout data/markout_small data/polymarket; do
        if [ -d "$p" ]; then
            printf "  %-22s %6s  %s files\n" "$p" "$(du -sh "$p" | cut -f1)" "$(find "$p" -type f | wc -l | tr -d ' ')"
        else
            printf "  %-22s %6s\n" "$p" "-"
        fi
    done
}

case "${1:-}" in
    live) live ;;
    archives) archives "${2:-}" ;;
    status) status ;;
    *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
