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
# the recordings scripts/publish-data.sh releases (its PATHS); tests/test_manifest.py holds the two lists equal
LIVE=(data/hlcollect data/deribit data/hlbook data/book data/lows/forward data/aggr/forward data/aggr/forward5m)

cd "$REPO"

live() {
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    echo "downloading $URL/$NAME ..."
    curl -fsSL -o "$tmp/$NAME" "$URL/$NAME"
    curl -fsSL -o "$tmp/$NAME.sha256" "$URL/$NAME.sha256"
    (cd "$tmp" && shasum -a 256 -c "$NAME.sha256")
    # the checksum proves the download, not the publisher: nothing from a release may land outside the
    # live folders (a .pth in .venv/ would run on the next python start). Refused before anything is extracted.
    check_archive "$tmp/$NAME"
    # -k: a file that already exists here is kept, so a local recording is never overwritten; bsdtar reports each
    # kept file as an error, which is the one error hidden here
    tar -xzkf "$tmp/$NAME" -C "$REPO" 2>&1 | grep -v "Already exists" || true
    echo "extracted into data/ (existing files kept)"
    # a local file that was kept may differ from the release's; that is reported, not an error
    present=()
    for p in "${LIVE[@]}"; do [ -f "$p/MANIFEST.sha256" ] && present+=("$p"); done
    if [ ${#present[@]} -eq 0 ]; then
        echo "manifest check skipped: the release carries no MANIFEST.sha256"
    elif [ ! -x "$PYTHON" ]; then
        echo "manifest check skipped: no virtualenv at $PYTHON (see the README's Quickstart)"
    else
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

check_archive() {
    # every member must sit under one of the live folders; anything else (a path with .., a dotfile at the
    # root, a file under .venv/ or espero/) refuses the whole archive
    local members bad alt
    members="$(tar -tzf "$1")" || { echo "cannot list $1" >&2; return 1; }
    alt="$(printf '%s|' "${LIVE[@]}")"
    # a live folder and what is under it, or one of the folders above it (data/, data/lows/, data/aggr/)
    bad="$(printf '%s\n' "$members" | grep -Ev "^((${alt%|})(/|\$)|data/(lows/|aggr/)?\$)" || true)"
    if [ -n "$bad" ]; then
        echo "refusing $1: it holds files outside the live folders:" >&2
        printf '  %s\n' $bad >&2
        return 1
    fi
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
    check-archive) check_archive "${2:?a tarball}" ;;
    *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
