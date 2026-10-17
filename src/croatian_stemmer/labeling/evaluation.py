"""Score explicit human targets without silently turning one kind into another."""

from collections import defaultdict
from dataclasses import asdict
from typing import Callable, Iterable

from .schema import Annotation


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def resolve(annotations: Iterable[Annotation], min_annotators: int = 1):
    if type(min_annotators) is not int or min_annotators < 1:
        raise ValueError("min_annotators must be a positive integer")
    corpora, items, ids, revisions = {}, {}, {}, {}
    raw = 0
    for a in annotations:
        a.validate()
        raw += 1
        if a.corpus_id in corpora and corpora[a.corpus_id] != a.corpus_identity:
            raise ValueError("a corpus id has conflicting source provenance")
        corpora[a.corpus_id] = a.corpus_identity
        item_key = a.corpus_id, a.item_id
        if item_key in items and items[item_key] != a.item_identity:
            raise ValueError("an immutable item changed between annotations")
        items[item_key] = a.item_identity
        if a.annotation_id in ids:
            if ids[a.annotation_id] != asdict(a):
                raise ValueError("annotation id reused with different content")
            continue
        ids[a.annotation_id] = asdict(a)
        revision_key = a.corpus_id, a.item_id, a.annotator_id, a.revision
        if revision_key in revisions:
            raise ValueError("duplicate annotator revision with different annotation ids")
        revisions[revision_key] = a

    histories = defaultdict(list)
    for a in revisions.values():
        histories[(a.corpus_id, a.item_id, a.annotator_id)].append(a)
    latest = defaultdict(list)
    for (corpus, item, _), history in histories.items():
        history.sort(key=lambda a: a.revision)
        if any(b.annotated_at < a.annotated_at for a, b in zip(history, history[1:])):
            raise ValueError("annotation timestamps move backwards across revisions")
        latest[(corpus, item)].append(history[-1])

    accepted = []
    counts = {"conflicting_items": 0, "insufficient_items": 0, "unsure_items": 0,
              "multi_annotator_items": 0, "multi_annotator_agreed_items": 0}
    for labels in latest.values():
        definite = [a for a in labels if a.answer != "unsure"]
        distinct = {a.label for a in definite}
        if len(definite) >= 2:
            counts["multi_annotator_items"] += 1
            counts["multi_annotator_agreed_items"] += len(distinct) == 1
        if len(distinct) > 1:
            counts["conflicting_items"] += 1
        elif not definite:
            counts["unsure_items"] += 1
        elif len(definite) < min_annotators:
            counts["insufficient_items"] += 1
        else:
            accepted.append(definite[0])
    counts.update({"raw_export_rows": raw, "unique_annotation_revisions": len(ids),
                   "unique_items": len(items), "resolved_items": len(accepted),
                   "annotators": len({a.annotator_id for a in revisions.values()}),
                   "corpora": len(corpora), "min_annotators": min_annotators,
                   "observed_agreement": ratio(counts["multi_annotator_agreed_items"],
                                               counts["multi_annotator_items"])})
    return accepted, counts


def evaluate(annotations: Iterable[Annotation], stem_fn: Callable[[str], str], *,
             min_annotators: int = 1) -> dict:
    accepted, coverage = resolve(annotations, min_annotators)
    stems = {}

    def stem(word):
        if word not in stems:
            stems[word] = stem_fn(word)
        return stems[word]

    same = different = same_errors = different_errors = 0
    lemma_groups = defaultdict(set)
    ambiguous_forms = defaultdict(set)
    for a in accepted:
        if a.kind == "pair":
            equal = stem(a.word) == stem(a.other_word)
            if a.answer == "same":
                same += 1
                same_errors += not equal
            else:
                different += 1
                different_errors += equal
        elif a.kind == "lemma":
            lemma_groups[(a.corpus_id, a.upos, a.lemma)].add(a.word)
            ambiguous_forms[(a.corpus_id, a.upos, a.word)].add(a.lemma)

    # The same spelling can have multiple dictionary lemmas in different
    # contexts. A context-free stemmer cannot disambiguate it; report it and
    # keep it out of the unambiguous lemma-group consistency calculation.
    ambiguous = {key for key, values in ambiguous_forms.items() if len(values) > 1}
    groups = []
    for (corpus, upos, _), words in lemma_groups.items():
        words = {w for w in words if (corpus, upos, w) not in ambiguous}
        if len(words) >= 2:
            groups.append(words)
    consistent = sum(len({stem(w) for w in words}) == 1 for words in groups)

    proposals = [a for a in accepted if a.kind == "stem"]
    matching = [a for a in proposals if stem(a.word) == a.proposed_stem]
    approved = sum(a.answer == "accept" for a in matching)
    return {
        "schema_version": 1,
        "coverage": coverage,
        "pairs": {"same": same, "different": different,
                  "under_stemming_errors": same_errors, "over_stemming_errors": different_errors,
                  "under_stemming_rate": ratio(same_errors, same),
                  "over_stemming_rate": ratio(different_errors, different),
                  "accuracy": ratio(same + different - same_errors - different_errors, same + different)},
        "lemmas": {"confirmed_items": sum(a.kind == "lemma" for a in accepted),
                   "ambiguous_forms_excluded": len(ambiguous),
                   "multi_form_groups": len(groups), "consistent_groups": consistent,
                   "group_consistency": ratio(consistent, len(groups))},
        "stems": {"resolved_proposals": len(proposals), "matching_current_output": len(matching),
                  "changed_outputs_need_relabeling": len(proposals) - len(matching),
                  "accepted_current_outputs": approved, "acceptance_rate": ratio(approved, len(matching))},
    }
