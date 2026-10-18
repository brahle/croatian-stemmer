"""Fixtures for the PostgreSQL-backed web tests (synthetic data only)."""
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio

from labeling_support import alembic, close_api, database_url_for_tests, make_settings, open_api, plain


def _dsn():
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncpg")
    dsn = database_url_for_tests()
    if not dsn:
        pytest.skip("Set LABELING_TEST_DATABASE_URL to a migrated, isolated PostgreSQL test database")
    return dsn


def _admin(dsn, statement):
    import asyncpg

    async def run():
        connection = await asyncpg.connect(plain(dsn))
        try:
            await connection.execute(statement)
        finally:
            await connection.close()
    asyncio.run(run())


@pytest_asyncio.fixture
async def make_api():
    """make_api(**settings_changes) -> Api on a fresh app; skips without a test database."""
    dsn = _dsn()
    opened = []

    async def factory(**changes):
        settings = make_settings(dsn, **{"annotator_policy": "open", "role_source": "groups", **changes})
        api = await open_api(settings)
        opened.append(api)
        return api

    yield factory
    for api in opened:
        await close_api(api)


@pytest_asyncio.fixture
async def api(make_api):
    return await make_api()


@pytest.fixture
def scratch_database():
    """A throwaway, empty database next to the test database (needs CREATEDB), dropped afterwards."""
    dsn = _dsn()
    import asyncpg
    base, _ = dsn.rsplit("/", 1)
    name = f"labeling_guard_{uuid4().hex[:12]}_test"
    try:
        _admin(dsn, f'CREATE DATABASE "{name}"')
    except asyncpg.InsufficientPrivilegeError:
        pytest.skip("the test role cannot CREATE DATABASE; this test needs a scratch database")
    yield f"{base}/{name}"
    _admin(dsn, f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def migrated_template():
    """A database migrated to head once per session; fresh_api copies it."""
    dsn = _dsn()
    import asyncpg
    base, _ = dsn.rsplit("/", 1)
    name = f"labeling_tpl_{uuid4().hex[:12]}_test"
    try:
        _admin(dsn, f'CREATE DATABASE "{name}"')
    except asyncpg.InsufficientPrivilegeError:
        pytest.skip("the test role cannot CREATE DATABASE; this test needs an isolated database")
    url = f"{base}/{name}"
    migrated = alembic(url, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    yield dsn, name
    _admin(dsn, f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest_asyncio.fixture
async def fresh_api(migrated_template):
    """fresh_api(**settings_changes) -> Api on its own freshly migrated database.

    For tests of global state (scoring runs, readiness, anchors, settings), which the
    shared test database would mix with every other test's data."""
    dsn, template = migrated_template
    base, _ = dsn.rsplit("/", 1)
    created, opened = [], []

    async def factory(**changes):
        name = f"labeling_run_{uuid4().hex[:12]}_test"
        await asyncio.to_thread(_admin, dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
        created.append(name)
        settings = make_settings(f"{base}/{name}", **{"annotator_policy": "open", "role_source": "groups", **changes})
        api = await open_api(settings)
        opened.append(api)
        return api

    yield factory
    for api in opened:
        await close_api(api)
    for name in created:
        await asyncio.to_thread(_admin, dsn, f'DROP DATABASE "{name}" WITH (FORCE)')
