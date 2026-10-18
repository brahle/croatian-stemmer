"""Only candidates are importable; caller identity/time never come from payloads."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from ..schema import Annotation, UPOS, word
from .config import MINIMUM_AGE


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_schema_version: StrictInt
    corpus_id: UUID
    corpus_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_uri: StrictStr = Field(min_length=1, max_length=2048)
    license: StrictStr = Field(min_length=1, max_length=512)
    item_id: UUID
    kind: Literal["pair", "lemma", "stem"]
    word: StrictStr
    other_word: StrictStr
    proposed_lemma: StrictStr
    other_proposed_lemma: StrictStr
    proposed_stem: StrictStr
    upos: StrictStr
    context: StrictStr = Field(max_length=4000)
    other_context: StrictStr = Field(max_length=4000)
    word_ref: StrictStr = Field(min_length=1, max_length=512)
    other_word_ref: StrictStr = Field(max_length=512)
    sampling_stratum: StrictStr = Field(min_length=1, max_length=128)
    algorithm_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    # Schema 2 (from-text): the lexicon the lemma and POS suggestions come from, whose licence
    # binds the labels too. Schema 1 (a lemmatised corpus suggests its own lemmas) has none.
    lexicon_uri: StrictStr | None = Field(default=None, min_length=1, max_length=2048)
    lexicon_license: StrictStr | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def valid_candidate(self):
        if self.candidate_schema_version not in (1, 2):
            raise ValueError("unsupported candidate schema")
        if (self.candidate_schema_version == 2) != (self.lexicon_uri is not None) or \
                (self.lexicon_uri is None) != (self.lexicon_license is None):
            raise ValueError("schema 2 needs the lexicon's source and licence; schema 1 has none")
        for field in ("word", "proposed_lemma"):
            if word(getattr(self, field), field) != getattr(self, field):
                raise ValueError("suggestions must be normalized")
        if self.upos not in UPOS:
            raise ValueError("invalid UPOS")
        if self.kind == "pair":
            if word(self.other_proposed_lemma) != self.other_proposed_lemma:
                raise ValueError("invalid second lemma suggestion")
        elif self.other_proposed_lemma:
            raise ValueError("second suggestion belongs only to a pair")
        self.annotation(owner="validation", revision=1, answer="unsure").validate()
        return self

    def annotation(self, *, owner, revision, answer, lemma="", irregular=False,
                   annotation_id=None, annotated_at=None):
        return Annotation(corpus_id=str(self.corpus_id), corpus_sha256=self.corpus_sha256,
                          source_uri=self.source_uri, license=self.license, item_id=str(self.item_id),
                          annotation_id=str(annotation_id or uuid4()), annotator_id=owner,
                          revision=revision, annotated_at=annotated_at or datetime.now(timezone.utc),
                          kind=self.kind, word=self.word, other_word=self.other_word,
                          proposed_stem=self.proposed_stem, upos=self.upos, context=self.context,
                          other_context=self.other_context, word_ref=self.word_ref,
                          other_word_ref=self.other_word_ref, answer=answer, lemma=lemma, irregular=irregular)

    @property
    def provenance(self):
        return (self.corpus_id, self.corpus_sha256, self.source_uri, self.license, self.lexicon_uri,
                self.lexicon_license)

    @property
    def question(self):
        return (self.kind, self.word, self.other_word, self.proposed_stem, self.upos,
                self.context, self.other_context, self.word_ref, self.other_word_ref)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=200)
    candidates: list[Candidate] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def one_corpus(self):
        if not self.name.strip():
            raise ValueError("name required")
        first = self.candidates[0]
        identity = first.provenance
        seen = {}
        for row in self.candidates:
            if row.provenance != identity:
                raise ValueError("import must contain one corpus with consistent provenance")
            if row.item_id in seen and seen[row.item_id] != row.model_dump():
                raise ValueError("duplicate item id with different content")
            seen[row.item_id] = row.model_dump()
        return self


VERSION = r"^[0-9A-Za-z._-]{1,32}$"


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    base_revision: StrictInt = Field(ge=0)
    answer: Literal["same", "different", "unsure", "confirmed", "accept", "reject"]
    lemma: StrictStr = Field(default="", max_length=128)
    irregular: StrictBool = False
    # Provenance: the UI build that produced the answer and the time it took.
    # Stored as validated; the server clamps nothing.
    client_version: StrictStr = Field(pattern=VERSION)
    elapsed_ms: StrictInt | None = Field(default=None, ge=0, le=3_600_000)

    @field_validator("lemma")
    @classmethod
    def normalized_lemma(cls, value):
        return word(value, "lemma") if value else ""


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    privacy_version: StrictStr = Field(pattern=VERSION)
    terms_version: StrictStr = Field(pattern=VERSION)
    participation_version: StrictStr = Field(pattern=VERSION)
    age_confirmed: StrictBool
    # The age the person confirmed; a client still asking for 16 is refused.
    age_threshold: StrictInt
    locale: Literal["hr", "en"]
    ui_version: StrictStr = Field(pattern=VERSION)

    @field_validator("age_confirmed")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError(f"participants must confirm they are at least {MINIMUM_AGE}")
        return value

    @field_validator("age_threshold")
    @classmethod
    def adult(cls, value):
        if value != MINIMUM_AGE:
            raise ValueError(f"the minimum age is {MINIMUM_AGE}")
        return value


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels_license: Literal["CC0 1.0", "CC BY 4.0", "CC BY-SA 4.0"]


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "quarantined", "blocked"]
    reason: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("a reason is required")
        return value.strip()


class EraseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["IZBRIŠI", "DELETE"]


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepting_judgments: StrictBool


Kind = Literal["pair", "lemma", "stem"]


class ScoringParamsRequest(BaseModel):
    """The whole parameter set; scoring.validate_params() checks every key and bound."""
    model_config = ConfigDict(extra="forbid")
    params: dict


class ScoringSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scoring_enabled: StrictBool


class RedrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    cell: Literal["agrees", "differs", "none"]


def _reason(value):
    if not value.strip() or "\x00" in value:
        raise ValueError("a reason is required")
    return value.strip()


class GoldRow(BaseModel):
    """One line of the gold builder's output; the server recomputes everything it can."""
    model_config = ConfigDict(extra="forbid")
    gold_schema_version: Literal[1]
    corpus_id: UUID
    item_id: UUID
    kind: Kind
    pool: Literal["qualification", "audit"]
    answer: Literal["same", "different", "confirmed", "accept", "reject"]
    lemma: StrictStr = Field(default="", max_length=128)
    basis: StrictStr = Field(min_length=1, max_length=64)
    source: Literal["hr500k"]
    corpus_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    batch: StrictStr | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def answer_fits_kind(self):
        gold_answer(self.kind, self.answer, self.lemma)
        if self.lemma:
            self.lemma = word(self.lemma, "lemma")
        return self


def gold_answer(kind, answer, lemma):
    """A gold answer must be a definite answer of its kind (schema.Annotation.validate)."""
    allowed = {"pair": ("same", "different"), "lemma": ("confirmed",), "stem": ("accept", "reject")}[kind]
    if answer not in allowed:
        raise ValueError(f"{kind} gold must be one of {allowed}")
    if (kind == "lemma") != bool(lemma):
        raise ValueError("lemma gold needs the lemma; other kinds have none")
    if lemma:
        word(lemma, "lemma")


class GoldImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[GoldRow] = Field(min_length=1, max_length=5000)


class GoldRetireRequest(BaseModel):
    """Retire many known-answer items at once (a file of item ids, one per line)."""
    model_config = ConfigDict(extra="forbid")
    corpus_id: UUID | None = None
    item_ids: list[UUID] = Field(min_length=1, max_length=20000)
    reason: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        return _reason(value)


class GoldActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["set", "retire", "reactivate", "retract", "disclose"]
    pool: Literal["qualification", "audit"] | None = None
    answer: Literal["same", "different", "confirmed", "accept", "reject"] | None = None
    lemma: StrictStr = Field(default="", max_length=128)
    reason: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        return _reason(value)

    @model_validator(mode="after")
    def complete(self):
        if self.action == "set" and (self.pool is None or self.answer is None):
            raise ValueError("set needs a pool and an answer")
        if self.lemma:
            self.lemma = word(self.lemma, "lemma")
        return self


class TrustedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: StrictStr = Field(min_length=3, max_length=320)
    # A curator's note; the dashboard asks for no more than a first name.
    label: StrictStr = Field(min_length=1, max_length=100)

    @field_validator("label")
    @classmethod
    def meaningful(cls, value):
        return _reason(value)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        return _reason(value)


TrustedRemoveRequest = ReasonRequest


class AdjudicateRequest(ReasonRequest):
    answer: Literal["same", "different", "confirmed", "accept", "reject"]
    lemma: StrictStr = Field(default="", max_length=128)
    irregular: StrictBool = False

    @field_validator("lemma")
    @classmethod
    def normalized_lemma(cls, value):
        return word(value, "lemma") if value else ""


class ReopenRequest(ReasonRequest):
    discard_previous: StrictBool = False


class ReapplyRequest(BaseModel):
    """Keycloak user ids from the erasure list kept outside the database (after a restore)."""
    model_config = ConfigDict(extra="forbid")
    keycloak_user_ids: list[StrictStr] = Field(min_length=1, max_length=1000)


class ReleaseRequest(BaseModel):
    """The item ids of the release's labels.tsv (optional: without them, every releasable row
    of the run that is not a known-answer item in use)."""
    model_config = ConfigDict(extra="forbid")
    item_ids: list[UUID] | None = Field(default=None, max_length=200000)
