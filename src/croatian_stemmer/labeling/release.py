"""Public releases (4.11.2): aggregate labels only, built from a pinned run's restricted
export, and the check that fails closed on anything else.

A release holds exactly labels.tsv, summary.tsv, dataset-card.md, params.json and
CHECKSUMS. Nothing in it is per vote or per contributor: no annotator ids, no
timestamps but the release date, no vote counts, tiers, weights, flags, events or gold
lists. A model-resolved row appears only when its crowd votes have at least three
distinct voters and none is pivotal, so the row does not depend on any single person.
"""

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .scoring import corpus_params, krippendorff_alpha, release_rule

FILES = ("labels.tsv", "summary.tsv", "dataset-card.md", "params.json", "CHECKSUMS")
LABEL_COLUMNS = ("corpus_id", "corpus_sha256", "source_uri", "license", "labels_license", "item_id", "kind", "word",
                 "other_word", "upos", "context", "other_context", "word_ref", "other_word_ref", "proposed_lemma",
                 "other_proposed_lemma", "proposed_stem", "resolved_answer", "resolved_lemma", "resolution_source",
                 "confidence_band", "cell", "run_id")
SUMMARY_COLUMNS = ("corpus_id", "kind", "measure", "key", "value")
FORBIDDEN_IN_COLUMNS = ("annotator", "email", "created", "elapsed", "tier", "weight", "count", "votes", "flag")
CHECKED_SOURCES = ("model", "reference", "review")


def read_export(path: Path):
    """(run record, corpus record, item records) of a resolved.jsonl run export."""
    run, corpus, items = None, None, []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record") == "run":
                run, corpus = row["run"], row["corpus"]
            elif row.get("record") == "item":
                items.append(row)
    if run is None:
        raise ValueError("the export has no run record")
    return run, corpus, items


def band(confidence):
    return "≥0.99" if confidence >= 0.99 else "0.95-0.99"


def crowd(item):
    """The counted crowd votes of an item as scoring.release_rule() takes them."""
    return [(v["annotator_id"], v["class"], v["weight"]) for v in item["votes"]
            if v["class"] is not None and v["tier"] != "anchor"]


def all_votes(item):
    return [(v["annotator_id"], v["class"], v["weight"]) for v in item["votes"] if v["class"] is not None]


def holds(item, params):
    """The release rule on the item's crowd votes (model rows: on all its counted votes)."""
    p = corpus_params(params, item["corpus_id"])
    tiers = {v["annotator_id"]: v["tier"] for v in item["votes"]}
    prior = [tuple(entry) for entry in item["prior"]]
    votes = all_votes(item) if item["resolution_source"] == "model" else crowd(item)
    return release_rule(prior, votes, item["k"], tiers, p)


def releasable(item):
    """In labels.tsv: resolved and releasable, and not a known-answer item still in use."""
    if item["state"] != "resolved" or not item["releasable"]:
        return False
    if item.get("gold_pool") == "qualification" or (item.get("gold_pool") == "audit" and item.get("gold_status") == "active"):
        return False
    return True


def build(export: Path, output: Path, released_on: date | None = None):
    """Write a release directory from a run export. The run must be pinned and not stale."""
    run, corpus, items = read_export(export)
    if not run.get("pinned") or run.get("stale"):
        raise ValueError("a release is built from a pinned run that is not stale")
    output.mkdir(parents=True, exist_ok=False)
    released_on = released_on or date.today()
    rows = [item for item in items if releasable(item)]
    labels = io.StringIO()
    writer = csv.DictWriter(labels, fieldnames=LABEL_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for item in sorted(rows, key=lambda i: (i["corpus_id"], i["item_id"])):
        c = item["candidate"]
        writer.writerow({
            "corpus_id": item["corpus_id"], "corpus_sha256": corpus["sha256"], "source_uri": corpus["source_uri"],
            "license": corpus["license"], "labels_license": corpus["labels_license"] or "",
            "item_id": item["item_id"], "kind": item["kind"], "word": c["word"], "other_word": c["other_word"],
            "upos": c["upos"], "context": c["context"], "other_context": c["other_context"], "word_ref": c["word_ref"],
            "other_word_ref": c["other_word_ref"], "proposed_lemma": c["proposed_lemma"],
            "other_proposed_lemma": c["other_proposed_lemma"], "proposed_stem": c["proposed_stem"],
            "resolved_answer": item["resolved_answer"], "resolved_lemma": item["resolved_lemma"] or "",
            "resolution_source": item["resolution_source"],
            # A person's decision (adjudication or an owner check) carries no crowd confidence.
            "confidence_band": band(item["confidence"]) if item["resolution_source"] == "model" else "",
            "cell": item["cell"], "run_id": run["id"]})
    summary = io.StringIO()
    writer = csv.DictWriter(summary, fieldnames=SUMMARY_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    states = defaultdict(int)
    units = defaultdict(list)
    for item in items:
        states[(item["kind"], item["state"])] += 1
        values = [v["class"] for v in item["votes"] if v["class"] is not None and v["tier"] != "anchor"]
        if len(values) >= 2:
            units[item["kind"]].append(values)
    for (kind, state), n in sorted(states.items()):
        writer.writerow({"corpus_id": corpus["id"], "kind": kind, "measure": "items_in_state", "key": state, "value": n})
    for key, cell in sorted((run.get("calibration") or {}).items()):
        writer.writerow({"corpus_id": corpus["id"], "kind": cell["kind"], "measure": "calibration", "key": cell["cell"],
                         "value": f'{"passed" if cell["passed"] else "not passed"} {cell["correct"]}/{cell["n"]}'})
    for kind, values in sorted(units.items()):
        alpha = krippendorff_alpha(values)
        writer.writerow({"corpus_id": corpus["id"], "kind": kind, "measure": "krippendorff_alpha", "key": "nominal",
                         "value": "" if alpha is None else f"{alpha:.4f}"})
    provisional = sum(n for (_, state), n in states.items() if state == "provisional")
    card = DATASET_CARD.format(
        name=corpus["name"], released=released_on.isoformat(), run=run["id"], version=run["scoring_version"],
        params=run["params_sha256"], source=corpus["source_uri"], license=corpus["license"],
        labels_license=corpus["labels_license"] or "", rows=len(rows), total=len(items), provisional=provisional)
    files = {"labels.tsv": labels.getvalue(), "summary.tsv": summary.getvalue(), "dataset-card.md": card,
             "params.json": json.dumps(run["params"], sort_keys=True, indent=1, ensure_ascii=False) + "\n"}
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")
    checksums = "".join(f"{hashlib.sha256(content.encode('utf-8')).hexdigest()}  {name}\n"
                        for name, content in sorted(files.items()))
    (output / "CHECKSUMS").write_text(checksums, encoding="utf-8")
    return {"rows": len(rows), "items": len(items), "run_id": run["id"]}


DATASET_CARD = """# {name}: Croatian stemmer labels

Released {released} from scoring run `{run}` (scoring version {version}, parameters sha256 `{params}`).

## What this is

One row per item whose label is settled: by the trust-weighted crowd (`resolution_source = model`,
with a calibrated confidence band), by the curator (`adjudication`), or by the project's expert
checking crowd-resolved work (`reference`, `review`, no band: the label is a person's decision).
A model or expert-checked row appears only when at least three contributors voted on the item and
no single vote decides it. {rows} of the run's {total} scored items are released.

Nothing here is per contributor: no identifiers, no individual answers, no vote counts.

## Licence and attribution

Source sentences: {source}, licence {license}. This file contains them, so it is an adaptation
licensed {labels_license}. Labels: contributors to the Croatian stemmer labeling project, who
license their contributions under CC BY-SA 4.0 and waive any rights in the labels alone under
CC0 1.0. Attribute both the source corpus and "contributors to the Croatian stemmer labeling
project".

## Limitations

- Model resolutions are counted only in cells whose calibration passed; {provisional} items were
  provisional at this run and are not included.
- Contributors see the corpus suggestion on most items; errors that copy it are what the
  calibration cells measure, separately for answers that agree and disagree with it.
- summary.tsv gives the item states, the calibration per cell and Krippendorff's alpha.
"""


def check(directory: Path, export: Path, annotators: Path | None = None):
    """Fail closed (ValueError with every problem) unless the directory is exactly an allowed release."""
    run, corpus, items = read_export(export)
    problems = []
    present = {p.name for p in directory.iterdir()}
    if present != set(FILES):
        problems.append(f"files {sorted(present)} are not exactly {sorted(FILES)}")
    ids = {v["annotator_id"] for item in items for v in item["votes"]}
    if annotators is not None:
        for line in annotators.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)["annotator_id"])
    by_id = {item["item_id"]: item for item in items}
    for name, columns in (("labels.tsv", LABEL_COLUMNS), ("summary.tsv", SUMMARY_COLUMNS)):
        path = directory / name
        if not path.exists():
            continue
        reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")), delimiter="\t")
        if tuple(reader.fieldnames or ()) != columns:
            problems.append(f"{name}: columns {reader.fieldnames} are not the allowlist")
        for column in reader.fieldnames or ():
            if any(word in column.lower() for word in FORBIDDEN_IN_COLUMNS):
                problems.append(f"{name}: column {column!r} names per-contributor data")
        for number, row in enumerate(reader, 2):
            for column, value in row.items():
                if value and "@" in value:
                    problems.append(f"{name}:{number}: {column} contains '@'")
                if value in ids:
                    problems.append(f"{name}:{number}: {column} is an annotator id")
            if name != "labels.tsv":
                continue
            item = by_id.get(row.get("item_id"))
            if item is None:
                problems.append(f"labels.tsv:{number}: item not in the run export")
                continue
            if item.get("gold_pool") == "qualification" or (item.get("gold_pool") == "audit"
                                                            and item.get("gold_status") == "active"):
                problems.append(f"labels.tsv:{number}: a known-answer item still in use")
            source = row.get("resolution_source")
            if source in CHECKED_SOURCES:
                voters = {a for a, _, _ in (all_votes(item) if source == "model" else crowd(item))}
                if len(voters) < run["params"]["release_min_voters"] or not holds(item, run["params"]):
                    problems.append(f"labels.tsv:{number}: fewer than three crowd voters or a pivotal one")
            if row.get("confidence_band") and source != "model":
                problems.append(f"labels.tsv:{number}: a band on a person's decision")
    if problems:
        raise ValueError("release check failed:\n" + "\n".join(problems))
    return {"ok": True, "files": sorted(present)}
