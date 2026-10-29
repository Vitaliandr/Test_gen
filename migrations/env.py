from alembic import context
from sqlalchemy import create_engine

from sitegen import tables  # noqa: F401
from sitegen.database import Base
from sitegen.settings import settings

target_metadata = Base.metadata


def run_migrations() -> None:
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
