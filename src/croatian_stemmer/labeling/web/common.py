"""Shared helpers for the route modules: errors, the caller, and vote queries."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, func, insert, or_, select

from ..scoring import validate_params
from .auth import Principal
from .models import AdminEvent, Annotator, Corpus, Judgment, Setting, TrustEvent


def failure(status, code, **values):
    return HTTPException(status, detail={"code": code, **values})


@dataclass(frozen=True)
class Caller:
    """An authenticated annotator record. `id` is the pseudonym used everywhere else."""
    id: UUID
    status: str
    principal: Principal
    consents: tuple = ()  # (document, version, age_threshold) rows when the request began

    @property
    def curator(self):
        return self.principal.curator


def corpus_json(corpus, counts=None):
    data = {"id": str(corpus.id), "name": corpus.name, "sha256": corpus.sha256,
            "source_uri": corpus.source_uri, "license": corpus.license,
            "lexicon_uri": corpus.lexicon_uri, "lexicon_license": corpus.lexicon_license,
            "labels_license": corpus.labels_license, "status": corpus.status,
            "created_at": corpus.created_at.isoformat(),
            "published_at": corpus.published_at.isoformat() if corpus.published_at else None}
    if counts is not None:
        data["items"] = counts
    return data


def judgment_json(judgment):
    if judgment is None:
        return None
    return {"answer": judgment.answer, "lemma": judgment.lemma, "irregular": judgment.irregular,
            "revision": judgment.revision, "annotated_at": judgment.created_at.isoformat()}


async def visible_corpus(db, caller, corpus_id, *, labeling=False):
    """A corpus the caller may see. Annotators see only published corpora (404
    otherwise); curators see every corpus but label only published ones."""
    corpus = (await db.execute(select(Corpus).where(Corpus.id == corpus_id))).scalar_one_or_none()
    if corpus is None or (corpus.status != "published" and not caller.curator):
        raise failure(404, "not_found")
    if labeling and corpus.status != "published":
        raise failure(409, "corpus_not_published")
    return corpus


def excluded_annotators():
    """Annotators whose judgments are left out of exports and vote counts:
    blocked ones, and erased ones whose last status before erasure was blocked
    (erasing an account must not bring its excluded votes back)."""
    last_status = (select(AdminEvent.details["to"].astext)
                   .where(AdminEvent.kind == "annotator.status", AdminEvent.target == cast(Annotator.id, String))
                   .order_by(AdminEvent.id.desc()).limit(1).scalar_subquery())
    return select(Annotator.id).where(or_(Annotator.status == "blocked",
                                          and_(Annotator.status == "erased", last_status == "blocked")))


def definite_votes(corpus_id):
    """Per item: the number of annotators whose latest answer is definite (not unsure)."""
    latest = (select(Judgment.item_id, Judgment.annotator_id, Judgment.answer)
              .where(Judgment.corpus_id == corpus_id, Judgment.annotator_id.not_in(excluded_annotators()))
              .distinct(Judgment.item_id, Judgment.annotator_id)
              .order_by(Judgment.item_id, Judgment.annotator_id, Judgment.revision.desc())).subquery()
    return (select(latest.c.item_id, func.count().filter(latest.c.answer != "unsure").label("n"))
            .group_by(latest.c.item_id)).subquery()


async def setting(db, key, default=None):
    """A label_setting value (inside the caller's transaction)."""
    value = (await db.execute(select(Setting.value).where(Setting.key == key))).scalar_one_or_none()
    return default if value is None else value


async def scoring_params(db) -> dict:
    """The live scoring parameters (validated; written only through PUT scoring/params)."""
    return validate_params(await setting(db, "scoring_params"))


async def trust_event(db, kind, *, actor_id=None, annotator_id=None, corpus_id=None, item_id=None, details=None) -> int:
    """Append one trust event; its id is the journal position the trigger assigns."""
    return (await db.execute(insert(TrustEvent).values(
        actor_id=actor_id, kind=kind, annotator_id=annotator_id, corpus_id=corpus_id, item_id=item_id,
        details=details or {}).returning(TrustEvent.id))).scalar_one()
