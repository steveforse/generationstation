"""PostgreSQL-only migration and persistence checks.

Set GS_TEST_DATABASE_URL to a disposable PostgreSQL database. A random schema is
created and dropped inside it; this suite never uses SQLite as a substitute.
"""
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, inspect, text
from sqlalchemy.engine import make_url

from generationstation.storage import Store, models

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.database
def test_postgresql_migration_and_store_round_trip():
    database_url = os.environ.get("GS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set GS_TEST_DATABASE_URL to run disposable PostgreSQL integration checks")

    parsed = make_url(database_url)
    if parsed.drivername != "postgresql+psycopg":
        pytest.skip("GS_TEST_DATABASE_URL must use postgresql+psycopg")

    schema = "gs_test_" + uuid.uuid4().hex
    admin_engine = create_engine(database_url, pool_pre_ping=True, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        isolated_url = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
        migration_engine = create_engine(isolated_url, hide_parameters=True)
        try:
            with migration_engine.connect() as connection:
                config = Config(str(BACKEND / "alembic.ini"))
                config.attributes["connection"] = connection
                config.attributes["database_url"] = isolated_url.render_as_string(hide_password=False)
                command.upgrade(config, "head")

            store = Store(isolated_url.render_as_string(hide_password=False))
            try:
                instance_id = store.initialize()
                assert uuid.UUID(instance_id)
                assert store.list_models() == []

                def assert_timeout_persists_after_rollback():
                    with store.engine.connect() as connection:
                        assert connection.exec_driver_sql("SHOW statement_timeout").scalar_one() == "5s"
                        connection.rollback()
                        assert connection.exec_driver_sql("SHOW statement_timeout").scalar_one() == "5s"

                assert_timeout_persists_after_rollback()
                store.engine.dispose()
                assert_timeout_persists_after_rollback()
                with store.engine.begin() as connection:
                    connection.execute(insert(models).values(
                        id="postgres-round-trip", name="Round trip", workload="test",
                    ))
                names = set(inspect(migration_engine).get_table_names(schema=schema))
                assert names >= {"station", "models", "alembic_version"}
            finally:
                store.close()

            reopened_store = Store(isolated_url.render_as_string(hide_password=False))
            try:
                assert reopened_store.initialize() == instance_id
                assert reopened_store.list_models() == [{
                    "id": "postgres-round-trip", "name": "Round trip", "workload": "test",
                }]
            finally:
                reopened_store.close()

            with migration_engine.connect() as connection:
                config = Config(str(BACKEND / "alembic.ini"))
                config.attributes["connection"] = connection
                config.attributes["database_url"] = isolated_url.render_as_string(hide_password=False)
                command.downgrade(config, "base")
            remaining = set(inspect(migration_engine).get_table_names(schema=schema))
            assert not remaining.intersection({"station", "models"})
        finally:
            migration_engine.dispose()
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
