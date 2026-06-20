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
