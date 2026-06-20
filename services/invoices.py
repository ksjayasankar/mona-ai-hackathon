"""P1 Globus — Invoice Triage service (productized, tenant-scoped, persisted).

Pipeline (mirrors the secure-intake reference):
  1. INGEST  — a simulated inbox: an email body + attachments (PDF/photo/Word/text).
               A pluggable IMAP/Gmail connector INTERFACE is defined below but NOT wired
               (no OAuth) — the demo runs on uploaded/pasted content, no credentials.
  2. SPLIT   — agents.invoices.split_invoices segments each source into N invoices, each
               with grounded per-field evidence + per-field confidence + a source span.
  3. ROUTE   — deterministic category→department table (rules-first); the LLM only SUGGESTS
               a department (with a one-line reason) when the table falls through.
  4. DEDUPE  — deterministic fingerprint vs the tenant's prior invoices: an exact re-send or
               a same-number/different-total amendment is FLAGGED for a human, never dropped.
  5. GATE    — ungrounded / below-confidence invoices route to needs_review before approval.
  6. PERSIST — InvoiceRecord + AuditLog per invoice; approvals write an ApprovalAction.

agents/invoices.py stays the pure logic; this is the product version (persistence + auth).
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel
from sqlmodel import Session, desc, select

from agents import invoices
from core import ingest
from core.db import engine
from core.models import AuditLog, InvoiceRecord
from core.models.invoice import (
    STATUS_APPROVED,
    STATUS_DUPLICATE,
    ApprovalAction,
)


# ---- pluggable inbox connector (interface only — NOT wired to real OAuth) ----
class InboxConnector(Protocol):
    """Where invoices come from. The demo uses UploadedInbox (no creds). A real
    IMAP/Gmail connector would implement the same shape and drop in unchanged."""

    def fetch(self) -> list[tuple[str, bytes]]:
        """Return [(filename, bytes)] for new invoice attachments."""
        ...


# ---- API result shapes --------------------------------------------------
class InvoiceRow(BaseModel):
    id: str
    source: str | None
    source_span: str | None
    vendor: str | None
    invoice_number: str | None
    date: str | None
    due_date: str | None
    po_number: str | None
    currency: str | None
    total: str | None
    net_amount: str | None
    vat_amount: str | None
    vat_rate: str | None
    category: str | None
    department: str | None
    dept_reason: str | None
    status: str
    confidence: float
    duplicate_of: str | None
    evidence: dict
    field_confidence: dict
    line_items: list
    flags: list[str]


class TriageReport(BaseModel):
    invoices: list[InvoiceRow]
    counts: dict
    summary: str


# ---- dedupe (pure: no DB, no LLM) ---------------------------------------
def classify_against_prior(
    f: invoices.InvoiceFields, prior: list[InvoiceRecord]
) -> tuple[str | None, list[str]]:
    """Does this invoice duplicate or amend one we already hold? Returns
    (matched_record_id | None, human-readable flags). Never silently drops."""
    fp, dk = invoices.fingerprint(f), invoices.dupe_key(f)
    for r in prior:
        if r.fingerprint and r.fingerprint == fp:
            return r.id, [f"Exact duplicate of {r.vendor or '?'} {r.invoice_number or ''} "
                          f"already received — held for a human, not re-ingested."]
        if r.dupe_key and dk and r.dupe_key == dk:
            return r.id, [f"Possible amendment of {r.vendor or '?'} {r.invoice_number or ''}: "
                          f"total {f.total} vs the earlier {r.total}. Held for a human."]
    return None, []


def _human_flags(f: invoices.InvoiceFields, dept: str, status: str) -> list[str]:
    out: list[str] = []
    if status == invoices.STATUS_NEEDS_REVIEW:
        weak = [k for k in invoices.CRITICAL_FIELDS
                if not f.evidence.get(k)
                or f.field_confidence.get(k, f.confidence) < invoices.CONF_THRESHOLD]
        out.append("Held for human review — not grounded/confident: " + ", ".join(weak) + ".")
    if dept == invoices.DEFAULT_DEPT:
        out.append("No routing rule matched — sent to Finance Review.")
    if f.notes:
        out.append(f.notes)
    return out


def _to_row(rec: InvoiceRecord) -> InvoiceRow:
    return InvoiceRow(
        id=rec.id, source=rec.source, source_span=rec.source_span, vendor=rec.vendor,
        invoice_number=rec.invoice_number, date=rec.date, due_date=rec.due_date,
        po_number=rec.po_number, currency=rec.currency, total=rec.total,
        net_amount=rec.net_amount, vat_amount=rec.vat_amount, vat_rate=rec.vat_rate,
        category=rec.category, department=rec.department, dept_reason=rec.dept_reason,
        status=rec.status, confidence=rec.confidence, duplicate_of=rec.duplicate_of,
        evidence=rec.evidence, field_confidence=rec.field_confidence,
        line_items=rec.line_items, flags=rec.flags,
    )


# ---- orchestration ------------------------------------------------------
def process(email_body: str, *, tenant_id: str,
            attachment_files: list[tuple[str, bytes]] | None = None,
            text_attachments: list[tuple[str, str]] | None = None,
            provider: str | None = None) -> TriageReport:
    # 1) INGEST — assemble invoice sources. Attachments are the invoice carriers; the email
    #    body is only treated as an invoice when nothing is attached (a pasted invoice).
    sources: list[tuple[str, list[dict]]] = []
    for name, data in (attachment_files or []):
        sources.append((name, ingest.bytes_to_blocks(data, Path(name).suffix, name)))
    for name, text in (text_attachments or []):
        sources.append((name, [{"type": "text", "text": text}]))
    if not sources and email_body.strip():
        sources.append(("email body", [{"type": "text", "text": email_body}]))

    recs: list[InvoiceRecord] = []
    with Session(engine) as s:
        # prior = everything this tenant already holds; grows as we persist this batch so
        # an invoice re-sent twice IN THE SAME email is still caught.
        prior: list[InvoiceRecord] = list(
            s.exec(select(InvoiceRecord).where(InvoiceRecord.tenant_id == tenant_id)).all())

        for src_name, blocks in sources:
            for f in invoices.split_invoices(blocks, provider=provider):
                # 3) ROUTE (rules-first; LLM suggests only on fall-through)
                dept = invoices.route(f.category)
                dept_reason = None
                if dept == invoices.DEFAULT_DEPT:
                    try:
                        sug = invoices.suggest_department(f, provider=provider)
                        dept_reason = f"Suggested: {sug.department} — {sug.reason}"
                    except Exception:
                        pass
                # 4) DEDUPE  5) GATE
                dup_of, dup_flags = classify_against_prior(f, prior)
                status = STATUS_DUPLICATE if dup_of else invoices.invoice_status(f)
                flags = dup_flags + _human_flags(f, dept, status)

                rec = InvoiceRecord(
                    tenant_id=tenant_id, source=src_name, source_span=f.source_span,
                    vendor=f.vendor, invoice_number=f.invoice_number, date=f.date,
                    due_date=f.due_date, po_number=f.po_number, currency=f.currency,
                    total=f.total, net_amount=f.net_amount, vat_amount=f.vat_amount,
                    vat_rate=f.vat_rate, category=f.category, department=dept,
                    dept_reason=dept_reason, status=status, confidence=round(f.confidence, 1),
                    fingerprint=invoices.fingerprint(f), dupe_key=invoices.dupe_key(f),
                    duplicate_of=dup_of, evidence=f.evidence, field_confidence=f.field_confidence,
                    line_items=[li.model_dump() for li in f.line_items],
                    fields=f.model_dump(), flags=flags,
                )
                s.add(rec)
                s.add(AuditLog(
                    tenant_id=tenant_id,
                    action="invoice.duplicate" if dup_of else "invoice.triaged",
                    severity="warning" if dup_of else "info",
                    detail={"vendor": f.vendor, "invoice_number": f.invoice_number,
                            "department": dept, "status": status, "source": src_name}))
                prior.append(rec)
                recs.append(rec)
        s.commit()
        for rec in recs:
            s.refresh(rec)
        rows = [_to_row(rec) for rec in recs]

    counts = {
        "found": len(rows),
        "pending": sum(r.status == invoices.STATUS_PENDING for r in rows),
        "needs_review": sum(r.status == invoices.STATUS_NEEDS_REVIEW for r in rows),
        "duplicate": sum(r.status == STATUS_DUPLICATE for r in rows),
    }
    summary = (f"{counts['found']} invoice(s): {counts['pending']} ready to approve, "
               f"{counts['needs_review']} need review, {counts['duplicate']} flagged duplicate.")
    return TriageReport(invoices=rows, counts=counts, summary=summary)


def approve(tenant_id: str, invoice_id: str, *, approver: str,
            outcome: str = "approved", note: str | None = None) -> dict:
    """Record a human decision on an invoice + its audit trail."""
    with Session(engine) as s:
        rec = s.get(InvoiceRecord, invoice_id)
        if rec is None or rec.tenant_id != tenant_id:
            raise ValueError("invoice not found for this tenant")
        if outcome == "approved":
            rec.status = STATUS_APPROVED
        elif outcome == "rejected":
            rec.status = "rejected"
        s.add(rec)
        s.add(ApprovalAction(tenant_id=tenant_id, invoice_id=invoice_id,
                             approver=approver, outcome=outcome, note=note))
        s.add(AuditLog(tenant_id=tenant_id, action=f"invoice.{outcome}", severity="info",
                       detail={"invoice_id": invoice_id, "approver": approver, "note": note}))
        s.commit()
        return {"id": invoice_id, "status": rec.status, "outcome": outcome}


def history(tenant_id: str, limit: int = 50) -> list[dict]:
    with Session(engine) as s:
        rows = s.exec(select(InvoiceRecord).where(InvoiceRecord.tenant_id == tenant_id)
                      .order_by(desc(InvoiceRecord.created_at)).limit(limit)).all()
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "vendor": r.vendor,
                 "invoice_number": r.invoice_number, "total": r.total, "currency": r.currency,
                 "department": r.department, "status": r.status, "source": r.source,
                 "duplicate_of": r.duplicate_of} for r in rows]
