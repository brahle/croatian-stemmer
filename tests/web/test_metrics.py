"""Prometheus metrics (0.3.1): a second listener only, aggregate values only, and the
values an alert needs (scoring state and runs, background jobs, erasure deadline,
quarantines)."""
import asyncio
import re

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, make_settings, profiled, score_now, scoring_on

from croatian_stemmer.labeling.web import metrics as metrics_module
from croatian_stemmer.labeling.web.config import Settings
from croatian_stemmer.labeling.web.metrics import Metrics, render

SAMPLE = re.compile(r'^([a-z_]+)(\{[a-z_]+="[A-Za-z0-9._-]*"(,[a-z_]+="[A-Za-z0-9._-]*")*\})? (-?[0-9.e+]+)$')
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def parse(body):
    """{name{labels}: value}, checking every line is valid exposition text."""
    values, typed = {}, set()
    for line in body.splitlines():
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ")
            assert kind in ("gauge", "counter") and name not in typed
            typed.add(name)
            continue
        if line.startswith("# HELP "):
            continue
        match = SAMPLE.match(line)
        assert match, line
        assert match.group(1) in typed, line
        values[match.group(1) + (match.group(2) or "")] = float(match.group(4))
    return values


@pytest.mark.parametrize("port", [-1, 1, 80, 1023, 65536, "9464"])
def test_the_metrics_port_is_off_or_unprivileged(port):
    assert make_settings().metrics_port == 0
    with pytest.raises(ValueError):
        make_settings(metrics_port=port)


def test_the_metrics_settings_from_the_environment(monkeypatch):
    base = {"LABELING_DATABASE_URL": "postgresql+asyncpg://t@localhost/x_test",
            "LABELING_OIDC_ISSUER": "https://id.example.org/realms/r", "LABELING_CONTROLLER_NAME": "C",
            "LABELING_CONTROLLER_EMAIL": "c@example.org", "LABELING_HOSTING_SUMMARY": "h",
            "LABELING_EDGE_LOG_RETENTION": "e", "LABELING_BACKUP_RETENTION": "b"}
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    assert Settings.from_environment().metrics_port == 0
    monkeypatch.setenv("LABELING_METRICS_PORT", "9464")
    monkeypatch.setenv("LABELING_METRICS_HOST", "127.0.0.1")
    settings = Settings.from_environment()
    assert (settings.metrics_port, settings.metrics_host) == (9464, "127.0.0.1")
    monkeypatch.setenv("LABELING_METRICS_HOST", "metrics.example.org")
    with pytest.raises(ValueError):
        Settings.from_environment()


def test_render_without_the_database():
    m = Metrics("0.3.1")
    m.run("timed_out")
    m.job("retention", ok=True)
    m.job("unconsented_expiry", ok=False)
    values = parse(render(m, None))
    assert values['labeling_scoring_runs_total{outcome="timed_out"}'] == 1
    assert values['labeling_metrics_database_up'] == 0 and "labeling_scoring_enabled" not in values
    assert 'labeling_job_last_success_timestamp_seconds{job="retention"}' in values
    assert 'labeling_job_last_success_timestamp_seconds{job="unconsented_expiry"}' not in values
    assert values['labeling_job_failures_total{job="unconsented_expiry"}'] == 1
    assert values['labeling_build_info{version="0.3.1"}'] == 1


@pytest.mark.asyncio
async def test_the_public_app_has_no_metrics(api):
    for path in ("/metrics", "/api/metrics", "/static/../metrics"):
        r = await api.client.get(path)
        assert r.status_code == 404 and "labeling_" not in r.text, path


@pytest.mark.asyncio
async def test_the_values_an_alert_needs(fresh_api):
    api = await fresh_api()
    ctx = api.app.state.ctx
    values = parse(await metrics_module.exposition(ctx))
    assert values["labeling_metrics_database_up"] == 1 and values["labeling_scoring_enabled"] == 0
    assert "labeling_scoring_seconds_since_last_success" not in values  # only while scoring is on
    assert values["labeling_erasure_requests_pending"] == 0
    assert values["labeling_erasure_request_oldest_pending_age_seconds"] == 0
    assert values["labeling_annotators_quarantined"] == 0 and values["labeling_scoring_runs_in_progress"] == 0

    rows = await api.imported(candidates(pairs=3))
    for name in ("alice", "bob"):
        await profiled(api, name)
        root = f'/api/corpora/{rows[0]["corpus_id"]}'
        item = (await api.request("GET", root + "/next", name)).json()["item"]
        assert (await api.request("POST", answer_path(item["candidate"]), name, json=answer())).status_code == 200
    await scoring_on(api)
    enabled = parse(await metrics_module.exposition(ctx))
    assert enabled["labeling_scoring_enabled"] == 1
    assert 0 <= enabled["labeling_scoring_seconds_since_last_success"] < 60  # since the switch, no run yet
    [(run_id, status)] = await score_now(api)
    assert status == "done"
    from croatian_stemmer.labeling.web.scoring_run import scheduled_tick
    assert await scheduled_tick(ctx) is None  # nothing changed: skipped
    # A person set aside, and an erasure request waiting 20 days for the identity provider.
    alice = await api.annotator_id("alice")
    await api.sql("UPDATE label_annotator SET status = 'quarantined' WHERE id = :a", a=alice)
    assert (await api.request("POST", "/api/me/erase", "bob", json={"confirm": "DELETE"})).status_code == 200
    await api.sql("UPDATE label_erasure_request SET requested_at = now() - interval '20 days'")
    body = await metrics_module.exposition(ctx)
    values = parse(body)
    assert values['labeling_scoring_runs_total{outcome="success"}'] == 1
    assert values['labeling_scoring_runs_total{outcome="skipped"}'] == 1
    finished = (await api.sql("SELECT extract(epoch FROM finished_at) FROM label_scoring_run WHERE id = :r",
                              r=run_id)).scalar_one()
    assert values['labeling_scoring_last_run_finish_timestamp_seconds{status="done"}'] == pytest.approx(
        float(finished), abs=1e-3)
    assert values["labeling_scoring_last_success_timestamp_seconds"] == pytest.approx(float(finished), abs=1e-3)
    assert 0 <= values["labeling_scoring_seconds_since_last_success"] < 60
    assert values["labeling_annotators_quarantined"] == 1
    assert values["labeling_erasure_requests_pending"] == 1
    assert 20 * 86400 - 60 < values["labeling_erasure_request_oldest_pending_age_seconds"] < 20 * 86400 + 60
    # Aggregates only: no identifier, email or subject anywhere in the text.
    assert not UUID.search(body) and "@" not in body and "alice" not in body and "bob" not in body


@pytest.mark.asyncio
async def test_failed_and_timed_out_runs_are_counted(fresh_api, monkeypatch):
    api = await fresh_api()
    ctx = api.app.state.ctx
    from croatian_stemmer.labeling.web import scoring_run

    def slow(inputs, params):
        raise asyncio.TimeoutError()  # what asyncio.wait_for raises at LABELING_SCORING_RUN_TIMEOUT

    monkeypatch.setattr(scoring_run, "score", slow)
    with pytest.raises(asyncio.TimeoutError):
        await score_now(api)

    def broken(inputs, params):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(scoring_run, "score", broken)
    with pytest.raises(RuntimeError):
        await score_now(api)
    values = parse(await metrics_module.exposition(ctx))
    assert values['labeling_scoring_runs_total{outcome="timed_out"}'] == 1
    assert values['labeling_scoring_runs_total{outcome="failed"}'] == 1
    assert values['labeling_scoring_last_run_finish_timestamp_seconds{status="failed"}'] > 0
    assert "labeling_scoring_last_success_timestamp_seconds" not in values


@pytest.mark.asyncio
async def test_the_listener_serves_only_get_metrics(api):
    server = await metrics_module.serve(api.app.state.ctx, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def call(request):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        response = await reader.read()
        writer.close()
        return response.decode()

    try:
        ok = await call(b"GET /metrics HTTP/1.1\r\nHost: x\r\n\r\n")
        head, body = ok.split("\r\n\r\n", 1)
        assert head.startswith("HTTP/1.1 200") and "text/plain; version=0.0.4" in head
        assert parse(body)["labeling_metrics_database_up"] == 1
        assert (await call(b"GET / HTTP/1.1\r\n\r\n")).startswith("HTTP/1.1 404")
        assert (await call(b"GET /api/me HTTP/1.1\r\n\r\n")).startswith("HTTP/1.1 404")
        assert (await call(b"POST /metrics HTTP/1.1\r\n\r\n")).startswith("HTTP/1.1 405")
        assert (await call(b"HEAD /metrics HTTP/1.1\r\n\r\n")).split("\r\n\r\n", 1)[1] == ""
        assert await call(b"GET /metrics HTTP/1.1\r\n" + b"X: " + b"a" * 9000 + b"\r\n\r\n") == ""  # oversized head
    finally:
        server.close()
        await server.wait_closed()
