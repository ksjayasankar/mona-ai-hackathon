"""p2 shift columns

Revision ID: p2shiftcols01
Revises: acc981dd630a
Create Date: 2026-06-20

Additive columns for the P2 UKS shift-replacement flagship. Batch ops keep SQLite happy.
"""
from alembic import op
import sqlalchemy as sa

revision = "p2shiftcols01"
down_revision = "acc981dd630a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("staff") as b:
        b.add_column(sa.Column("employee_id", sa.String(), nullable=True))
        b.add_column(sa.Column("contract", sa.String(), nullable=True))
        b.add_column(sa.Column("scheduled_hours_next7", sa.Float(), nullable=False, server_default="0"))
        b.add_column(sa.Column("shift_grid", sa.JSON(), nullable=True))
        b.add_column(sa.Column("overtime_ok", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("shift_preference", sa.String(), nullable=True))
        b.add_column(sa.Column("last_shift_end", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("last_contacted_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("persona", sa.String(), nullable=True))
        b.create_index("ix_staff_employee_id", ["employee_id"])

    with op.batch_alter_table("shiftgap") as b:
        b.add_column(sa.Column("person_out", sa.String(), nullable=True))
        b.add_column(sa.Column("shift_start", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("shift_end", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("shift_hours", sa.Float(), nullable=False, server_default="12"))
        b.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("filled_by_staff_id", sa.String(), nullable=True))
        b.add_column(sa.Column("filled_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("outreachlog") as b:
        b.add_column(sa.Column("seq", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("token", sa.String(), nullable=True))
        b.add_column(sa.Column("sent_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("responded_at", sa.DateTime(), nullable=True))
        b.create_index("ix_outreachlog_token", ["token"])
        b.create_index("ix_outreachlog_gap_id", ["gap_id"])


def downgrade() -> None:
    with op.batch_alter_table("outreachlog") as b:
        b.drop_index("ix_outreachlog_gap_id")
        b.drop_index("ix_outreachlog_token")
        for c in ("responded_at", "sent_at", "token", "seq"):
            b.drop_column(c)
    with op.batch_alter_table("shiftgap") as b:
        for c in ("filled_at", "filled_by_staff_id", "version", "shift_hours", "shift_end", "shift_start", "person_out"):
            b.drop_column(c)
    with op.batch_alter_table("staff") as b:
        b.drop_index("ix_staff_employee_id")
        for c in ("persona", "last_contacted_at", "last_shift_end", "shift_preference",
                  "overtime_ok", "shift_grid", "scheduled_hours_next7", "contract", "employee_id"):
            b.drop_column(c)
