from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from sitegen.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str]
    #draft/facts_approved/approved, сам считается из meta
    status: Mapped[str] = mapped_column(default="draft")
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    # отпечатки утверждений и результат проверки
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model: Mapped[str | None]
    cost: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    language: Mapped[str]
    style: Mapped[dict[str, Any]] = mapped_column(JSON)
    model: Mapped[str | None]
    #карточка на момент сборки, правки сайт не трогают
    source: Mapped[dict[str, Any]] = mapped_column(JSON)
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    cost: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
