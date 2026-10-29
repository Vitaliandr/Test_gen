"""companies and sites

Revision ID: 001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brand", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("params", sa.JSON, nullable=False),
        sa.Column("model", sa.String),
        sa.Column("cost", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("language", sa.String, nullable=False),
        sa.Column("style", sa.JSON, nullable=False),
        sa.Column("model", sa.String),
        sa.Column("source", sa.JSON, nullable=False),
        sa.Column("report", sa.JSON, nullable=False),
        sa.Column("cost", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sites")
    op.drop_table("companies")
