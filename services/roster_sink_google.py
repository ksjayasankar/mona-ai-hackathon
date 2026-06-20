"""GoogleSheetsSink — flips the roster cell in a live Google Sheet via gspread.

Lazy: gspread is imported inside the client factory so this module imports cleanly even if
gspread isn't installed. Auth is service-account only (GOOGLE_SHEETS_CREDENTIALS_JSON)."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from services.roster_sink import SyncResult

log = logging.getLogger("roster_sink")


def _open_spreadsheet(sheet_id: str, creds_path: str):
    import gspread  # imported lazily; only needed when Google sync is active
    gc = gspread.service_account(filename=creds_path)
    return gc.open_by_key(sheet_id)


class GoogleSheetsSink:
    def __init__(self, sheet_id: str | None = None, creds_path: str | None = None,
                 worksheet: str | None = None):
        self.sheet_id = sheet_id or os.environ["GOOGLE_SHEETS_ID"]
        self.creds_path = creds_path or os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]
        self.worksheet = worksheet or os.getenv("GOOGLE_SHEETS_WORKSHEET", "Roster")

    def _ws(self):
        ss = _open_spreadsheet(self.sheet_id, self.creds_path)
        try:
            return ss, ss.worksheet(self.worksheet)
        except Exception:
            return ss, ss.add_worksheet(self.worksheet, rows=200, cols=20)

    def push_roster(self, rows: list[dict], day_cols: list[str]) -> SyncResult:
        ss, ws = self._ws()
        header = ["employee_id", "name", "role", "department", *day_cols]
        data = [header] + [[r.get("employee_id"), r.get("name"), r.get("role"),
                            r.get("department"), *[r.get(c, "") for c in day_cols]] for r in rows]
        ws.clear()
        ws.update(data, "A1")
        return SyncResult("google_sheets", True, ss.url)

    def record_fill(self, *, employee_id: str, name: str, day_label: str,
                    code: str, when: datetime) -> SyncResult:
        ss, ws = self._ws()
        header = ws.row_values(1)
        if day_label not in header:
            return SyncResult("google_sheets", False, ss.url, f"column '{day_label}' not in sheet")
        col = header.index(day_label) + 1
        cell = ws.find(employee_id, in_column=1)
        if not cell:
            return SyncResult("google_sheets", False, ss.url, f"{employee_id} not found")
        ws.update_cell(cell.row, col, code)
        return SyncResult("google_sheets", True, ss.url)
