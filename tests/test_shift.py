"""P2 UKS shift-replacement tests — offline (local ollama, structured gaps, no Twilio)."""
from datetime import datetime
from datetime import datetime as _dt

from sqlmodel import Session

from core.db import engine
from core.models import OutreachLog, ShiftGap, Staff


def test_models_roundtrip_new_columns():
    with Session(engine) as s:
        st = Staff(tenant_id="t1", employee_id="HOSP-9001", name="Test Nurse",
                   role="Registered Nurse", department="ICU", qualifications=["BLS", "ACLS"],
                   contract="Per-diem", max_hours_week=48, scheduled_hours_next7=24.0,
                   shift_grid={"Sat 06/20": "O"}, overtime_ok=True, shift_preference="Night",
                   active=True, last_shift_end=datetime(2026, 6, 19, 19, 0), persona="flex",
                   phone="+49 150 0000000")
        s.add(st); s.commit(); s.refresh(st)
        gap = ShiftGap(tenant_id="t1", role="Registered Nurse", department="ICU", shift="night",
                       day_label="Sat 06/20", required_certs=["BLS", "ACLS"], person_out="Felix",
                       shift_start=datetime(2026, 6, 20, 19, 0), shift_end=datetime(2026, 6, 21, 7, 0),
                       shift_hours=12.0, status="open", version=0)
        s.add(gap); s.commit(); s.refresh(gap)
        log = OutreachLog(tenant_id="t1", gap_id=gap.id, staff_id=st.id, channel="sms",
                          message="hi", status="queued", seq=0, token="tok-abc")
        s.add(log); s.commit(); s.refresh(log)
        assert st.shift_grid["Sat 06/20"] == "O" and st.overtime_ok is True
        assert gap.version == 0 and gap.shift_hours == 12.0
        assert log.token == "tok-abc" and log.seq == 0


# ---------------------------------------------------------------------------
# Task 2 — pure ArbZG eligibility engine
# ---------------------------------------------------------------------------
from agents import shift as shift_agent  # noqa: E402


def _night_gap(**over):
    base = dict(role="Registered Nurse", department="ICU", shift="night",
                shift_start=_dt(2026, 6, 20, 19, 0), shift_end=_dt(2026, 6, 21, 7, 0),
                shift_hours=12.0, day_label="Sat 06/20", required_certs=["BLS", "ACLS"],
                person_out_id="HOSP-1059", person_out="Felix Haddad")
    base.update(over)
    return shift_agent.GapSpec(**base)


def _staff(emp, role="Registered Nurse", dept="ICU", certs=("BLS", "ACLS"), active=True,
           grid_today="O", sched=24.0, maxh=48.0, last_end=_dt(2026, 6, 19, 19, 0),
           ot=True, contract="Full-time", pref="Flexible", last_contacted=None):
    return shift_agent.StaffLike(
        employee_id=emp, name=f"Nurse {emp}", role=role, department=dept,
        certifications=list(certs), contract=contract, max_hours_week=maxh,
        scheduled_hours_next7=sched, shift_grid={"Sat 06/20": grid_today}, overtime_ok=ot,
        shift_preference=pref, active=active, last_shift_end=last_end, phone="+49 150 1",
        persona=None, last_contacted_at=last_contacted)


def test_engine_excludes_each_arbzg_rule():
    staff = [
        _staff("HOSP-1059"),                                   # the person who is OUT -> never listed
        _staff("HOSP-2001", active=False),                     # on leave
        _staff("HOSP-2002", role="Pharmacist"),                # wrong role
        _staff("HOSP-2003", certs=("BLS",)),                   # missing ACLS
        _staff("HOSP-2004", grid_today="N"),                   # already on a night shift that day
        _staff("HOSP-2005", last_end=_dt(2026, 6, 20, 14, 0)), # 5h rest -> §5 fail
        _staff("HOSP-2006", sched=40.0, maxh=48.0),            # 40+12=52 > 48 -> §3 fail
        _staff("HOSP-2007"),                                   # fully eligible
    ]
    rep = shift_agent.screen_candidates(staff, _night_gap())
    elig_ids = {c.employee_id for c in rep.eligible}
    excl = {e.employee_id: e.rule for e in rep.excluded}
    assert "HOSP-1059" not in elig_ids and "HOSP-1059" not in excl       # the sick person is dropped entirely
    assert "HOSP-2007" in elig_ids
    assert excl["HOSP-2001"] == "active"
    assert excl["HOSP-2002"] == "role"
    assert excl["HOSP-2003"] == "certs"
    assert excl["HOSP-2004"] == "already_on_shift"
    assert excl["HOSP-2005"] == "rest_§5"
    assert excl["HOSP-2006"] == "weekly_cap_§3"
    # every exclusion carries a human reason that names the rule
    assert all(e.reason for e in rep.excluded)
    assert any("§5" in e.reason for e in rep.excluded)
    assert any("§3" in e.reason for e in rep.excluded)


def test_engine_ranks_fairly():
    # two eligible; the one with more headroom + never contacted should rank first
    a = _staff("HOSP-3001", sched=36.0, ot=False, last_contacted=_dt(2026, 6, 20, 9, 0))
    b = _staff("HOSP-3002", sched=12.0, ot=True, last_contacted=None)
    rep = shift_agent.screen_candidates([a, b], _night_gap())
    assert [c.employee_id for c in rep.eligible][0] == "HOSP-3002"
    assert rep.eligible[0].score >= rep.eligible[1].score
    assert rep.eligible[0].why  # reasons present


def test_charge_nurse_can_cover_rn_gap():
    cn = _staff("HOSP-4001", role="Charge Nurse")
    rep = shift_agent.screen_candidates([cn], _night_gap())
    assert {c.employee_id for c in rep.eligible} == {"HOSP-4001"}


def test_find_replacements_backcompat_shape():
    req = shift_agent.GapRequest(person_out="Felix Haddad (HOSP-1059)", role="Registered Nurse",
                                 department="ICU", shift="night", day_label="tonight",
                                 required_certs=["BLS", "ACLS"])
    res = shift_agent.find_replacements(req, top_n=3)
    assert isinstance(res, shift_agent.ShiftResult)
    assert res.role == "Registered Nurse" and res.shift_window == "19:00–07:00"
    assert res.candidates and res.candidates[0].why
    assert res.candidates[0].draft_message  # top picks get an outreach draft


# ---------------------------------------------------------------------------
# Task 3 — seed Staff from the hospital xlsx
# ---------------------------------------------------------------------------
from core.auth import get_or_create_tenant  # noqa: E402
from services import shift as shift_svc  # noqa: E402


def test_seed_staff_idempotent_and_parsed():
    tenant = get_or_create_tenant("test-uks", "Test UKS")
    n1 = shift_svc.seed_staff(tenant)
    n2 = shift_svc.seed_staff(tenant)          # re-seed must not duplicate
    assert n1 == n2 == 100
    from sqlmodel import select
    with Session(engine) as s:
        rows = s.exec(select(Staff).where(Staff.tenant_id == tenant)).all()
        assert len(rows) == 100
        felix = next(r for r in rows if r.employee_id == "HOSP-1059")
        assert felix.role == "Registered Nurse" and felix.department == "ICU"
        assert "ACLS" in felix.qualifications
        # an "— on shift —" person has last_shift_end set to today 19:00 (finishing a day shift)
        on_shift = [r for r in rows if r.last_shift_end == _dt(2026, 6, 20, 19, 0)]
        assert on_shift


# ---------------------------------------------------------------------------
# Task 4 — gap creation + screening service
# ---------------------------------------------------------------------------
_FELIX = dict(role="Registered Nurse", department="ICU", shift="night", day_label="Sat 06/20",
              required_certs=["BLS", "ACLS"], person_out="Felix Haddad (HOSP-1059)")


def test_create_and_screen_felix_gap():
    tenant = get_or_create_tenant("test-uks2", "Test UKS 2")
    shift_svc.seed_staff(tenant)
    gid = shift_svc.create_gap(tenant, structured=dict(_FELIX))
    rep = shift_svc.screen_gap(tenant, gid)
    assert rep.n_eligible >= 1
    # every eligible is within the weekly cap (the engine guarantees it)
    assert all(c.max_hours >= c.scheduled_hours + 12 for c in rep.eligible)
    # Felix himself is never offered his own shift
    assert all(c.employee_id != "HOSP-1059" for c in rep.eligible)
    # the board exposes excluded-with-reason
    assert rep.excluded and all(e.reason for e in rep.excluded)
    state = shift_svc.gap_state(tenant, gid)
    assert state["gap"]["status"] == "open" and state["eligible"]
