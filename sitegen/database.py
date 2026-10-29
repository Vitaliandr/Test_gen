from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sitegen.settings import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    args: dict[str, object] = {}
    if url.startswith("sqlite"):
        db_file = make_url(url).database
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        #фоновые задачи пишут из другого потока
        args["check_same_thread"] = False
    return create_engine(url, connect_args=args)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
