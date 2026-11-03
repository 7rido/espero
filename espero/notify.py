"""Tell a human. Two channels, both optional, neither a dependency.

* macOS Notification Center via `osascript` (silently skipped elsewhere)
* a webhook (Slack/Discord-style `{"text": ...}` POST) when ESPERO_WEBHOOK_URL
  is set

A notification that fails must never fail the run that sent it.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

log = logging.getLogger(__name__)


def macos(title: str, message: str) -> bool:
    if sys.platform != "darwin":
        return False
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("macOS notification failed: %s", exc)
        return False


def webhook(title: str, message: str, url: str = "") -> bool:
    url = url or os.environ.get("ESPERO_WEBHOOK_URL", "")
    if not url:
        return False
    from .data import FetchError, http_get
    body = json.dumps({"text": f"*{title}*\n{message}"}).encode()
    try:
        # one attempt: a POST that timed out may still have been delivered, and a
        # retry would send the alert twice
        http_get(url, headers={"Content-Type": "application/json", "User-Agent": "espero/0.2"},
                 data=body, retries=1)
        return True
    except (FetchError, ValueError) as exc:          # ValueError: urllib refuses a malformed URL before any request
        log.warning("webhook failed: %s", str(exc).replace(url, redact(url)))
        return False


def redact(url: str) -> str:
    """A webhook URL is a bearer secret: keep scheme and host, hide the rest."""
    scheme, _, rest = url.partition("://")
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/…" if rest else "…"


def notify(title: str, message: str) -> None:
    """Best effort on every channel that is configured."""
    log.info("notify: %s -- %s", title, message)
    macos(title, message)
    webhook(title, message)
