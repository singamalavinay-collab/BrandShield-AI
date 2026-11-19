import asyncio
from logging.config import fileConfig
import os
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.models import Base

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model MetaData for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    """Return database connection URL for migrations with strict precedence:
    1. os.environ['MIGRATION_DATABASE_URL'] (Administrative connection for production/staging migrations)
    2. settings.MIGRATION_DATABASE_URL (Pydantic loaded setting from environment)
    3. config.get_main_option('sqlalchemy.url') (Programmatic test runner option for SQLite fixtures)
    4. os.environ['DATABASE_URL'] or settings.DATABASE_URL (Development fallback)
    """
    env_mig_url = os.getenv("MIGRATION_DATABASE_URL")
    if env_mig_url and env_mig_url.strip():
        return env_mig_url.strip()

    settings_mig_url = getattr(settings, "MIGRATION_DATABASE_URL", None)
    if settings_mig_url and str(settings_mig_url).strip():
        return str(settings_mig_url).strip()

    cfg_url = config.get_main_option("sqlalchemy.url")
    if cfg_url and cfg_url.strip() and not cfg_url.strip().startswith("%(here)s"):
        return cfg_url.strip()

    return os.getenv("DATABASE_URL", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    url = get_url()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
