from alembic import context
from sqlalchemy import create_engine, pool

from generationstation.config import Settings
from generationstation.storage import metadata

config = context.config
url = config.attributes.get("database_url")
if url is None:
    url = Settings().database_url.get_secret_value()
if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
        try:
            with engine.connect() as connection:
                context.configure(connection=connection, target_metadata=metadata)
                with context.begin_transaction():
                    context.run_migrations()
        finally:
            engine.dispose()
