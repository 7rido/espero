"""Reading `.env`, with no dependency.

The name is from the Coinbase order adapter this module held until 2026-11-01. That path was removed:
it had never been reconciled against a venue, it served strategies that failed their tests, and the
repo's rule is that no mainnet order is placed from here. `espero/hl_exchange.py` is now the only code
that signs anything, and only on the testnet. `load_env` stays under this name because two frozen
research scripts, #40's `testnet_check.py` and #42's `rehearsal.py`, import it from here.
"""
from __future__ import annotations

import os
import re
import sys

# upper case only, like every key in .env.example: a stray base64 line ending in
# "=" padding is mixed case, so it can never become a variable named after key material
_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def parse_env(text: str) -> tuple[dict, list]:
    """Parse .env text. Returns (values, warnings); warnings never quote a value.

    Accepts `KEY=value`, `export KEY=value`, single or double quotes (a quoted
    value may span lines, for a PEM), an unquoted PEM from `-----BEGIN` to
    `-----END`, and `#` comments, including after an unquoted value. Keys are
    upper case. A line that is not `KEY=value` is skipped with a warning naming
    only its number, so a stray secret line can never become a variable."""
    values: dict = {}
    warnings: list = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        n, line = i + 1, lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, eq, value = line.partition("=")
        key = key.strip()
        if not eq or not _KEY.match(key):
            warnings.append(f".env line {n}: not KEY=value, ignored")
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            q, body = value[0], value[1:]
            while q not in body and i < len(lines):
                body += "\n" + lines[i].rstrip("\r")
                i += 1
            if q not in body:
                warnings.append(f".env line {n}: {key} has an unclosed quote, ignored")
                continue
            value = body[:body.index(q)]
            if "\n" in value and not value.startswith("-----BEGIN"):
                warnings.append(f".env line {n}: {key} spans several lines; check its closing quote")
        elif value.startswith("-----BEGIN") and "-----END" not in value:
            parts = [value]
            while i < len(lines) and "-----END" not in parts[-1]:
                parts.append(lines[i].strip())
                i += 1
            value = "\n".join(parts)
            warnings.append(f".env line {n}: {key} is an unquoted multi-line value; quote it")
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[key] = value
    return values, warnings


def load_env(path: str = ".env") -> None:
    """Load .env into the environment. Existing variables win. A relative path is
    taken from the current directory."""
    p = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as fh:
        values, warnings = parse_env(fh.read())
    for key, value in values.items():
        os.environ.setdefault(key, value)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
