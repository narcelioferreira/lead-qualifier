"""Engine e sessões do Postgres (SQLAlchemy assíncrono com psycopg 3)."""

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: SecretStr) -> AsyncEngine:
    # `hide_parameters`: valores das queries (texto do lead) não aparecem em logs nem exceções.
    return create_async_engine(
        database_url.get_secret_value(),
        hide_parameters=True,
        pool_pre_ping=True,
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
