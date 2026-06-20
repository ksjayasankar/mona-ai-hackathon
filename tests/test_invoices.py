"""P1 Globus — invoice triage tests. Offline by default (local Ollama, text invoices).

Pure-logic tests (routing, dedupe fingerprint, confidence→status) need NO model and
always run. The split/extract + service tests use the local Ollama provider on TEXT
invoices (conftest forces LLM_PROVIDER=ollama, AUTH_MODE=dev, throwaway SQLite).
"""
from agents import invoices
from agents.invoices import InvoiceFields


def _fields(**kw) -> InvoiceFields:
    """Build an InvoiceFields for tests; everything optional defaults sensibly."""
    base = dict(vendor="ACME GmbH", invoice_number="R-100", date="2026-03-04",
                currency="EUR", total="€1,240.00", vat_rate="19%", category="Software",
                confidence=95.0)
    base.update(kw)
    return InvoiceFields(**base)


# ---- deterministic routing (category -> department) ---------------------
def test_routing_maps_categories_to_departments():
    assert invoices.route("Electricity") == "Facilities"
    assert invoices.route("Cloud / SaaS subscription") == "IT"
    assert invoices.route("Hotel stay") == "Travel & Expenses"
    assert invoices.route("Office supplies") == "Procurement"
    assert invoices.route("Professional services / consulting") == "Finance Approval"


def test_routing_unknown_category_falls_through_to_finance_review():
    assert invoices.route("Mystery widgets") == invoices.DEFAULT_DEPT
    assert invoices.route(None) == invoices.DEFAULT_DEPT


# ---- dedupe fingerprint -------------------------------------------------
def test_same_invoice_rescanned_has_same_fingerprint():
    a = _fields()
    b = _fields()  # a re-scan of the identical invoice
    assert invoices.fingerprint(a) == invoices.fingerprint(b)


def test_fingerprint_ignores_case_and_whitespace_and_money_formatting():
    a = _fields(vendor="ACME GmbH", total="€1,240.00")
    b = _fields(vendor="  acme  gmbh ", total="1.240,00 €")  # DE formatting, messy spacing
    assert invoices.fingerprint(a) == invoices.fingerprint(b)


def test_amended_invoice_shares_dupe_key_but_differs_on_fingerprint():
    original = _fields(total="€1,240.00")
    amended = _fields(total="€1,420.00")  # same vendor+number, different total
    assert invoices.dupe_key(original) == invoices.dupe_key(amended)
    assert invoices.fingerprint(original) != invoices.fingerprint(amended)


# ---- confidence -> status (the "flag for human confirm" gate) -----------
def test_grounded_high_confidence_invoice_is_pending_approval():
    f = _fields(
        evidence={"vendor": "ACME GmbH", "total": "Gesamtbetrag 1.240,00 €", "date": "04.03.2026"},
        field_confidence={"vendor": 98.0, "total": 96.0, "date": 97.0},
    )
    assert invoices.invoice_status(f) == invoices.STATUS_PENDING


def test_low_confidence_field_routes_to_needs_review():
    f = _fields(
        evidence={"vendor": "ACME GmbH", "total": "9·0,00 (glare)", "date": "11.03.2026"},
        field_confidence={"vendor": 72.0, "total": 58.0, "date": 68.0},  # total below threshold
    )
    assert invoices.invoice_status(f) == invoices.STATUS_NEEDS_REVIEW


def test_ungrounded_field_routes_to_needs_review_even_if_confident():
    f = _fields(
        evidence={"vendor": "ACME GmbH", "total": "Gesamtbetrag 1.240,00 €"},  # no 'date' evidence
        field_confidence={"vendor": 98.0, "total": 96.0, "date": 99.0},
    )
    assert invoices.invoice_status(f) == invoices.STATUS_NEEDS_REVIEW


# ---- extraction + multi-invoice split (offline Ollama, TEXT invoices) ----
_ONE_INVOICE = """\
RECHNUNG
Stadtwerke München GmbH
Rechnungsnummer: SW-2026-0042
Rechnungsdatum: 04.03.2026
Leistung: Gaslieferung (Gas)
Nettobetrag: 241,53 €
MwSt 7%: 16,91 €
Gesamtbetrag: 258,44 €
"""

_TWO_INVOICES = """\
=== INVOICE 1 ===
INVOICE
Microsoft Ireland Operations Ltd
Invoice number: MS-9001
Date: 2026-03-05
Item: Software licenses
VAT 23%
Total due: €2,407.43

=== INVOICE 2 ===
RECHNUNG
Deutsche Telekom AG
Rechnungsnummer: DT-5500
Rechnungsdatum: 06.03.2026
Leistung: Internet & Telefon
MwSt 19%
Gesamtbetrag: 86,73 €
"""


def _text_blocks(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def test_extracts_invoice_fields_from_text_smoke():
    out = invoices.split_invoices(_text_blocks(_ONE_INVOICE))
    assert len(out) >= 1
    first = out[0]
    # the verbatim identifiers a small model reads reliably (number-parsing the total is
    # a known weak spot for the 8B dev model, so we don't gate the smoke on it)
    assert "stadtwerke" in invoices._norm(first.vendor)
    assert "sw20260042" in invoices._norm(first.invoice_number)


def test_splits_two_invoices_in_one_document():
    out = invoices.split_invoices(_text_blocks(_TWO_INVOICES))
    assert len(out) >= 2, f"expected the model to segment 2 invoices, got {len(out)}"


def test_suggest_department_returns_a_dept_and_reason():
    f = _fields(category="miscellaneous widgets", vendor="Generic Supplies Co")
    sug = invoices.suggest_department(f)
    assert sug.department.strip()
    assert sug.reason.strip()


# ======================================================================
# Service layer — orchestration (offline Ollama, text invoices)
# ======================================================================
from core.auth import get_or_create_tenant
from core.models import InvoiceRecord
from services import invoices as inv_svc


def _prior(**kw) -> InvoiceRecord:
    f = _fields(**kw)
    return InvoiceRecord(tenant_id="t", vendor=f.vendor, invoice_number=f.invoice_number,
                         total=f.total, date=f.date,
                         fingerprint=invoices.fingerprint(f), dupe_key=invoices.dupe_key(f))


# ---- pure dedupe classification (no DB, no LLM) -------------------------
def test_exact_resend_is_classified_as_duplicate():
    prior = [_prior()]
    dup_of, flags = inv_svc.classify_against_prior(_fields(), prior)
    assert dup_of == prior[0].id
    assert any("duplicate" in f.lower() for f in flags)


def test_amended_invoice_is_classified_as_possible_amendment_not_silent_drop():
    prior = [_prior(total="€1,240.00")]
    dup_of, flags = inv_svc.classify_against_prior(_fields(total="€1,420.00"), prior)
    assert dup_of == prior[0].id
    assert any("amend" in f.lower() for f in flags)


def test_brand_new_invoice_is_not_a_duplicate():
    prior = [_prior(invoice_number="R-100")]
    dup_of, flags = inv_svc.classify_against_prior(_fields(invoice_number="R-999"), prior)
    assert dup_of is None
    assert flags == []


# ---- end-to-end orchestration -------------------------------------------
def test_process_splits_and_persists_each_invoice():
    tenant = get_or_create_tenant("test-globus-split", "Test Globus Split")
    report = inv_svc.process("3 invoices for March attached.", tenant_id=tenant,
                             text_attachments=[("march_batch.txt", _TWO_INVOICES)])
    assert report.counts["found"] >= 2
    rows = inv_svc.history(tenant)
    assert len(rows) >= 2


def test_resent_duplicate_is_flagged_against_the_db():
    tenant = get_or_create_tenant("test-globus-dupe", "Test Globus Dupe")
    inv_svc.process("First send.", tenant_id=tenant,
                    text_attachments=[("inv.txt", _ONE_INVOICE)])
    again = inv_svc.process("Re-sent the same invoice.", tenant_id=tenant,
                            text_attachments=[("inv_again.txt", _ONE_INVOICE)])
    assert any(r.status == "duplicate" for r in again.invoices), \
        "a re-sent identical invoice must be flagged, not silently re-ingested"


def test_approve_records_an_approval_action():
    tenant = get_or_create_tenant("test-globus-approve", "Test Globus Approve")
    report = inv_svc.process("Please process.", tenant_id=tenant,
                             text_attachments=[("inv.txt", _ONE_INVOICE)])
    inv_id = report.invoices[0].id
    inv_svc.approve(tenant, inv_id, approver="clerk@globus", outcome="approved", note="looks good")
    rows = inv_svc.history(tenant)
    approved = next(r for r in rows if r["id"] == inv_id)
    assert approved["status"] == "approved"
