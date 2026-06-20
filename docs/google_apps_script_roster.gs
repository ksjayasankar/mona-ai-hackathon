/**
 * UKS roster webhook — the simplest "live Google Sheets" path (no Cloud project / service account).
 *
 * SETUP (≈2 min):
 *   1. Create/open a Google Sheet.
 *   2. Extensions → Apps Script. Delete the default Code.gs contents and paste THIS file.
 *   3. Set SECRET below to any random string.
 *   4. Deploy → New deployment → ⚙ type: "Web app" →
 *        Execute as: Me · Who has access: Anyone → Deploy. (Authorize when prompted.)
 *   5. Copy the "Web app" URL.
 *   6. In the repo .env:
 *        GOOGLE_APPS_SCRIPT_URL=<the Web app URL>
 *        GOOGLE_APPS_SCRIPT_SECRET=<the same SECRET you set below>
 *        GOOGLE_SHEETS_WORKSHEET=Roster        (optional; the tab is auto-created)
 *   7. Restart the API. Seeding fills the sheet; accepting a shift flips the winner's cell to N/D, live.
 *
 * The script runs AS YOU (the sheet owner), so it already has write access — nothing to share.
 * The endpoint is public, so every request must carry the matching SECRET or it's rejected.
 */
const SECRET = "change-me"; // <-- must equal GOOGLE_APPS_SCRIPT_SECRET in .env

function doPost(e) {
  const out = (obj) =>
    ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);

  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return out({ ok: false, error: "bad json" });
  }
  if (body.secret !== SECRET) return out({ ok: false, error: "forbidden" });

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const name = body.worksheet || "Roster";
  const sheet = ss.getSheetByName(name) || ss.insertSheet(name);

  if (body.action === "push") {
    sheet.clearContents();
    const rows = body.rows || [];
    if (rows.length) sheet.getRange(1, 1, rows.length, rows[0].length).setValues(rows);
    return out({ ok: true, url: ss.getUrl() });
  }

  if (body.action === "fill") {
    const data = sheet.getDataRange().getValues();
    const header = data[0] || [];
    const col = header.indexOf(body.day_label);
    if (col < 0) return out({ ok: false, error: "day column not found", url: ss.getUrl() });
    for (let r = 1; r < data.length; r++) {
      if (String(data[r][0]) === String(body.employee_id)) {
        sheet.getRange(r + 1, col + 1).setValue(body.code).setBackground("#c6efce");
        return out({ ok: true, url: ss.getUrl() });
      }
    }
    return out({ ok: false, error: "employee not found", url: ss.getUrl() });
  }

  return out({ ok: false, error: "unknown action" });
}
