"""Versioned, provenance-preserving human annotation TSVs."""

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO
from uuid import UUID

SCHEMA_VERSION = "1"
UPOS = frozenset("ADJ ADP ADV AUX CCONJ DET INTJ NOUN NUM PART PRON PROPN PUNCT SCONJ SYM VERB X".split())
FIELDS = (
    "schema_version", "corpus_id", "corpus_sha256", "source_uri", "license",
    "item_id", "annotation_id", "annotator_id", "revision", "annotated_at",
    "kind", "word", "other_word", "lemma", "proposed_stem", "answer",
    "irregular", "upos", "context", "other_context", "word_ref", "other_word_ref",
    "provenance",
)


def normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def word(value: str, field: str = "word") -> str:
    value = normalized(value.strip())
    if not value or len(value) > 128 or not value.isalpha():
        raise ValueError(f"{field} must be one alphabetic word of at most 128 characters")
    return value


def _text(value: str, field: str, limit: int, *, required: bool = True) -> None:
    if (required and not value.strip()) or len(value) > limit or "\x00" in value:
        raise ValueError(f"invalid {field}")


@dataclass(frozen=True)
class Annotation:
    corpus_id: str
    corpus_sha256: str
    source_uri: str
    license: str
    item_id: str
    annotation_id: str
    annotator_id: str
    revision: int
    annotated_at: datetime
    kind: str
    word: str
    answer: str
    word_ref: str
    other_word: str = ""
    lemma: str = ""
    proposed_stem: str = ""
    irregular: bool = False
    upos: str = ""
    context: str = ""
    other_context: str = ""
    other_word_ref: str = ""
    schema_version: str = SCHEMA_VERSION
    provenance: str = "human"

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version {self.schema_version!r}")
        if self.provenance != "human":
            raise ValueError("candidate suggestions are not human annotations")
        for field in ("corpus_id", "item_id", "annotation_id"):
            if str(UUID(getattr(self, field))) != getattr(self, field):
                raise ValueError(f"{field} must be a canonical UUID")
        if not re.fullmatch(r"[0-9a-f]{64}", self.corpus_sha256):
            raise ValueError("corpus_sha256 must be a lowercase SHA-256 digest")
        for field, limit in (("source_uri", 2048), ("license", 512), ("annotator_id", 256), ("word_ref", 512)):
            _text(getattr(self, field), field, limit)
        for field, limit in (("context", 4000), ("other_context", 4000), ("other_word_ref", 512)):
            _text(getattr(self, field), field, limit, required=False)
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        if self.annotated_at.tzinfo is None or self.annotated_at.utcoffset() is None:
            raise ValueError("annotated_at must include a timezone")
        if type(self.irregular) is not bool:
            raise ValueError("irregular must be boolean")
        if self.upos and self.upos not in UPOS:
            raise ValueError("invalid UPOS")
        if word(self.word) != self.word:
            raise ValueError("word must be normalized NFC and lowercase")
        if self.kind == "pair":
            if word(self.other_word, "other_word") != self.other_word:
                raise ValueError("other_word must be normalized NFC and lowercase")
            _text(self.other_word_ref, "other_word_ref", 512)
            if self.answer not in {"same", "different", "unsure"} or self.lemma or self.proposed_stem:
                raise ValueError("pair requires same/different/unsure and no lemma/stem label")
        elif self.kind == "lemma":
            if self.answer not in {"confirmed", "unsure"}:
                raise ValueError("lemma requires confirmed/unsure")
            if self.answer == "confirmed" and word(self.lemma, "lemma") != self.lemma:
                raise ValueError("lemma must be normalized")
            if self.answer == "unsure" and self.lemma:
                raise ValueError("an unsure lemma cannot contain a confirmed label")
            if self.other_word or self.other_word_ref or self.other_context or self.proposed_stem:
                raise ValueError("lemma annotation has unrelated pair/stem fields")
        elif self.kind == "stem":
            if self.answer not in {"accept", "reject", "unsure"}:
                raise ValueError("stem requires accept/reject/unsure")
            if word(self.proposed_stem, "proposed_stem") != self.proposed_stem:
                raise ValueError("proposed_stem must be normalized")
            if self.other_word or self.other_word_ref or self.other_context or self.lemma:
                raise ValueError("stem annotation has unrelated pair/lemma fields")
        else:
            raise ValueError(f"unknown annotation kind {self.kind!r}")

    @property
    def corpus_identity(self) -> tuple:
        return self.corpus_sha256, self.source_uri, self.license

    @property
    def item_identity(self) -> tuple:
        return (self.kind, self.word, self.other_word, self.proposed_stem, self.upos,
                self.context, self.other_context, self.word_ref, self.other_word_ref)

    @property
    def label(self) -> tuple:
        return self.answer, self.lemma

    def row(self) -> dict[str, str]:
        self.validate()
        values = asdict(self)
        values["annotated_at"] = self.annotated_at.isoformat()
        values["irregular"] = "1" if self.irregular else "0"
        return {field: str(values[field]) for field in FIELDS}

    @classmethod
    def from_row(cls, values: dict[str, str]) -> "Annotation":
        if set(values) != set(FIELDS) or any(v is None for v in values.values()):
            raise ValueError("annotation row does not match the versioned schema")
        values = dict(values)
        if not re.fullmatch(r"[1-9][0-9]*", values["revision"]):
            raise ValueError("revision must be a positive integer")
        values["revision"] = int(values["revision"])
        if values["irregular"] not in {"0", "1"}:
            raise ValueError("irregular must be 0 or 1")
        values["irregular"] = values["irregular"] == "1"
        values["annotated_at"] = datetime.fromisoformat(values["annotated_at"])
        result = cls(**values)
        result.validate()
        return result


def read_tsv(handle: TextIO) -> list[Annotation]:
    reader = csv.DictReader(handle, delimiter="\t", strict=True)
    if reader.fieldnames != list(FIELDS):
        raise ValueError("TSV header does not match schema v1")
    out = []
    try:
        for row in reader:
            try:
                out.append(Annotation.from_row(row))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"line {reader.line_num}: {exc}") from exc
    except csv.Error as exc:
        raise ValueError(f"line {reader.line_num}: invalid TSV: {exc}") from exc
    return out


def write_tsv(handle: TextIO, annotations: Iterable[Annotation]) -> None:
    writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for annotation in annotations:
        writer.writerow(annotation.row())


def load(paths: Iterable[Path]) -> tuple[list[Annotation], list[dict]]:
    annotations, sources = [], []
    for path in paths:
        # Hash the exact bytes parsed, rather than a later reread of a file that
        # could have changed between the evaluation and its provenance receipt.
        raw = path.read_bytes()
        annotations.extend(read_tsv(io.StringIO(raw.decode("utf-8-sig"))))
        sources.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
    return annotations, sources
