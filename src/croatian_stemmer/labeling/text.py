"""Candidates from raw Croatian text: plain text files, standard input, or a MediaWiki
XML dump such as the Croatian Wikipedia's (streamed, also from .xml.bz2).

Raw text has no lemmas, so suggestions come from a lexicon: one or more lemmatised
CoNLL-U corpora (hr500k), each form taking its most frequent lemma and POS there.
Forms the lexicon does not know are skipped. The sampling is prepare's (the same
strata, prefixed `text_`, so a raw-text corpus never shares a class prior with a
lemmatised one), with word items spread over frequency bands. Nothing here is a
known answer: raw text has no ground truth, so such a corpus takes no gold of its own.
"""

import bz2
import hashlib
import html
import io
import json
import random
import re
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from xml.etree.ElementTree import iterparse

from croatian_stemmer.rules import STOP_WORDS

from .candidates import Records, Token, _check_provenance, occurrences, reservoir, sample
from .licenses import allowed, family
from .schema import normalized

PREFIX = "text_"
CROATIAN = frozenset("abcčćdđefghijklmnoprsštuvzž")
# Frequency bands of word items (occurrences in the text): [low, high).
BANDS = ((2, 5), (5, 20), (20, 100), (100, 1000), (1000, None))
WIKI_LICENSE = "CC BY-SA 4.0"
MAX_CONTEXT = 4000
MIN_WORDS, MAX_WORDS = 4, 60

# Abbreviations after which a full stop does not end a Croatian sentence.
ABBREVIATIONS = frozenset("""
    npr tj itd sl dr prof god st br str sv gl mr ing tzv odn usp v g pr kr sur
    tisk izd ur prev engl lat njem franc tal grč hrv srp slov rus mađ min sat
    mil mlrd tis kn km cm mm kg gr ml dl ca oko pok sjev juž ist zap ožu tra svi
    lip srp kol ruj lis stu pro sij velj jan feb mar apr jun jul aug sep okt nov dec
    br sc dipl doc akad pred potpred
""".split())

_SENTENCE_END = re.compile(r"([.!?…]+)([\"'”’»)\]]*)\s+(?=[\"'„“«(\[]?[A-ZČĆĐŠŽ0-9])")


# A usable context ends like a sentence; markup residue or an address disqualifies it
# (a release refuses any value containing "@").
_ENDED = re.compile(r"[.!?…][\"'”’»)\]]*$")
_RESIDUE = re.compile(r"[\[\]{}|<>=_\\]")


def split_sentences(paragraph: str) -> list[str]:
    """Croatian sentences of a paragraph: a split after . ! ? or … followed by space and an
    upper-case letter or digit, except after a known abbreviation or a one-letter initial."""
    out, start = [], 0
    for match in _SENTENCE_END.finditer(paragraph):
        before = paragraph[start:match.start()].rsplit(None, 1)
        last = before[-1] if before else ""
        bare = last.strip("\"'„“«(").lower()
        if match.group(1) == "." and (bare in ABBREVIATIONS or (len(bare) == 1 and bare.isalpha())):
            continue
        out.append(paragraph[start:match.end(2)].strip())
        start = match.end()
    out.append(paragraph[start:].strip())
    return [s for s in out if s]


def words(sentence: str):
    """(index, surface, form) of each word: whitespace tokens with their punctuation
    stripped that are purely alphabetic (no digits, hyphens or apostrophes inside)."""
    for index, raw in enumerate(sentence.split()):
        surface = raw.strip(".,;:!?…\"'„“”’«»()[]{}*/")
        if surface and surface.isalpha():
            yield index, surface, normalized(surface)


def croatian(form: str) -> bool:
    return 2 <= len(form) <= 40 and all(c in CROATIAN for c in form)


# ---- wikitext --------------------------------------------------------------------------

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DROPPED_TAGS = re.compile(
    r"<(ref|math|chem|gallery|code|pre|syntaxhighlight|source|timeline|score|graph|mapframe|imagemap|"
    r"templatedata|references|table|nowiki|poem|hiero|inputbox|categorytree)\b[^>]*?(/>|>.*?</\1\s*>)",
    re.S | re.I)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_EXTERNAL = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")
_URL = re.compile(r"(?:https?:)?//\S+")
_MAGIC = re.compile(r"__[A-ZČĆĐŠŽ]+__")
_FORMAT = re.compile(r"'{2,}")
# Namespaces whose links are not running text (English and Croatian names).
_NON_TEXT_LINKS = ("file:", "image:", "datoteka:", "slika:", "category:", "kategorija:", "media:", "mediji:")
_INTERWIKI = re.compile(r"^[a-z]{2,3}(-[a-z]+)?:")


def _strip_nested(text: str, opening: str, closing: str) -> str:
    """Remove every balanced opening...closing block (templates, tables), nested or not."""
    out, depth, i, n = [], 0, 0, len(text)
    while i < n:
        if text.startswith(opening, i):
            depth += 1
            i += len(opening)
        elif depth and text.startswith(closing, i):
            depth -= 1
            i += len(closing)
        else:
            if not depth:
                out.append(text[i])
            i += 1
    return "".join(out)


def _link(match) -> str:
    inner = match.group(1)
    target, _, label = inner.partition("|")
    lowered = target.strip().lower()
    if lowered.startswith(_NON_TEXT_LINKS) or _INTERWIKI.match(lowered):
        return ""
    return (label or target).split("|")[-1]


def wikitext_paragraphs(text: str) -> list[str]:
    """Plain paragraphs of an article's wikitext: comments, references and other non-text
    tags, templates, tables, files, categories, interwiki links, headings, list and table
    markup and formatting removed; links replaced by their text."""
    text = _COMMENT.sub("", text)
    text = _DROPPED_TAGS.sub("", text)
    text = _strip_nested(text, "{{", "}}")
    text = _strip_nested(text, "{|", "|}")
    for _ in range(3):  # links can hold links (file captions)
        text = _LINK.sub(_link, text)
    text = _EXTERNAL.sub(lambda m: m.group(1) or "", text)
    text = _TAG.sub("", text)
    text = _MAGIC.sub("", text)
    text = _FORMAT.sub("", text)
    text = html.unescape(text).replace(" ", " ")
    paragraphs, current = [], []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith(("=", "|", "!", "{", "}", "[[", "]]")):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        stripped = stripped.lstrip("*#:;").strip()
        if stripped:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return [_URL.sub("", p).strip() for p in paragraphs]


def mwparser_paragraphs(text: str) -> list[str]:
    """The same with mwparserfromhell (the `wiki` extra) doing the wikitext parsing."""
    import mwparserfromhell
    text = _DROPPED_TAGS.sub("", _COMMENT.sub("", text))
    code = mwparserfromhell.parse(text)
    for node in code.filter_templates(recursive=False):
        try:
            code.remove(node)
        except ValueError:
            pass
    return wikitext_paragraphs(str(code.strip_code(normalize=True, collapse=False)))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def wiki_pages(handle, info=None):
    """(site, title, revision id, wikitext) of each main-namespace article that is not a
    redirect, streamed from a MediaWiki XML export; site is the base URL from <siteinfo>,
    and `info` (a dict), if given, receives its `site` and `dbname`."""
    info = {} if info is None else info
    site, title, ns, revision, text, redirect, depth = "", "", "", "", "", False, 0
    for event, element in iterparse(handle, events=("start", "end")):
        name = _local(element.tag)
        if event == "start":
            if name == "revision":
                depth += 1
            continue
        if name == "base" and not site:
            match = re.match(r"(https?://[^/]+)/", (element.text or ""))
            site = info["site"] = match.group(1) if match else ""
        elif name == "dbname" and "dbname" not in info:
            info["dbname"] = (element.text or "").strip()
        elif name == "title":
            title = element.text or ""
        elif name == "ns":
            ns = element.text or ""
        elif name == "redirect":
            redirect = True
        elif name == "id" and depth and not revision:
            revision = element.text or ""
        elif name == "text":
            text = element.text or ""
        elif name == "revision":
            depth -= 1
        elif name == "page":
            if ns == "0" and not redirect and text and revision:
                yield site, title, revision, text
            title, ns, revision, text, redirect = "", "", "", "", False
            element.clear()


def is_disambiguation(text: str) -> bool:
    return re.search(r"\{\{\s*(razdvojba|disambig|višeznačnica)", text, re.I) is not None


# ---- documents -------------------------------------------------------------------------


class Documents:
    """The input as documents of (ref base, paragraphs), and its identity (corpus_sha256):
    the SHA-256 of a single file's bytes, or of the sorted list of (name, SHA-256) of several."""

    def __init__(self, inputs, *, wikipedia=None, parser="builtin", max_pages=None):
        self.inputs, self.parser, self.max_pages = list(inputs), parser, max_pages
        self.wikipedia = wikipedia
        self.stats = Counter()
        self.site, self.info = "", {}
        self.files = []
        for value in self.inputs:
            if value == "-":
                self.files.append(("stdin", None))
                continue
            path = Path(value)
            if path.is_dir():
                found = sorted(p for p in path.rglob("*.txt") if p.is_file())
                if not found:
                    raise ValueError(f"{path}: no .txt files")
                self.files += [(p.relative_to(path).as_posix(), p) for p in found]
            elif path.is_file():
                self.files.append((path.name, path))
            else:
                raise ValueError(f"{path}: no such file or directory")
        if not self.files:
            raise ValueError("no input")
        names = [name for name, _ in self.files]
        if len(set(names)) != len(names):
            raise ValueError("two inputs have the same name; pass their directory instead")
        if self.wikipedia is None:
            self.wikipedia = all(p is not None and p.name.endswith((".xml", ".xml.bz2")) for _, p in self.files)
        self.hashes = {}

    @property
    def sha256(self) -> str:
        if len(self.hashes) == 1:
            return next(iter(self.hashes.values()))
        listing = "".join(f"{name}\t{digest}\n" for name, digest in sorted(self.hashes.items()))
        return hashlib.sha256(listing.encode("utf-8")).hexdigest()

    def _read(self, name, path):
        """A binary stream that hashes what it yields (stdin is read once, in full)."""
        if path is None:
            data = sys.stdin.buffer.read()
            self.hashes[name] = hashlib.sha256(data).hexdigest()
            return io.BytesIO(data)
        return io.BufferedReader(_Hashing(path.open("rb"),
                                          lambda value, name=name: self.hashes.__setitem__(name, value)), 1 << 20)

    def __iter__(self):
        for name, path in self.files:
            raw = self._read(name, path)
            try:
                if self.wikipedia:
                    stream = bz2.open(raw) if name.endswith(".bz2") else raw
                    for site, title, revision, text in wiki_pages(stream, self.info):
                        if self.max_pages is not None and self.stats["pages"] >= self.max_pages:
                            break
                        self.site = self.site or site
                        if is_disambiguation(text):
                            self.stats["disambiguation_pages"] += 1
                            continue
                        self.stats["pages"] += 1
                        clean = mwparser_paragraphs if self.parser == "mwparserfromhell" else wikitext_paragraphs
                        base = f"{site or 'https://wiki.invalid'}/w/index.php?oldid={revision}"
                        yield base, clean(text)
                    raw.read()  # hash the whole file, also after --max-pages
                else:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig").read()
                    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
                    self.stats["files"] += 1
                    yield name, [p for p in paragraphs if p]
            finally:
                raw.close()


class _Hashing(io.RawIOBase):
    """A read-only raw stream that reports the SHA-256 of its bytes when it reaches the end."""

    def __init__(self, handle, done):
        self.handle, self.done, self.digest, self.finished = handle, done, hashlib.sha256(), False

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.handle.read(len(buffer))
        if not data:
            if not self.finished:
                self.finished = True
                self.done(self.digest.hexdigest())
            return 0
        self.digest.update(data)
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self.handle.close()
        super().close()


# ---- lexicon ---------------------------------------------------------------------------


def lexicon(paths):
    """{form: (lemma, upos)}: each form's most frequent analysis over the lexicon corpora
    (ties by lemma, then POS), and the corpora's SHA-256s."""
    counts, hashes = defaultdict(Counter), []
    for path in paths:
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        for token in occurrences(path):
            counts[token.word][(token.lemma, token.upos)] += 1
    if not counts:
        raise ValueError("the lexicon has no form/lemma/POS entries")
    best = {form: min(found.items(), key=lambda kv: (-kv[1], kv[0]))[0] for form, found in counts.items()}
    return best, hashes


# ---- candidates ------------------------------------------------------------------------


def from_text(inputs, *, lexicon_paths, lexicon_uri, lexicon_license, source_uri=None, license=None,
              pair_count=10000, word_count=1000, seed=0, min_count=2, wikipedia=None, parser="builtin",
              max_pages=None):
    """(records, receipt): candidates of the text in candidate schema 2, which also names the
    lexicon (lexicon_uri, lexicon_license) the lemma and POS suggestions come from.

    The corpus id covers the input's hash and every option that changes the items (seed,
    sample sizes, min_count, max_pages, parser, format and the lexicon's hashes), so two
    different runs over one file are two corpora, never a mix in one."""
    if parser not in ("builtin", "mwparserfromhell"):
        raise ValueError("parser must be builtin or mwparserfromhell")
    if (type(pair_count) is not int or type(word_count) is not int or pair_count < 0 or word_count < 0
            or pair_count + word_count == 0):
        raise ValueError("request at least one candidate")
    if type(min_count) is not int or min_count < 1:
        raise ValueError("min-count must be positive")
    documents = Documents(inputs, wikipedia=wikipedia, parser=parser, max_pages=max_pages)
    if documents.wikipedia:
        # Wikipedia text is CC BY-SA: no other licence can be declared for it.
        license = license or WIKI_LICENSE
        if family(license) != "by-sa":
            raise ValueError(f"a MediaWiki dump is CC BY-SA text; {license!r} cannot be declared for it")
    elif not source_uri or not license:
        raise ValueError("source URI and license are required for plain text")
    _check_provenance(lexicon_uri or "", lexicon_license or "")
    if not allowed(license, lexicon_license):
        raise ValueError(f"no labels licence satisfies both the text ({license}) and the lexicon "
                         f"({lexicon_license}) licences")
    known, lexicon_hashes = lexicon(lexicon_paths)

    counts, lower, capital, chosen = Counter(), Counter(), Counter(), {}
    stats = Counter()
    for base, paragraphs in documents:
        seen_sentences = set()
        number = 0
        for paragraph in paragraphs:
            for sentence in split_sentences(paragraph):
                number += 1
                stats["sentences"] += 1
                n_words = len(sentence.split())
                if (not MIN_WORDS <= n_words <= MAX_WORDS or len(sentence) > MAX_CONTEXT
                        or not _ENDED.search(sentence) or _RESIDUE.search(sentence) or "@" in sentence
                        or "://" in sentence or sentence in seen_sentences):
                    stats["sentences_skipped"] += 1
                    continue
                seen_sentences.add(sentence)
                stats["sentences_used"] += 1
                for index, surface, form in words(sentence):
                    stats["tokens"] += 1
                    if not croatian(form):
                        stats["tokens_not_croatian_alphabet"] += 1
                        continue
                    if form not in known:
                        stats["tokens_not_in_lexicon"] += 1
                        continue
                    if form in STOP_WORDS:
                        stats["tokens_stop_words"] += 1
                        continue
                    counts[form] += 1
                    if surface[0].islower():
                        lower[form] += 1
                    elif index > 0:
                        capital[form] += 1
                    ref = f"{base}#s{number}.w{index + 1}"
                    # One occurrence per form, spread over the text: the lowest seeded hash.
                    rank = zlib.crc32(f"{seed}:{ref}".encode("utf-8"))
                    if form not in chosen or rank < chosen[form][0]:
                        chosen[form] = (rank, ref, sentence)
    if documents.wikipedia and not documents.site:
        raise ValueError("the dump has no <siteinfo><base> URL")
    corpus_sha256 = documents.sha256
    if documents.wikipedia and not source_uri:
        dbname = documents.info.get("dbname") or "wiki"
        source_uri = f"https://dumps.wikimedia.org/{dbname}/"
    _check_provenance(source_uri, license)

    names = {form for form in counts if capital[form] > lower[form]}
    tokens = []
    for form, n in counts.items():
        if n < min_count:
            stats["forms_below_min_count"] += 1
        elif form in names:
            stats["forms_skipped_as_names"] += 1
        else:
            lemma, upos = known[form]
            if upos in ("PROPN", "X", "PUNCT", "SYM", "NUM"):
                stats["forms_skipped_by_pos"] += 1
                continue
            _, ref, sentence = chosen[form]
            tokens.append(Token(form, lemma, upos, ref, sentence))
    tokens.sort(key=lambda t: (t.upos, t.lemma, t.word))
    if not tokens:
        raise ValueError("the text has no eligible words")
    identity = {"corpus_sha256": corpus_sha256, "seed": seed, "pairs": pair_count, "word_items": word_count,
                "min_count": min_count, "max_pages": max_pages, "parser": parser,
                "format": "mediawiki" if documents.wikipedia else "text", "lexicon_sha256": lexicon_hashes}
    corpus_id = str(uuid5(NAMESPACE_URL, "croatian-stemmer-text-corpus:" + json.dumps(identity, sort_keys=True)))
    records = Records(corpus_id=corpus_id, corpus_sha256=corpus_sha256, source_uri=source_uri, license=license,
                      lexicon=(lexicon_uri, lexicon_license))
    rng = random.Random(seed)
    by_band = defaultdict(list)
    for token in tokens:
        for low, high in BANDS:
            if counts[token.word] >= low and (high is None or counts[token.word] < high):
                by_band[(low, high)].append(token)
                break
    word_strata = _spread(by_band, min(word_count, len(tokens)), rng)
    rows, n_pairs = sample(tokens, records, pair_count=pair_count, word_count=0, rng=rng, prefix=PREFIX,
                           word_strata=word_strata)
    receipt = {"candidate_schema_version": 2, "corpus_id": corpus_id, "corpus_sha256": corpus_sha256,
               "source_uri": source_uri, "license": license, "lexicon_uri": lexicon_uri,
               "lexicon_license": lexicon_license, "labels_licenses": list(allowed(license, lexicon_license)),
               "identity": identity, "seed": seed, "format":
               "mediawiki" if documents.wikipedia else "text", "parser": parser if documents.wikipedia else None,
               "site": documents.site or None, "inputs": len(documents.files), "min_count": min_count,
               "lexicon_sha256": lexicon_hashes, "lexicon_forms": len(known),
               **{key: value for key, value in sorted((documents.stats + stats).items())},
               "eligible_forms": len(tokens),
               "forms_per_band": {_band_name(band): len(found) for band, found in sorted(by_band.items(),
                                                                                       key=lambda kv: kv[0][0])},
               "requested_pairs": pair_count, "prepared_pairs": n_pairs,
               "prepared_lemma_items": sum(r["kind"] == "lemma" for r in rows),
               "prepared_stem_items": sum(r["kind"] == "stem" for r in rows),
               "strata": dict(sorted(Counter(r["sampling_stratum"] for r in rows).items())),
               "gold": "none: raw text has no ground truth", "human_judgments": 0,
               "algorithm_sha256": records.algorithm}
    return rows, receipt


def _band_name(band):
    low, high = band
    return f"{low}+" if high is None else f"{low}-{high - 1}"


def _spread(by_band, total, rng):
    """total tokens drawn evenly over the frequency bands (a band with too few gives its
    share to the others), each with its band stratum."""
    bands = sorted(by_band, key=lambda band: band[0])
    remaining, out = total, []
    pools = {band: list(by_band[band]) for band in bands}
    while remaining and any(pools.values()):
        open_bands = [band for band in bands if pools[band]]
        share = max(1, remaining // len(open_bands))
        for band in open_bands:
            if not remaining:
                break
            taken = reservoir(pools[band], min(share, remaining, len(pools[band])), rng)
            chosen = set(id(t) for t in taken)
            pools[band] = [t for t in pools[band] if id(t) not in chosen]
            out += [(token, f"{PREFIX}word_band_{_band_name(band)}") for token in taken]
            remaining -= len(taken)
    return out
