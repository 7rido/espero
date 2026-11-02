#!/usr/bin/env bash
# Stamp a pre-registration outside the repo, before its result exists (acceptance (d) in the #61/#62 plans).
#
#   ./scripts/timestamp.sh research/PREREGISTRATION_RAWBARS.md        # writes <file>.ots beside it
#   ./scripts/timestamp.sh --verify research/PREREGISTRATION_RAWBARS.md
#   ./scripts/timestamp.sh --upgrade research/PREREGISTRATION_RAWBARS.md   # once Bitcoin has confirmed it
#
# OpenTimestamps (`pip install opentimestamps-client`, the `ots` command in .venv/bin) sends the file's
# SHA-256, never the file, to public calendars that aggregate hashes into a Bitcoin transaction. The .ots
# proof is committed with the document; `ots verify` later checks the document's hash against the chain.
# No account, no key, no fee. A proof is "pending" until the calendar's transaction confirms (hours),
# then `--upgrade` rewrites it as a complete Bitcoin attestation.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OTS="${OTS:-$REPO/.venv/bin/ots}"
[ -x "$OTS" ] || { echo "no ots at $OTS: uv pip install --python .venv/bin/python opentimestamps-client" >&2; exit 1; }
case "${1:-}" in
    --verify)  shift; for f in "$@"; do "$OTS" verify "$f.ots"; done ;;
    --upgrade) shift; for f in "$@"; do "$OTS" upgrade "$f.ots"; done ;;
    -*)        echo "usage: $0 [--verify|--upgrade] FILE..." >&2; exit 2 ;;
    *)         for f in "$@"; do
                   [ -f "$f" ] || { echo "$f: no such file" >&2; exit 1; }
                   [ -f "$f.ots" ] && { echo "$f.ots exists; a stamp is made once" >&2; exit 1; }
                   "$OTS" stamp "$f"
                   echo "stamped $f -> $f.ots ($(shasum -a 256 "$f" | cut -c1-16)…)"
               done ;;
esac
