"""Migrations must reproduce the ORM models exactly."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.database.base import Base

BACKEND = Path(__file__).resolve().parents[1]


def _upgrade_and_diff(url: str) -> list:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={url}"]})()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)


def test_migration_matches_models_sqlite(tmp_path):
    assert _upgrade_and_diff(f"sqlite:///{tmp_path / 'm.db'}") == []


@pytest.mark.postgres
def test_migration_matches_models_postgres():
    url = get_settings().database_url
    if not url or not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL not set to PostgreSQL")
    assert _upgrade_and_diff(url) == []
