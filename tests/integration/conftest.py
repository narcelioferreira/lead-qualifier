"""Fixtures dos testes de integração com o Postgres real.

Cada módulo de teste ganha um banco descartável no mesmo servidor do `DATABASE_URL`, com as
migrations aplicadas, apagado no fim: o banco de desenvolvimento nunca é tocado.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    try:
        base = make_url(Settings().database_url.get_secret_value())
    except ValidationError as exc:
        pytest.skip(f".env incompleto: {exc.error_count()} erro(s)")
    admin_dsn = base.set(drivername="postgresql").render_as_string(hide_password=False)
    name = f"lead_qualifier_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres não está rodando (docker compose up -d postgres)")
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            yield base.set(database=name).render_as_string(hide_password=False)
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="module")
def migrated(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url
