#!/usr/bin/env bash
# Maintainer only: publish a snapshot of the live recordings as a GitHub release, so a
# teammate (or their agent) can fetch it with ./scripts/fetch-data.sh live.
#
#   ./scripts/publish-data.sh            # tar, checksum, create release data-YYYY-MM-DD
#   ./scripts/publish-data.sh --dry-run  # build the tarball and list it, publish nothing
#
# Public market data only: Hyperliquid snapshots, order-book recordings, the forward
# klines and aggr's liquidation bars. No .env, no *.db, no account state. Needs `gh`
# logged in as an account that can write to the repo, or GH_TOKEN set to its token
# (the daily job's Monday step does that; see ESPERO_PUBLISH_AS in .env.example).
# Re-running on a day already published does nothing.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GH_REPO="${GH_REPO:-7rido/espero}"
DAY="$(date -u +%Y-%m-%d)"
TAG="data-$DAY"
OUT="${TMPDIR:-/tmp}/espero-live-data"
NAME="espero-live-data.tar.gz"
PATHS=(data/hlcollect data/book data/lows/forward data/aggr/forward data/aggr/forward5m)

cd "$REPO"
if [ "${1:-}" != "--dry-run" ] && gh release view "$TAG" --repo "$GH_REPO" >/dev/null 2>&1; then
    echo "already published today: https://github.com/$GH_REPO/releases/tag/$TAG"
    exit 0
fi
present=()
for p in "${PATHS[@]}"; do [ -d "$p" ] && present+=("$p"); done
[ ${#present[@]} -gt 0 ] || { echo "nothing to publish: none of ${PATHS[*]} exists" >&2; exit 1; }

rm -rf "$OUT" && mkdir -p "$OUT"
tar -czf "$OUT/$NAME" "${present[@]}"
(cd "$OUT" && shasum -a 256 "$NAME" > "$NAME.sha256")

{
    echo "Live recordings as of $DAY UTC (public market data; see docs/DATA.md)."
    echo
    for p in "${present[@]}"; do
        echo "- \`$p\`: $(find "$p" -type f | wc -l | tr -d ' ') files, $(du -sh "$p" | cut -f1)"
    done
    echo
    echo "sha256: \`$(cut -d' ' -f1 "$OUT/$NAME.sha256")\`"
} > "$OUT/notes.md"

cat "$OUT/notes.md"
echo "tarball: $OUT/$NAME ($(du -h "$OUT/$NAME" | cut -f1))"

if [ "${1:-}" = "--dry-run" ]; then
    echo "dry run: nothing published"
    exit 0
fi

gh release create "$TAG" "$OUT/$NAME" "$OUT/$NAME.sha256" \
    --repo "$GH_REPO" --title "Live data $DAY" --notes-file "$OUT/notes.md" --latest
echo "published: https://github.com/$GH_REPO/releases/tag/$TAG"
