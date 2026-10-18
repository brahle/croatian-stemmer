"""Prometheus metrics for alerting, on a listener of their own.

The public app never serves /metrics. When LABELING_METRICS_PORT is set, the lifespan
starts a second, plain-HTTP listener on that port (LABELING_METRICS_HOST, default all
interfaces) that answers only `GET /metrics` in the Prometheus text format 0.0.4. The
ingress routes to the app's port (8000), so the metrics stay off the public hostname
unless someone deliberately routes the second port; scrape it from inside the cluster
(a pod or service monitor on that port). No dependency beyond the standard library.

Every value is an aggregate: no annotator id, email, item or corpus appears in a label
or a value. Database gauges are read at scrape time (bounded by a statement timeout);
counters and job timestamps are in process and start again at a restart (Prometheus
handles counter resets; alert rules should allow for an absent job timestamp in the
first hours after a start, see docs/labeling-web.md).
"""

import asyncio
import logging
import time

from sqlalchemy import text

log = logging.getLogger("croatian_stemmer.labeling.web.metrics")

RUN_OUTCOMES = ("success", "superseded", "failed", "timed_out", "skipped")
JOBS = ("scoring", "retention", "unconsented_expiry", "erasure_reminder")
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """In-process counters and timestamps; one per app."""

    def __init__(self, version: str):
        self.version = version
        self.started = time.time()
        self.runs = {outcome: 0 for outcome in RUN_OUTCOMES}
        self.job_success = {}  # job -> unix time of its last successful pass
        self.job_failures = {job: 0 for job in JOBS}

    def run(self, outcome: str):
        self.runs[outcome] += 1

    def job(self, name: str, ok: bool):
        if ok:
            self.job_success[name] = time.time()
        else:
            self.job_failures[name] += 1


SNAPSHOT = text("""
SELECT
  (SELECT value FROM label_setting WHERE key = 'scoring_enabled') = 'true'::jsonb AS enabled,
  extract(epoch FROM (SELECT updated_at FROM label_setting WHERE key = 'scoring_enabled')) AS enabled_at,
  extract(epoch FROM (SELECT max(finished_at) FROM label_scoring_run WHERE status = 'done')) AS last_success,
  (SELECT extract(epoch FROM finished_at) FROM label_scoring_run WHERE finished_at IS NOT NULL
     ORDER BY finished_at DESC, id LIMIT 1) AS last_finished,
  (SELECT status FROM label_scoring_run WHERE finished_at IS NOT NULL
     ORDER BY finished_at DESC, id LIMIT 1) AS last_status,
  (SELECT count(*) FROM label_scoring_run WHERE status = 'running') AS running,
  (SELECT count(*) FROM label_erasure_request WHERE keycloak_deleted_at IS NULL) AS erasures,
  extract(epoch FROM (SELECT min(requested_at) FROM label_erasure_request WHERE keycloak_deleted_at IS NULL))
    AS oldest_erasure,
  (SELECT count(*) FROM label_annotator WHERE status = 'quarantined') AS quarantined,
  extract(epoch FROM now()) AS now
""")


async def snapshot(ctx) -> dict:
    """The database side of a scrape, in one read-only transaction."""
    async with ctx.engine.connect() as connection:
        async with connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            row = (await connection.execute(SNAPSHOT)).one()
    return dict(row._mapping)


def render(metrics: Metrics, db: dict | None) -> str:
    """The exposition text. `db` is None when the database could not be read."""
    lines = []

    def metric(name, kind, help_, samples):
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            label = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
            lines.append(f"{name}{label} {_number(value)}")

    metric("labeling_build_info", "gauge", "The running release.", [({"version": metrics.version}, 1)])
    metric("labeling_process_start_time_seconds", "gauge", "When this process started (unix time).",
           [({}, metrics.started)])
    metric("labeling_scoring_runs_total", "counter",
           "Scoring runs by outcome since the process started; skipped counts scheduled ticks that did not run.",
           [({"outcome": outcome}, metrics.runs[outcome]) for outcome in RUN_OUTCOMES])
    metric("labeling_job_last_success_timestamp_seconds", "gauge",
           "When a background job last completed without an error (unix time); absent until its first pass.",
           [({"job": job}, metrics.job_success[job]) for job in JOBS if job in metrics.job_success])
    metric("labeling_job_failures_total", "counter", "Background job passes that raised, since the process started.",
           [({"job": job}, metrics.job_failures[job]) for job in JOBS])
    metric("labeling_metrics_database_up", "gauge", "1 when this scrape could read the database.",
           [({}, 0 if db is None else 1)])
    if db is not None:
        enabled = bool(db["enabled"])
        metric("labeling_scoring_enabled", "gauge", "1 when the curator has switched trust scoring on.",
               [({}, int(enabled))])
        metric("labeling_scoring_runs_in_progress", "gauge",
               "Scoring runs in status running (a row left running by a crashed process counts too).",
               [({}, db["running"])])
        if db["last_finished"] is not None:
            metric("labeling_scoring_last_run_finish_timestamp_seconds", "gauge",
                   "When the latest finished scoring run finished (unix time), labelled by its status.",
                   [({"status": db["last_status"]}, db["last_finished"])])
        if db["last_success"] is not None:
            metric("labeling_scoring_last_success_timestamp_seconds", "gauge",
                   "When the latest done scoring run finished (unix time).", [({}, db["last_success"])])
        since = [v for v in (db["last_success"], db["enabled_at"]) if v is not None]
        if enabled and since:
            metric("labeling_scoring_seconds_since_last_success", "gauge",
                   "While scoring is on: seconds since the later of the latest done run and the "
                   "last write of the scoring switch.", [({}, max(0.0, db["now"] - max(since)))])
        metric("labeling_erasure_requests_pending", "gauge",
               "Erasure requests whose identity-provider deletion is not yet confirmed.", [({}, db["erasures"])])
        metric("labeling_erasure_request_oldest_pending_age_seconds", "gauge",
               "Age of the oldest pending erasure request (0 when none); the privacy notice promises 30 days.",
               [({}, max(0.0, db["now"] - db["oldest_erasure"]) if db["oldest_erasure"] is not None else 0)])
        metric("labeling_annotators_quarantined", "gauge", "Annotators currently set aside (quarantined).",
               [({}, db["quarantined"])])
    return "\n".join(lines) + "\n"


def _number(value) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 2 ** 53 else repr(value)


async def exposition(ctx) -> str:
    try:
        db = await snapshot(ctx)
    except Exception:
        log.exception("metrics: could not read the database")
        db = None
    return render(ctx.metrics, db)


async def serve(ctx, host: str, port: int):
    """Start the metrics listener; returns the asyncio server (close it at shutdown)."""

    async def handle(reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
            parts = request_line.split(" ")
            method, target = (parts[0], parts[1]) if len(parts) == 3 else ("", "")
            path = target.split("?", 1)[0]
            if path != "/metrics":
                status, body, kind = "404 Not Found", b"not found\n", "text/plain; charset=utf-8"
            elif method not in ("GET", "HEAD"):
                status, body, kind = "405 Method Not Allowed", b"method not allowed\n", "text/plain; charset=utf-8"
            else:
                status, body, kind = "200 OK", (await exposition(ctx)).encode("utf-8"), CONTENT_TYPE
            writer.write((f"HTTP/1.1 {status}\r\nContent-Type: {kind}\r\nContent-Length: {len(body)}\r\n"
                          f"Cache-Control: no-store\r\nConnection: close\r\n\r\n").encode("latin-1"))
            if method != "HEAD":
                writer.write(body)
            await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            pass
        finally:
            writer.close()

    # limit bounds a request head; a scrape's is a few hundred bytes.
    return await asyncio.start_server(handle, host, port, limit=8192)
