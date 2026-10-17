"""Run schema migrations against the explicitly configured PostgreSQL store."""
import asyncio
import os
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from croatian_stemmer.labeling.web.models import Base

url = os.environ["LABELING_DATABASE_URL"]
if not url.startswith("postgresql+asyncpg://"):
    raise ValueError("LABELING_DATABASE_URL must use PostgreSQL/asyncpg")

def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

async def online():
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
