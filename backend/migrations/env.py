from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from app.config import settings
from app.db import Base
from app import models  # noqa: F401

target_metadata = Base.metadata
url = settings.migration_database_url or settings.database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True, connect_args={"connect_timeout": 10})
    with engine.connect() as connection:
        # Concurrent deploys must not apply DDL at the same time.
        connection.exec_driver_sql("SELECT pg_advisory_lock(98210421)")
        connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(98210421)")
            connection.commit()
    engine.dispose()
