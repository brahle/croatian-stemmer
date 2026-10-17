"""App factory, middleware and the authorization dependencies.

Every route declares one dependency that states who may call it:
  public            no token
  ctx.annotator_any a signed-in annotator, including a blocked one (data-subject rights only)
  ctx.annotator     a signed-in annotator that is not blocked
  ctx.consented     an annotator who accepted the current privacy notice and terms
  ctx.curator       an annotator whose token carries the curator group/role
Routes live in routes_public.py, routes_annotator.py and routes_curator.py.
"""

import asyncio
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from . import routes_annotator, routes_curator, routes_public
from .auth import Authenticator
from .common import Caller, failure
from .config import Settings
from .legal import LegalDocuments
from .limits import Limiter
from .models import Annotator, Consent, ErasureRequest, Setting

STATIC = Path(__file__).parent / "static"
DOCUMENTS = Path(__file__).parent / "documents"  # legal templates; not under /static
log = logging.getLogger("croatian_stemmer.labeling.web")


class RequestBounds:
    """Bound bodies before JSON parsing; serialize large imports per worker."""
    def __init__(self, app):
        self.app = app
        self.imports = asyncio.Semaphore(1)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        importing = scope["path"] == "/api/import" and scope["method"] == "POST"
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

    def forget_settings(self):
        self._accepting = None

    def consent_missing(self):
        return failure(403, "consent_required", required={"privacy": self.settings.privacy_version,
                                                           "terms": self.settings.terms_version})

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
                    digest = hashlib.sha256(principal.subject.encode()).hexdigest()
                    pending = (await db.execute(select(func.count()).select_from(ErasureRequest).where(
                        ErasureRequest.subject_sha256 == digest,
                        ErasureRequest.keycloak_deleted_at.is_(None)))).scalar_one()
                    if pending:
                        raise failure(409, "erasure_pending")
                    await db.execute(insert(Annotator).values(
                        subject=principal.subject, email=principal.email,
                        email_verified=principal.email_verified).on_conflict_do_nothing(index_elements=[Annotator.subject]))
                    row = (await db.execute(select(Annotator.id, Annotator.status, Annotator.last_seen_at,
                                                   func.now() - Annotator.last_seen_at)
                                            .where(Annotator.subject == principal.subject))).one()
                elif row[3].total_seconds() > 600:
                    await db.execute(update(Annotator).where(Annotator.id == row[0]).values(
                        last_seen_at=func.now(), email=principal.email, email_verified=principal.email_verified))
            return Caller(id=row[0], status=row[1], principal=principal)

        async def annotator(caller: Caller = Depends(annotator_any)) -> Caller:
            if caller.status == "blocked":
                raise failure(403, "account_blocked")
            return caller

        async def consented(caller: Caller = Depends(annotator), db=Depends(session)) -> Caller:
            async with db.begin():
                accepted = set((await db.execute(select(Consent.document, Consent.version).where(
                    Consent.annotator_id == caller.id))).all())
            if not {("privacy", settings.privacy_version), ("terms", settings.terms_version)} <= accepted:
                raise self.consent_missing()
            return caller

        async def curator(caller: Caller = Depends(annotator)) -> Caller:
            if not caller.curator:
                raise failure(403, "curator_required")
            return caller

        self.session, self.annotator_any, self.annotator = session, annotator_any, annotator
        self.consented, self.curator = consented, curator


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
        async def watch():
            while True:
                try:
                    await warn_overdue_erasures(ctx)
                except Exception:  # never let the reminder take the app down
                    log.exception("erasure reminder failed")
                await asyncio.sleep(6 * 3600)
        task = asyncio.create_task(watch())
        try:
            yield
        finally:
            task.cancel()
            await ctx.engine.dispose()

    app = FastAPI(title="Croatian stemmer labeling", lifespan=lifespan)
    app.state.engine, app.state.auth, app.state.ctx = ctx.engine, ctx.auth, ctx
    app.add_middleware(RequestBounds)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        # Same-origin only. The identity server is reached by top-level
        # navigation (sign-in) and fetch (token endpoint); no frames.
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                                 "img-src 'self'; connect-src 'self' " + settings.identity_origin
                                 + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    routes_public.register(app, ctx)
    routes_annotator.register(app, ctx)
    routes_curator.register(app, ctx)
    return app
