import uuid

from sqlalchemy import CheckConstraint, Column, Integer, MetaData, String, Table, create_engine, event, select
from sqlalchemy.dialects.postgresql import insert

metadata = MetaData()
station = Table(
    "station", metadata,
    Column("id", Integer, primary_key=True),
    Column("instance_id", String(36), nullable=False),
    CheckConstraint("id = 1", name="station_singleton"),
)
models = Table(
    "models", metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("workload", String(40), nullable=False),
)


class Store:
    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url, pool_pre_ping=True, pool_size=2, max_overflow=2,
            pool_timeout=5, hide_parameters=True,
            connect_args={"connect_timeout": 5},
        )
        event.listen(self.engine, "connect", self._set_statement_timeout)

    @staticmethod
    def _set_statement_timeout(connection, record):
        # Keep queries bounded without replacing caller-supplied libpq options
        # such as search_path or TLS settings. Autocommit makes SET persist as a
        # session setting rather than leaving an implicit transaction open.
        previous_autocommit = connection.autocommit
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = 5000")
        finally:
            connection.autocommit = previous_autocommit

    def initialize(self) -> str:
        # Schema changes belong to Alembic, never implicit create_all at startup.
        with self.engine.begin() as conn:
            conn.execute(insert(station).values(id=1, instance_id=str(uuid.uuid4())).on_conflict_do_nothing())
            return conn.execute(select(station.c.instance_id).where(station.c.id == 1)).scalar_one()

    def list_models(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(models).order_by(models.c.name)).mappings()]

    def close(self):
        self.engine.dispose()
