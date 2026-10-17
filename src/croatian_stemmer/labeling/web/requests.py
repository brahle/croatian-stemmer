"""Only candidates are importable; caller identity/time never come from payloads."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from ..schema import Annotation, UPOS, word


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

    @model_validator(mode="after")
    def valid_candidate(self):
        if self.candidate_schema_version != 1:
            raise ValueError("unsupported candidate schema")
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
        identity = first.corpus_id, first.corpus_sha256, first.source_uri, first.license
        seen = {}
        for row in self.candidates:
            if (row.corpus_id, row.corpus_sha256, row.source_uri, row.license) != identity:
                raise ValueError("import must contain one corpus with consistent provenance")
            if row.item_id in seen and seen[row.item_id] != row.model_dump():
                raise ValueError("duplicate item id with different content")
            seen[row.item_id] = row.model_dump()
        return self


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    base_revision: StrictInt = Field(ge=0)
    answer: Literal["same", "different", "unsure", "confirmed", "accept", "reject"]
    lemma: StrictStr = Field(default="", max_length=128)
    irregular: StrictBool = False

    @field_validator("lemma")
    @classmethod
    def normalized_lemma(cls, value):
        return word(value, "lemma") if value else ""
