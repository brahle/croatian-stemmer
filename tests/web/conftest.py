"""Fixtures for the PostgreSQL-backed web tests (synthetic data only)."""
import pytest
import pytest_asyncio

from labeling_support import close_api, database_url_for_tests, make_settings, open_api


@pytest_asyncio.fixture
async def make_api():
    """make_api(**settings_changes) -> Api on a fresh app; skips without a test database."""
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncpg")
    dsn = database_url_for_tests()
    if not dsn:
        pytest.skip("Set LABELING_TEST_DATABASE_URL to a migrated, isolated PostgreSQL test database")
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
