#!/usr/bin/env bash
# Run the same job as .github/workflows/ci.yml, locally.
#
#   ./scripts/check.sh --install   # first run: create/refresh the editable install
#   ./scripts/check.sh             # tests + the audit table + CLI smoke test
set -euo pipefail

cd "$(dirname "$0")/.."

pick_python() {
    for cand in "${PYTHON:-}" ".venv/bin/python" "python3" "python"; do
        [ -n "$cand" ] || continue
        { command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; } || continue
        if "$cand" -c "import numpy, pandas" >/dev/null 2>&1; then
            echo "$cand"
            return 0
        fi
    done
    return 1
}

if ! PY=$(pick_python); then
    echo "no python with numpy+pandas found." >&2
    echo "create one:  python3 -m venv .venv && .venv/bin/pip install -e '.[chart]'" >&2
    echo "or point at one:  PYTHON=/path/to/python ./scripts/check.sh" >&2
    exit 1
fi

if [ "${1:-}" = "--install" ]; then
    echo "== install =="
    "$PY" -m pip install -e ".[chart]"
fi

echo "== lint =="
if "$PY" -m ruff --version >/dev/null 2>&1; then
    "$PY" -m ruff check espero tests research   # the same line CI runs; research/ is exempt from line length by config
else
    echo "ruff not installed (pip install -e '.[dev]'); CI will run it" >&2
fi

echo
echo "== tests =="
"$PY" -m unittest discover -s tests -t . -v

echo
echo "== shape =="
"$PY" research/index.py --check        # every research file claimed; INDEX.md current
"$PY" -m espero.layers --check         # every module in a layer; the README's layout block current
"$PY" -m unittest tests.test_shape     # no state at the root; every daily step has a plan; every module a test

echo
echo "== audit table =="
"$PY" -m espero matrix

echo
echo "== cli =="
"$PY" -m espero --version
"$PY" -m espero backtest --fee-bps 60 | tail -3

echo
echo "ok"
