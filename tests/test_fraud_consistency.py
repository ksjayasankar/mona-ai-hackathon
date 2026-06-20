from datetime import date

from agents import fraud as A
from agents.fraud import CVClaims, CVRole, CertFields

TODAY = date(2026, 6, 20)


def _claims(roles, name="Jane Doe"):
    return CVClaims(candidate_name=name, roles=roles, skills=[], summary=None,
                    languages=[], extraction_confidence=90.0)


def test_overlapping_roles_flagged():
    roles = [CVRole(title="A", employer="X", start="01/2019", end="06/2022", achievements_specific=True),
             CVRole(title="B", employer="Y", start="01/2021", end="present", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    overlap = next(s for s in sigs if s.name == "timeline_overlap")
    assert overlap.category == "consistency"
    assert "2019" in overlap.evidence and "2021" in overlap.evidence


def test_large_gap_flagged_low():
    roles = [CVRole(title="A", employer="X", start="01/2014", end="06/2016", achievements_specific=True),
             CVRole(title="B", employer="Y", start="01/2020", end="present", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    gap = next(s for s in sigs if s.name == "timeline_gap")
    assert gap.severity == "low"


def test_end_before_start_flagged():
    roles = [CVRole(title="A", employer="X", start="01/2022", end="01/2019", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    assert "impossible_dates" in {s.name for s in sigs}


def test_future_date_flagged():
    roles = [CVRole(title="A", employer="X", start="01/2030", end="present", achievements_specific=True)]
    sigs = A.consistency_signals(_claims(roles), today=TODAY)
    assert "future_dated" in {s.name for s in sigs}


def test_clean_timeline_no_signals():
    roles = [CVRole(title="A", employer="X", start="01/2016", end="12/2019", achievements_specific=True),
             CVRole(title="B", employer="Y", start="01/2020", end="present", achievements_specific=True)]
    assert A.consistency_signals(_claims(roles), today=TODAY) == []


def test_cv_cert_name_mismatch():
    cert = CertFields(is_certificate=True, cert_type="diploma", issuer="Uni", holder_name="John Smith",
                      title="BSc", issue_date="2019", valid_until=None, is_genuine_looking=True,
                      forgery_signals=[], extraction_confidence=90.0, notes=None)
    sigs = A.cross_signals(_claims([], name="Jane Doe"), [cert])
    assert "name_mismatch" in {s.name for s in sigs}


def test_expired_certificate_flagged():
    cert = CertFields(is_certificate=True, cert_type="license", issuer="ISACA", holder_name="Jane Doe",
                      title="CISA", issue_date="2018", valid_until="01.01.2020", is_genuine_looking=True,
                      forgery_signals=[], extraction_confidence=90.0, notes=None)
    sigs = A.cert_signals(cert, today=TODAY)
    s = next(x for x in sigs if x.name == "certificate_expired")
    assert "2020" in s.evidence


def test_forgery_signal_maps_to_high():
    cert = CertFields(is_certificate=True, cert_type="license", issuer="ISACA", holder_name="Jane Doe",
                      title="CISA", issue_date="2018", valid_until=None, is_genuine_looking=False,
                      forgery_signals=["warped seal", "inconsistent fonts"], extraction_confidence=90.0, notes=None)
    sigs = A.cert_signals(cert, today=TODAY)
    assert any(s.severity == "high" for s in sigs)
