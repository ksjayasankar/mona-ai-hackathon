"""Import every model module so SQLModel.metadata is fully populated before
create_all / Alembic autogenerate."""
from core.models.intake import Applicant, AuditLog, IntakeRecord, Tenant  # noqa: F401
from core.models.shift import OutreachLog, ShiftGap, Staff  # noqa: F401
from core.models.fraud import Candidate, Certificate, VerificationRecord  # noqa: F401
from core.models.permit import PermitCheck, ReviewAction  # noqa: F401
from core.models.pricing import PriceRecommendation, PriceRun  # noqa: F401
from core.models.invoice import ApprovalAction, InvoiceRecord  # noqa: F401

__all__ = [
    "Tenant", "Applicant", "IntakeRecord", "AuditLog",
    "Staff", "ShiftGap", "OutreachLog",
    "Candidate", "Certificate", "VerificationRecord",
    "PermitCheck", "ReviewAction",
    "PriceRun", "PriceRecommendation",
    "InvoiceRecord", "ApprovalAction",
]
