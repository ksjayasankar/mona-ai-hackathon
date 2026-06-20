"""AppsScriptSink — pushes roster updates to a Google Apps Script Web App webhook.

The simplest 'real Google Sheets' path: no Cloud project, no service account, no JSON key.
You paste docs/google_apps_script_roster.gs into the sheet's Apps Script editor, deploy it as
a Web App, and drop the URL (+ a shared secret) in .env. The script runs as the sheet owner,
so it already has write access. We just HTTP-POST the fill; the script flips the cell."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from services.roster_sink import SyncResult

log = logging.getLogger("roster_sink")


def _post(url: str, payload: dict) -> dict:
    import httpx
    # Apps Script web apps 302-redirect to the real response host, so follow redirects.
    r = httpx.post(url, json=payload, timeout=20, follow_redirects=True)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {}


class AppsScriptSink:
    def __init__(self, url: str | None = None, secret: str | None = None, worksheet: str | None = None):
        self.url = url or os.environ["GOOGLE_APPS_SCRIPT_URL"]
        self.secret = secret if secret is not None else os.getenv("GOOGLE_APPS_SCRIPT_SECRET", "")
        self.worksheet = worksheet or os.getenv("GOOGLE_SHEETS_WORKSHEET", "Roster")

    def push_roster(self, rows: list[dict], day_cols: list[str]) -> SyncResult:
        header = ["employee_id", "name", "role", "department", *day_cols]
        matrix = [header] + [[r.get("employee_id"), r.get("name"), r.get("role"),
                              r.get("department"), *[r.get(c, "") for c in day_cols]] for r in rows]
        resp = _post(self.url, {"action": "push", "secret": self.secret,
                                "worksheet": self.worksheet, "rows": matrix})
        return SyncResult("google_sheets", bool(resp.get("ok", True)),
                          resp.get("url", self.url), resp.get("error"))

    def record_fill(self, *, employee_id: str, name: str, day_label: str,
                    code: str, when: datetime) -> SyncResult:
        resp = _post(self.url, {"action": "fill", "secret": self.secret, "worksheet": self.worksheet,
                                "employee_id": employee_id, "name": name, "day_label": day_label,
                                "code": code, "when": when.isoformat(timespec="minutes")})
        return SyncResult("google_sheets", bool(resp.get("ok", True)),
                          resp.get("url", self.url), resp.get("error"))
