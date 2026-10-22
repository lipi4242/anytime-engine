"""The admin backend: the cases API of mentat-admin (its docs/plugins.md),
header `X-Mentat-Token`, read-only:

    GET /api/cases/due?until=YYYY-MM-DD  every open occurrence due by `until`,
        one item per date {case_id, title, status, description, next_action,
        recurrence, brain_ref, due_at, closable} — the admin computes
        the series, so the pack does not recompute it from a copy
    GET /api/cases?status=waiting        the waiting cases (also the undated ones)

Where: `.mentat/local.json` `admin.url` + `admin.token_env` (written by the
admin's `npm run connect`); the token itself from that environment variable,
or from the repo's `.env` (0600, gitignored) when the process did not load it.
Every failure raises CasesUnavailable; nothing is guessed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from anytime_engine import mentat_manifest as mm

from .source import CasesUnavailable

TIMEOUT_S = 10


def _dotenv(path: Path, key: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        k, sep, v = line.strip().removeprefix("export ").partition("=")
        if sep and k.strip() == key:
            return v.strip().strip("\"'") or None
    return None


def _token(root: Path) -> tuple[str, str]:
    admin = (mm.local(root) or {}).get("admin") or {}
    url, env = admin.get("url"), admin.get("token_env")
    if not url or not env:
        raise CasesUnavailable("cases.backend is admin, but the admin is not connected "
                               "(.mentat/local.json admin.url + token_env)")
    token = os.environ.get(env) or _dotenv(root / ".env", env)
    if not token:
        raise CasesUnavailable(f"admin token missing: ${env} is not set (env or .env)")
    return str(url).rstrip("/"), token


def _get(url: str, token: str, path: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(url + path, headers={"X-Mentat-Token": token,
                                                      "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            rows = json.load(resp)
    except urllib.error.HTTPError as e:
        raise CasesUnavailable(f"admin refused the request: HTTP {e.code} on {path}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise CasesUnavailable(f"admin unreachable: {e}") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise CasesUnavailable(f"admin answered {path} with something other than a list")
    return rows


def fetch(root: Path, until: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(open occurrences due by `until`, waiting cases) — both from the API."""
    url, token = _token(root)
    items = _get(url, token, "/api/cases/due?until=" + until.isoformat())
    waiting = _get(url, token, "/api/cases?status=waiting")
    return items, waiting
