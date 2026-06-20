from datetime import date

import services.fraud as svc
from agents.fraud import CVClaims, CVRole, CertFields
from core.auth import get_or_create_tenant
from core.tools.forensics import Signal

TODAY = date(2026, 6, 20)


def _claims():
    return CVClaims(candidate_name="Jane Doe", email="jane@x.com", github="github.com/jane",
                    roles=[CVRole(title="Dev", employer="X", start="01/2019", end="06/2022",
                                  achievements_specific=True),
                           CVRole(title="Dev2", employer="Y", start="01/2021", end="present",
                                  achievements_specific=True)],
                    skills=["python"], summary="Engineer", languages=["English"], extraction_confidence=90.0)


def _cert():
    return CertFields(is_certificate=True, cert_type="diploma", issuer="Uni", holder_name="Jane Doe",
                      title="BSc", issue_date="2018", valid_until=None, is_genuine_looking=True,
                      forgery_signals=[], extraction_confidence=90.0, notes=None)


def test_build_report_assembles_and_scores():
    forensic = [Signal(name="incremental_updates", severity="medium", category="forensic",
                       evidence="2 generations", why="edit history")]
    rep = svc.build_report(claims=_claims(), cert_fields=[_cert()], forensic_signals=forensic,
                           verify_findings=None, today=TODAY)
    # the overlap (consistency) + the forensic signal are both present
    names = {s["name"] for s in rep.by_category.get("consistency", [])}
    assert "timeline_overlap" in names
    assert rep.risk in ("LOW", "MEDIUM", "HIGH")
    assert "not an automated verdict" in rep.summary or "signal" in rep.methodology_note.lower()
    # the AI-writing caveat (weak, never reject) is disclosed
    assert "weak" in rep.methodology_note.lower() and "never" in rep.methodology_note.lower()


def test_persist_and_history_tenant_scoped():
    tenant = get_or_create_tenant("test-persowerk", "Test Persowerk")
    rep = svc.build_report(claims=_claims(), cert_fields=[_cert()], forensic_signals=[],
                           verify_findings=None, today=TODAY)
    rid = svc.persist(tenant, rep, _claims(), [_cert()])
    rows = svc.history(tenant)
    assert any(r["id"] == rid for r in rows)
    full = svc.get_record(tenant, rid)
    assert full and full["report"]["candidate_name"] == "Jane Doe"
    # isolation: another tenant cannot see it
    other = get_or_create_tenant("test-persowerk-other", "Other")
    assert svc.get_record(other, rid) is None
