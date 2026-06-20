"""P3 Leistenschneider — work-permit validator tests.

Fully OFFLINE + deterministic. The verdict rule, rubric confidence, grounding check and
§AufenthG consult are all PURE logic, so these tests never call a model (and so never
touch the Gemini quota). conftest forces the ollama provider + a throwaway SQLite DB.
"""
from __future__ import annotations

from datetime import date

from agents import aufenthg, permits

PIN = date(2026, 6, 20)  # the demo "today"; pinned so tests are date-independent


def _fields(**over) -> "permits.PermitFields":
    """A fully-grounded, valid §18a skilled-worker permit; override fields per test."""
    base = dict(
        is_work_permit=True,
        document_type="Aufenthaltserlaubnis",
        document_type_quote="TYP / TYPE  AUFENTHALTSERLAUBNIS",
        holder_name="Amara Chidi Okonkwo",
        nationality="NIGERIA (NGA)",
        legal_basis="§ 18a AufenthG — Fachkraft mit Berufsausbildung",
        issue_date="15.08.2024",
        valid_until="14.08.2027",
        valid_until_quote="Gültig bis / Valid until  14.08.2027",
        employment_allowed=True,
        employment_quote="Beschäftigung gestattet. Dependent employment permitted.",
        extraction_confidence=96.0,
        notes=None,
    )
    base.update(over)
    return permits.PermitFields(**base)


# ----------------------------------------------------------------------------
# §AufenthG corpus — deterministic lookup (the offline path the verdict relies on)
# ----------------------------------------------------------------------------
def test_blue_card_is_work_authorized_by_statute():
    rule = aufenthg.lookup("§ 18b Abs. 2 AufenthG — Hochqualifizierte", "Blaue Karte EU")
    assert rule is not None
    assert rule.default_work == "permitted"
    assert "18" in rule.source  # cites a real statute, not a fabricated one


def test_student_permit_restricts_employment():
    rule = aufenthg.lookup("§ 16b AufenthG — Studium", "Aufenthaltserlaubnis")
    assert rule is not None
    assert rule.default_work == "restricted"
    assert rule.zusatzblatt_required is True


def test_skilled_worker_permit_allows_employment():
    rule = aufenthg.lookup("§ 18a AufenthG — Fachkraft mit Berufsausbildung", None)
    assert rule is not None
    assert rule.default_work == "permitted"


def test_unknown_legal_basis_returns_none():
    assert aufenthg.lookup("§ 99z PhantasieG — made up", "Mystery") is None
    assert aufenthg.lookup(None, None) is None


def test_rag_generalizes_to_novel_wording():
    # wording the deterministic matcher misses, but is semantically a corpus rule.
    novel = "residence title issued for the purpose of enrolling at a university"
    assert aufenthg.lookup(novel, "study visa") is None          # deterministic miss
    rule = aufenthg.resolve(novel, "study visa", use_rag=True)   # RAG fallback
    assert rule is not None                                       # resolved, not fabricated
    assert rule.id in {r["id"] for r in aufenthg._RULES}          # a real corpus rule
    assert rule.source.startswith("§")                           # cites a real statute


# ----------------------------------------------------------------------------
# Verdict rule — deterministic, pure, offline (no model)
# ----------------------------------------------------------------------------
def test_valid_permit_is_confirmed_with_high_confidence():
    r = permits.decide(_fields(), today=PIN)
    assert r.decision == "VALID"
    assert r.valid_until == "14.08.2027"
    assert r.days_remaining is not None and r.days_remaining > 0
    assert r.confidence >= 90
    assert r.needs_review is False
    assert r.legal_basis_citation and "18a" in r.legal_basis_citation


def test_expired_permit_is_rejected():
    r = permits.decide(
        _fields(valid_until="02.05.2024", valid_until_quote="Gültig bis / Valid until 02.05.2024"),
        today=PIN,
    )
    assert r.decision == "EXPIRED"
    assert r.days_remaining is not None and r.days_remaining < 0


def test_today_is_injectable():
    f = _fields(valid_until="01.01.2027", valid_until_quote="Gültig bis 01.01.2027")
    assert permits.decide(f, today=date(2026, 12, 31)).decision == "VALID"
    assert permits.decide(f, today=date(2027, 2, 1)).decision == "EXPIRED"


def test_student_permit_with_employment_prohibited_is_not_work_authorized():
    r = permits.decide(_fields(
        legal_basis="§ 16b AufenthG — Studium",
        employment_allowed=False,
        employment_quote="Erwerbstätigkeit nicht gestattet. Employment not permitted.",
        valid_until="30.09.2027", valid_until_quote="Gültig bis / Valid until 30.09.2027",
    ), today=PIN)
    assert r.decision == "NOT_WORK_AUTHORIZED"


def test_drivers_license_is_not_a_permit():
    r = permits.decide(permits.PermitFields(
        is_work_permit=False, document_type="Führerschein",
        document_type_quote="FÜHRERSCHEIN / DRIVING LICENCE", extraction_confidence=97.0,
    ), today=PIN)
    assert r.decision == "NOT_A_PERMIT"
    assert any("permit" in reason.lower() for reason in r.reasons)


# ----------------------------------------------------------------------------
# Grounding — never trust a value the model can't quote from the document
# ----------------------------------------------------------------------------
def test_fabricated_valid_until_is_flagged_ungrounded():
    # the model claims a valid-until that is NOT supported by any quoted text
    r = permits.decide(_fields(valid_until="01.01.2099", valid_until_quote=""), today=PIN)
    assert r.decision == "NEEDS_REVIEW"
    assert r.needs_review is True
    assert any("ground" in reason.lower() for reason in r.reasons)


def test_implied_authorization_routes_to_human_review_with_citation():
    # Blue Card with NO printed employment clause -> permitted by statute, but a human confirms.
    r = permits.decide(_fields(
        document_type="Blaue Karte EU", document_type_quote="TYP / TYPE BLAUE KARTE EU",
        legal_basis="§ 18b Abs. 2 AufenthG — Hochqualifizierte",
        employment_allowed=None, employment_quote=None,
        valid_until="31.03.2028", valid_until_quote="Gültig bis / Valid until 31.03.2028",
    ), today=PIN)
    assert r.decision == "NEEDS_REVIEW"
    assert r.legal_basis_citation and "18g" in r.legal_basis_citation  # real statute cited
    assert any("statute" in reason.lower() for reason in r.reasons)


# ----------------------------------------------------------------------------
# Rubric confidence — transparent, itemized, explainable
# ----------------------------------------------------------------------------
def test_rubric_is_itemized_and_sums_to_confidence():
    r = permits.decide(_fields(), today=PIN)
    assert len(r.rubric) >= 4
    assert round(sum(item.earned for item in r.rubric), 1) == r.confidence
    assert all(item.detail for item in r.rubric)  # every line explains itself


def test_below_threshold_valid_routes_to_review():
    # legible-but-weak read: low classification confidence + ungrounded doc type -> below threshold
    r = permits.decide(_fields(extraction_confidence=20.0, document_type_quote=""), today=PIN)
    assert r.decision == "NEEDS_REVIEW"
    assert r.needs_review is True


# ----------------------------------------------------------------------------
# Service — persistence + human-review oversight loop (offline; no LLM)
# ----------------------------------------------------------------------------
from core.auth import get_or_create_tenant          # noqa: E402
from services import permits as permits_svc          # noqa: E402


def _persist_review_case():
    """A Blue Card with no printed employment clause -> needs_review; persisted."""
    r = permits.decide(_fields(
        document_type="Blaue Karte EU", document_type_quote="TYP / TYPE BLAUE KARTE EU",
        legal_basis="§ 18b Abs. 2 AufenthG — Hochqualifizierte",
        employment_allowed=None, employment_quote=None,
        valid_until="31.03.2028", valid_until_quote="Gültig bis / Valid until 31.03.2028",
    ), today=PIN)
    assert r.needs_review is True
    tenant = get_or_create_tenant("test-leistenschneider", "Test Leistenschneider")
    saved = permits_svc.save_check(tenant, "blue_card.pdf", r)
    return tenant, saved


def test_below_threshold_check_enters_review_queue():
    tenant, saved = _persist_review_case()
    queue = permits_svc.review_queue(tenant)
    assert any(c["id"] == saved["id"] for c in queue)


def test_human_override_updates_decision_logs_audit_and_leaves_queue():
    tenant, saved = _persist_review_case()
    out = permits_svc.review(tenant, saved["id"], reviewer="officer@leistenschneider.de",
                             outcome="overridden", override_decision="VALID",
                             note="Zusatzblatt confirms employment")
    assert out["decision"] == "VALID"
    assert out["status"] == "overridden"
    # it has left the human-review queue
    assert all(c["id"] != saved["id"] for c in permits_svc.review_queue(tenant))
    # the override is audited with reviewer + outcome
    actions = permits_svc.review_history(tenant, saved["id"])
    assert any(a["outcome"] == "overridden" and a["reviewer"] == "officer@leistenschneider.de"
               for a in actions)


def test_tenant_isolation_on_review_queue():
    tenant, saved = _persist_review_case()
    other = get_or_create_tenant("test-other-agency", "Other Agency")
    assert all(c["id"] != saved["id"] for c in permits_svc.review_queue(other))


def test_process_end_to_end_persists_and_lists_in_history():
    # full glue: ingest TEXT (offline via ollama) -> validate -> persist -> history.
    # Assertions are lenient (local model output varies); we test the PLUMBING, not accuracy.
    permit_txt = (
        "BUNDESREPUBLIK DEUTSCHLAND — Aufenthaltstitel (residence permit). "
        "Art des Titels: Aufenthaltserlaubnis. Rechtsgrundlage: § 18a AufenthG — Fachkraft. "
        "Gültig bis / Valid until: 14.08.2027. Anmerkungen: Beschäftigung gestattet."
    )
    tenant = get_or_create_tenant("test-leistenschneider", "Test Leistenschneider")
    out = permits_svc.process(permit_txt.encode(), "permit.txt", tenant_id=tenant, today=PIN)
    assert out["id"]
    assert out["decision"] in {"VALID", "EXPIRED", "NOT_A_PERMIT", "NOT_WORK_AUTHORIZED", "NEEDS_REVIEW"}
    assert isinstance(out["rubric"], list)  # JSON column round-tripped
    assert any(h["id"] == out["id"] for h in permits_svc.history(tenant))


# ----------------------------------------------------------------------------
# API — HTTP layer, tenant-scoped, human-review endpoints (offline via ollama)
# ----------------------------------------------------------------------------
def test_api_upload_review_and_error_paths():
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    permit_txt = (
        "BUNDESREPUBLIK DEUTSCHLAND — Aufenthaltstitel. Aufenthaltserlaubnis. "
        "§ 18a AufenthG. Gültig bis / Valid until: 14.08.2027. Beschäftigung gestattet."
    )
    r = client.post("/agents/permits",
                    files={"file": ("permit.txt", permit_txt.encode(), "text/plain")})
    assert r.status_code == 200
    check = r.json()
    assert check["id"]
    assert check["decision"] in {"VALID", "EXPIRED", "NOT_A_PERMIT", "NOT_WORK_AUTHORIZED", "NEEDS_REVIEW"}

    assert client.get("/agents/permits/history").status_code == 200
    assert client.get("/agents/permits/review-queue").status_code == 200
    assert client.get(f"/agents/permits/{check['id']}").status_code == 200

    rev = client.post(f"/agents/permits/{check['id']}/review",
                      json={"outcome": "overridden", "override_decision": "VALID", "note": "checked"})
    assert rev.status_code == 200
    assert rev.json()["decision"] == "VALID" and rev.json()["status"] == "overridden"

    # invalid override decision -> 400; unknown check -> 404
    assert client.post(f"/agents/permits/{check['id']}/review",
                       json={"outcome": "overridden", "override_decision": "NONSENSE"}).status_code == 400
    assert client.get("/agents/permits/does-not-exist").status_code == 404
