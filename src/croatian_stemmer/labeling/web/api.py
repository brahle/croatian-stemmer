"""Subject-scoped human labeling API and static Croatian interface."""

import asyncio
import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import and_, case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .auth import Authenticator
from .config import Settings
from .models import Corpus, Item, Judgment
from .requests import AnswerRequest, Candidate, ImportRequest

STATIC = Path(__file__).parent / "static"


def failure(status, code, **values):
    return HTTPException(status, detail={"code": code, **values})


def corpus_json(corpus):
    return {"id": str(corpus.id), "name": corpus.name, "sha256": corpus.sha256,
            "source_uri": corpus.source_uri, "license": corpus.license,
            "created_at": corpus.created_at.isoformat()}


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


def create_app(settings: Settings) -> FastAPI:
    engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=3)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    auth = Authenticator(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.dispose()

    app = FastAPI(title="Croatian stemmer labeling", lifespan=lifespan)
    app.state.engine, app.state.auth = engine, auth
    app.add_middleware(RequestBounds)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                                 "img-src 'self'; connect-src 'self' " + settings.identity_origin + "; frame-src "
                                 + settings.identity_origin + "; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    async def owner(request: Request):
        return await auth.authenticate(request.headers.get("authorization"))

    async def session():
        async with sessions() as db:
            yield db

    async def owned_corpus(db, subject, corpus_id):
        row = (await db.execute(select(Corpus).where(Corpus.owner_id == subject, Corpus.id == corpus_id))).scalar_one_or_none()
        if row is None:
            raise failure(404, "not_found")
        return row

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/readyz")
    async def ready(db=Depends(session)):
        try:
            await db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise failure(503, "database_unavailable") from exc
        return {"ok": True}

    @app.get("/api/config")
    async def public_config():
        return settings.browser

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/corpora")
    async def corpora(offset: int = Query(0, ge=0, le=2**31 - 1), subject=Depends(owner), db=Depends(session)):
        rows = (await db.execute(select(Corpus).where(Corpus.owner_id == subject).order_by(Corpus.created_at, Corpus.id).offset(offset).limit(101))).scalars().all()
        return {"items": [corpus_json(row) for row in rows[:100]],
                "next_offset": offset + 100 if len(rows) > 100 else None}

    @app.post("/api/import")
    async def import_candidates(request: Request, subject=Depends(owner), db=Depends(session)):
        try:
            data = ImportRequest.model_validate_json(await request.body())
        except ValidationError as exc:
            raise failure(422, "invalid_candidates") from exc
        first = data.candidates[0]
        unique = {row.item_id: row for row in data.candidates}
        async with db.begin():
            await db.execute(insert(Corpus).values(owner_id=subject, id=first.corpus_id, name=data.name,
                             sha256=first.corpus_sha256, source_uri=first.source_uri, license=first.license)
                             .on_conflict_do_nothing(index_elements=[Corpus.owner_id, Corpus.id]))
            corpus = (await db.execute(select(Corpus).where(Corpus.owner_id == subject, Corpus.id == first.corpus_id).with_for_update())).scalar_one()
            if (corpus.sha256, corpus.source_uri, corpus.license) != (first.corpus_sha256, first.source_uri, first.license):
                raise failure(409, "corpus_provenance_conflict")
            existing = set()
            ids = list(unique)
            for start in range(0, len(ids), 1000):
                found = (await db.execute(select(Item.id, Item.payload).where(Item.owner_id == subject,
                          Item.corpus_id == corpus.id, Item.id.in_(ids[start:start + 1000])))).all()
                for item_id, payload in found:
                    if Candidate.model_validate(payload).question != unique[item_id].question:
                        raise failure(409, "immutable_item_conflict")
                    existing.add(item_id)
            ordinal = (await db.execute(select(func.max(Item.ordinal)).where(Item.owner_id == subject,
                                       Item.corpus_id == corpus.id))).scalar_one()
            ordinal = 0 if ordinal is None else ordinal + 1
            batch, added = [], 0
            for item_id, candidate in unique.items():
                if item_id in existing:
                    continue
                batch.append({"owner_id": subject, "corpus_id": corpus.id, "id": item_id,
                              "ordinal": ordinal + added, "kind": candidate.kind,
                              "payload": candidate.model_dump(mode="json"), "current_revision": 0})
                added += 1
                if len(batch) == 1000:
                    await db.execute(insert(Item), batch)
                    batch.clear()
            if batch:
                await db.execute(insert(Item), batch)
        return {"corpus": corpus_json(corpus), "added": added, "already_present": len(existing)}

    latest_join = and_(Judgment.owner_id == Item.owner_id, Judgment.corpus_id == Item.corpus_id,
                       Judgment.item_id == Item.id, Judgment.revision == Item.current_revision)

    @app.get("/api/corpora/{corpus_id}/progress")
    async def progress(corpus_id: UUID, subject=Depends(owner), db=Depends(session)):
        await owned_corpus(db, subject, corpus_id)
        rows = (await db.execute(select(Item.kind, func.count(Item.id),
                func.sum(case((Item.current_revision > 0, 1), else_=0)),
                func.sum(case((Judgment.answer == "unsure", 1), else_=0)))
                .outerjoin(Judgment, latest_join).where(Item.owner_id == subject,
                 Item.corpus_id == corpus_id).group_by(Item.kind))).all()
        counts = {kind: {"total": 0, "reviewed": 0, "unsure": 0, "definite": 0} for kind in ("pair", "lemma", "stem")}
        for kind, total, reviewed, unsure in rows:
            counts[kind] = {"total": total, "reviewed": reviewed, "unsure": unsure,
                            "definite": reviewed - unsure}
        revisions = (await db.execute(select(func.count()).select_from(Judgment).where(
                     Judgment.owner_id == subject, Judgment.corpus_id == corpus_id))).scalar_one()
        return {"kinds": counts, "revision_events": revisions}

    @app.get("/api/corpora/{corpus_id}/items")
    async def items(corpus_id: UUID, kind: Literal["pair", "lemma", "stem"] = "pair",
                    state: Literal["unlabelled", "labelled", "unsure"] = "unlabelled",
                    after: int = Query(-1, ge=-1, le=2**31 - 1), limit: int = Query(1, ge=1, le=50),
                    subject=Depends(owner), db=Depends(session)):
        await owned_corpus(db, subject, corpus_id)
        query = select(Item, Judgment).outerjoin(Judgment, latest_join).where(
                Item.owner_id == subject, Item.corpus_id == corpus_id, Item.kind == kind,
                Item.ordinal > after)
        if state == "unlabelled":
            query = query.where(Item.current_revision == 0)
        elif state == "labelled":
            query = query.where(Item.current_revision > 0)
        else:
            query = query.where(Judgment.answer == "unsure")
        rows = (await db.execute(query.order_by(Item.ordinal).limit(limit + 1))).all()
        result = []
        for item, judgment in rows[:limit]:
            result.append({"candidate": item.payload, "ordinal": item.ordinal,
                           "current_revision": item.current_revision,
                           "judgment": None if judgment is None else {
                               "answer": judgment.answer, "lemma": judgment.lemma,
                               "irregular": judgment.irregular, "revision": judgment.revision,
                               "annotated_at": judgment.created_at.isoformat()}})
        return {"items": result, "next_after": rows[limit - 1][0].ordinal if len(rows) > limit else None}

    @app.get("/api/corpora/{corpus_id}/items/{item_id}")
    async def item_detail(corpus_id: UUID, item_id: UUID, subject=Depends(owner), db=Depends(session)):
        row = (await db.execute(select(Item, Judgment).outerjoin(Judgment, latest_join).where(
                Item.owner_id == subject, Item.corpus_id == corpus_id, Item.id == item_id))).one_or_none()
        if row is None:
            raise failure(404, "not_found")
        item, judgment = row
        return {"candidate": item.payload, "ordinal": item.ordinal, "current_revision": item.current_revision,
                "judgment": None if judgment is None else {"answer": judgment.answer, "lemma": judgment.lemma,
                 "irregular": judgment.irregular, "revision": judgment.revision,
                 "annotated_at": judgment.created_at.isoformat()}}

    @app.post("/api/corpora/{corpus_id}/items/{item_id}/answer")
    async def answer(corpus_id: UUID, item_id: UUID, data: AnswerRequest,
                     subject=Depends(owner), db=Depends(session)):
        try:
            async with db.begin():
                item = (await db.execute(select(Item).where(Item.owner_id == subject,
                        Item.corpus_id == corpus_id, Item.id == item_id).with_for_update())).scalar_one_or_none()
                if item is None:
                    raise failure(404, "not_found")
                old = (await db.execute(select(Judgment).where(Judgment.owner_id == subject,
                       Judgment.annotation_id == data.request_id))).scalar_one_or_none()
                if old is not None:
                    if (old.corpus_id, old.item_id, old.revision - 1, old.answer, old.lemma, old.irregular) != (
                            corpus_id, item_id, data.base_revision, data.answer, data.lemma, data.irregular):
                        raise failure(409, "request_id_conflict")
                    return {"annotation_id": str(old.annotation_id), "revision": old.revision,
                            "current_revision": item.current_revision}
                if item.current_revision != data.base_revision:
                    raise failure(409, "revision_conflict", current_revision=item.current_revision)
                candidate = Candidate.model_validate(item.payload)
                created_at = datetime.now(timezone.utc)
                try:
                    annotation = candidate.annotation(owner=subject, revision=item.current_revision + 1,
                                 answer=data.answer, lemma=data.lemma, irregular=data.irregular,
                                 annotation_id=data.request_id, annotated_at=created_at)
                    annotation.validate()
                except ValueError as exc:
                    raise failure(422, "invalid_judgment") from exc
                db.add(Judgment(owner_id=subject, corpus_id=corpus_id, item_id=item.id,
                       revision=annotation.revision, annotation_id=data.request_id, answer=data.answer,
                       lemma=data.lemma, irregular=data.irregular, created_at=created_at))
                item.current_revision = annotation.revision
            return {"annotation_id": str(data.request_id), "revision": annotation.revision,
                    "current_revision": annotation.revision}
        except IntegrityError as exc:
            raise failure(409, "request_id_conflict") from exc

    @app.get("/api/corpora/{corpus_id}/export.tsv")
    async def export(corpus_id: UUID, subject=Depends(owner), db=Depends(session)):
        await owned_corpus(db, subject, corpus_id)
        async def rows():
            import csv
            from ..schema import FIELDS
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
            query = select(Item, Judgment).join(Judgment, and_(Judgment.owner_id == Item.owner_id,
                    Judgment.corpus_id == Item.corpus_id, Judgment.item_id == Item.id)).where(
                    Item.owner_id == subject, Item.corpus_id == corpus_id).order_by(Item.ordinal, Judgment.revision)
            result = await db.stream(query.execution_options(yield_per=250))
            try:
                async for item, judgment in result:
                    candidate = Candidate.model_validate(item.payload)
                    annotation = candidate.annotation(owner=subject, revision=judgment.revision,
                                 answer=judgment.answer, lemma=judgment.lemma, irregular=judgment.irregular,
                                 annotation_id=judgment.annotation_id, annotated_at=judgment.created_at)
                    writer.writerow(annotation.row())
                    yield buffer.getvalue().encode("utf-8")
                    buffer.seek(0)
                    buffer.truncate(0)
            finally:
                await result.close()
        from fastapi.responses import StreamingResponse
        return StreamingResponse(rows(), media_type="text/tab-separated-values; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="labels-{corpus_id}.tsv"'})

    return app
