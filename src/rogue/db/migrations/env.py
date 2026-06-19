# ruff: noqa: E402 — load_dotenv() must run BEFORE `from rogue.db.models import Base`
# because the models import path is sensitive to DATABASE_URL being set in env
# (and because alembic's config.set_main_option below reads it). This is the
# documented alembic env.py pattern; keep the deferred imports.

import os

from dotenv import load_dotenv

load_dotenv()

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from rogue.db.models import Base

config = context.config
if os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
if config.config_file_name is not None:
    # disable_existing_loggers=False preserves loggers that other modules
    # configured before alembic ran — without this, pytest's caplog stops
    # capturing records from `rogue.extract.extraction_agent` (and any other
    # project logger) the first time a test triggers `alembic.upgrade()`.
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
