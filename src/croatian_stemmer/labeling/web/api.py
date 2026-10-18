"""App factory, middleware and the authorization dependencies.

Every route declares one dependency that states who may call it:
  public            no token
  ctx.annotator_any a signed-in annotator, including a blocked one (data-subject rights only)
  ctx.annotator     a signed-in annotator that is not blocked
  ctx.consented     an annotator who accepted the current privacy notice, terms and
                    participation statement, confirming the minimum age
  ctx.curator       an annotator whose token carries the curator group/role
Routes live in routes_public.py, routes_annotator.py and routes_curator.py.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from . import routes_annotator, routes_curator, routes_public, routes_trust
from .auth import Authenticator
from .common import Caller, failure, scoring_params
from .config import MINIMUM_AGE, Settings
from .erasure import erase_profile, pending_erasure
from .legal import LegalDocuments
from .limits import Limiter
from .models import Annotator, Consent, ErasureRequest, Setting
from .scoring_run import moderation_tx, scheduled_tick

STATIC = Path(__file__).parent / "static"
DOCUMENTS = Path(__file__).parent / "documents"  # legal templates; not under /static
log = logging.getLogger("croatian_stemmer.labeling.web")


# Routes whose bodies may be large (a corpus or a gold import); serialized per worker.
LARGE_BODY_ROUTES = {("POST", "/api/import"), ("POST", "/api/admin/gold/import")}


class RequestBounds:
    """Bound bodies before JSON parsing; serialize large imports per worker."""
    def __init__(self, app):
        self.app = app
        self.imports = asyncio.Semaphore(1)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        importing = (scope["method"], scope["path"]) in LARGE_BODY_ROUTES
        limit = 32 * 1024 * 1024 if importing else 16384
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        async def too_large():
            return await JSONResponse({"detail": {"code": "body_too_large"}}, 413)(scope, receive, send)
        if length > limit:
            return await too_large()
        read = 0
        async def bounded_receive():
            nonlocal read
            message = await receive()
            read += len(message.get("body", b""))
            if read > limit:
                raise failure(413, "body_too_large")
            return message
        async def call():
            await self.app(scope, bounded_receive, send)
        if importing:
            async with self.imports:
                await call()
        else:
            await call()


class Context:
    """Per-app state shared by the route modules."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=3)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.auth = Authenticator(settings)
        self.limiter = Limiter()
        self.legal = LegalDocuments(settings, DOCUMENTS)
        self._accepting = None  # (value, monotonic time)
        self._serving = None  # (scoring params, monotonic time)
        self.scoring_pause = None  # tests: an async callable awaited between scoring and publication
        self.status_pause = None  # tests: awaited by the status route while it holds the annotator row
        self._build_dependencies()

    async def accepting_judgments(self, db) -> bool:
        """Kill switch: the environment override, else the setting (5 s cache)."""
        if self.settings.read_only:
            return False
        now = time.monotonic()
        if self._accepting is not None and now - self._accepting[1] < 5:
            return self._accepting[0]
        async with db.begin():
            value = (await db.execute(select(Setting.value).where(Setting.key == "accepting_judgments"))).scalar_one_or_none()
        accepting = value is None or value is True
        self._accepting = (accepting, now)
        return accepting

    async def serving_params(self, db) -> dict:
        """The scoring parameters the scheduler and admission read (5 s cache)."""
        now = time.monotonic()
        if self._serving is not None and now - self._serving[1] < 5:
            return self._serving[0]
        params = await scoring_params(db)
        self._serving = (params, now)
        return params

    def forget_settings(self):
        self._accepting = None
        self._serving = None

    def consent_missing(self):
        return failure(403, "consent_required", required=self.settings.required_documents)

    def consent_complete(self, rows) -> bool:
        """rows: (document, version, age_threshold). Every required document at its
        configured version, each accepted with the current minimum age."""
        accepted = {(document, version) for document, version, age in rows if age == MINIMUM_AGE}
        return set(self.settings.required_documents.items()) <= accepted

    def _build_dependencies(self):
        sessions, auth, settings = self.sessions, self.auth, self.settings

        async def session():
            async with sessions() as db:
                yield db

        async def annotator_any(request: Request, db=Depends(session)) -> Caller:
            principal = await auth.authenticate(request.headers.get("authorization"))
            async with db.begin():
                row = (await db.execute(select(Annotator.id, Annotator.status, Annotator.last_seen_at,
                                               func.now() - Annotator.last_seen_at)
                                        .where(Annotator.subject == principal.subject))).one_or_none()
                if row is None:
                    # An erased account keeps its Keycloak user for up to 30 days;
                    # signing in again meanwhile must not create a new profile.
                    pending = await pending_erasure(db, principal.subject)
                    if pending:
                        raise pending
                    await db.execute(insert(Annotator).values(
                        subject=principal.subject, email=principal.email,
                        email_verified=principal.email_verified).on_conflict_do_nothing(index_elements=[Annotator.subject]))
                    row = (await db.execute(select(Annotator.id, Annotator.status, Annotator.last_seen_at,
                                                   func.now() - Annotator.last_seen_at)
                                            .where(Annotator.subject == principal.subject))).one()
                elif row[3].total_seconds() > 600 and not await refresh_profile(db, row[0], principal):
                    # Erased since the SELECT above: never write the email back or go on as a stale caller.
                    raise await pending_erasure(db, principal.subject) or failure(409, "erasure_pending")
            return Caller(id=row[0], status=row[1], principal=principal)

        async def annotator(caller: Caller = Depends(annotator_any)) -> Caller:
            if caller.status == "blocked":
                raise failure(403, "account_blocked")
            return caller

        async def consented(caller: Caller = Depends(annotator), db=Depends(session)) -> Caller:
            async with db.begin():
                rows = (await db.execute(select(Consent.document, Consent.version, Consent.age_threshold).where(
                    Consent.annotator_id == caller.id))).all()
            if not self.consent_complete(rows):
                raise self.consent_missing()
            return caller

        async def curator(caller: Caller = Depends(annotator)) -> Caller:
            if not caller.curator:
                raise failure(403, "curator_required")
            return caller

        self.session, self.annotator_any, self.annotator = session, annotator_any, annotator
        self.consented, self.curator = consented, curator


async def refresh_profile(db, annotator_id, principal) -> bool:
    """Refresh last_seen_at and the email from the token, only while the row still
    belongs to this subject and is not erased (an erasure committed after the
    caller's SELECT wins). False when no row was updated."""
    result = await db.execute(
        update(Annotator).where(Annotator.id == annotator_id, Annotator.subject == principal.subject,
                                Annotator.status != "erased")
        .values(last_seen_at=func.now(), email=principal.email, email_verified=principal.email_verified)
        .execution_options(synchronize_session=False))
    return result.rowcount == 1


async def expire_unconsented_profiles(ctx, now: datetime | None = None, days=30):
    """Erase active profiles that never accepted the gate within `days` of their creation
    (storage limitation; the privacy notice states the 30 days). Each goes through the
    erasure path with no actor, which queues the Keycloak user for the curator.
    `now` is the clock (the database's when None); returns the erased ids."""
    cutoff = func.now() - func.make_interval(0, 0, 0, days) if now is None else now - timedelta(days=days)
    due = (Annotator.status == "active", Annotator.created_at < cutoff)
    async with ctx.sessions() as db:
        async with db.begin():
            candidates = (await db.execute(select(Annotator.id).where(
                *due, ~exists().where(Consent.annotator_id == Annotator.id)))).scalars().all()
        erased = []
        for annotator_id in candidates:
            async with db.begin():
                await moderation_tx(db)
                person = (await db.execute(select(Annotator).where(Annotator.id == annotator_id, *due)
                                           .with_for_update())).scalar_one_or_none()
                # Recheck with the row locked: a consent committed meanwhile keeps the profile
                # (the consent route share-locks this row while it writes).
                if person is None or (await db.execute(select(exists().where(
                        Consent.annotator_id == annotator_id)))).scalar_one():
                    continue
                await erase_profile(db, person, actor_id=None,
                                    details={"keycloak_user_id": person.subject, "reason": "unconsented_expiry"})
                erased.append(annotator_id)
    if erased:
        log.info("erased %d profiles that never accepted the gate within %d days", len(erased), days)
    return erased


async def warn_overdue_erasures(ctx, days=14):
    """Log (without identity) erasures whose Keycloak deletion is older than `days`."""
    async with ctx.sessions() as db:
        rows = (await db.execute(select(ErasureRequest.id, func.now() - ErasureRequest.requested_at).where(
            ErasureRequest.keycloak_deleted_at.is_(None),
            ErasureRequest.requested_at < func.now() - func.make_interval(0, 0, 0, days)))).all()
    for request_id, age in rows:
        log.warning("erasure request %s has waited %d days for Keycloak account deletion "
                    "(complete it within 30 days of the request)", request_id, age.days)
    return [request_id for request_id, _ in rows]


def create_app(settings: Settings) -> FastAPI:
    ctx = Context(settings)

    @asynccontextmanager
    async def lifespan(app):
        async def every(seconds, job, name):
            while True:
                try:
                    await job(ctx)
                except Exception:  # never let a background job take the app down
                    log.exception("%s failed", name)
                await asyncio.sleep(seconds)
        tasks = [asyncio.create_task(every(6 * 3600, warn_overdue_erasures, "erasure reminder")),
                 asyncio.create_task(every(24 * 3600, expire_unconsented_profiles, "unconsented profile expiry")),
                 asyncio.create_task(every(settings.scoring_interval_s, scheduled_tick, "scoring run"))]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await ctx.engine.dispose()

    # No interactive docs or schema on a public site: they list every route and model.
    app = FastAPI(title="Croatian stemmer labeling", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine, app.state.auth, app.state.ctx = ctx.engine, ctx.auth, ctx
    app.add_middleware(RequestBounds)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        # Same-origin only. The identity server is reached by top-level
        # navigation (sign-in) and fetch (token endpoint); no frames.
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "X-Robots-Tag": "noindex, nofollow",
                                 "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                                 "img-src 'self'; connect-src 'self' " + settings.identity_origin
                                 + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    routes_public.register(app, ctx)
    routes_annotator.register(app, ctx)
    routes_curator.register(app, ctx)
    routes_trust.register(app, ctx)
    return app
