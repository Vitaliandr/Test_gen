from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sitegen.tables import Site


def get(session: Session, site_id: int) -> Site | None:
    return session.get(Site, site_id)


def all_items(session: Session, company_id: int | None = None) -> list[Site]:
    query = select(Site).order_by(Site.id.desc())
    if company_id is not None:
        query = query.where(Site.company_id == company_id)
    return list(session.scalars(query))


def version(session: Session, site: Site) -> int:
    #id общий на все компании, версию считаем внутри одной
    query = select(func.count()).where(Site.company_id == site.company_id, Site.id <= site.id)
    return int(session.scalar(query) or 0)


def add(session: Session, site: Site) -> None:
    session.add(site)


def delete(session: Session, site: Site) -> None:
    session.delete(site)
