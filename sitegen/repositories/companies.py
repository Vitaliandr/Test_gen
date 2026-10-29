#коммитит сервис, тут нет
from sqlalchemy import select
from sqlalchemy.orm import Session

from sitegen.tables import Company


def get(session: Session, company_id: int) -> Company | None:
    return session.get(Company, company_id)


def all_items(session: Session) -> list[Company]:
    return list(session.scalars(select(Company).order_by(Company.id.desc())))


def add(session: Session, company: Company) -> None:
    session.add(company)


def delete(session: Session, company: Company) -> None:
    session.delete(company)
