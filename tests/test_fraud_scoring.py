from agents import fraud as A
from core.tools.forensics import Signal


def _sig(sev, cat="forensic", weak=False):
    return Signal(name="x", severity=sev, category=cat, evidence="e", why="w", weak=weak)


def test_no_signals_is_low_zero():
    r = A.score_risk([])
    assert r.risk == "LOW" and r.score == 0


def test_two_high_signals_is_high():
    r = A.score_risk([_sig("high"), _sig("high")])
    assert r.risk == "HIGH" and r.score >= 67


def test_weak_only_never_high():
    r = A.score_risk([_sig("high", weak=True), _sig("high", weak=True), _sig("medium", weak=True)])
    assert r.risk != "HIGH"


def test_injection_forces_high():
    r = A.score_risk([_sig("high", cat="injection")])
    assert r.risk == "HIGH" and r.score >= 85


def test_monotonic_adding_signal_never_lowers():
    base = A.score_risk([_sig("medium")]).score
    more = A.score_risk([_sig("medium"), _sig("low")]).score
    assert more >= base


def test_findings_to_signals_skill_gap_is_weak():
    f = A.VerifyFindings(github_account_age_years=1.0, github_languages=["python"],
                         claimed_experience_years=10.0, skills_not_found=["rust"],
                         company_web_findings=[], notes=None)
    sigs = A.findings_to_signals(f)
    assert any(s.category == "verification" for s in sigs)
    assert any(s.weak for s in sigs)  # absence-of-evidence stays weak
