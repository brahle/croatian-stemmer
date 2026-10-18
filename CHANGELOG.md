# Changelog

## 0.3.0

Labeling web app: the trust system (version 2 of the labeling design). Deploy with
a pre-deploy database backup: migration 003 is forward-only (rollback is the
previous image plus a restore). Scoring is off after the migration; nobody is
profiled until the curator turns it on, which should follow reading the DPIA
(`docs/labeling-dpia.md`).

- Journals and runs. One journal sequence orders judgments, consents, admin
  events, trust events and item membership; a scoring run is a pure function
  of the journals up to a commit-safe watermark and its parameters, published
  only if no moderation event arrived meanwhile (otherwise it is superseded and
  rerun), and replayable offline from its restricted bundle
  (`croatian-stemmer-labels score --bundle`).
- The model. One-coin Dawid-Skene posteriors per item; per person and task kind
  an accuracy with gold-only promotion (`new`, `qualified`, `established`,
  `anchor`), weight ceilings, capped peer evidence and a calibration gate per
  kind and cell: items that meet the 0.95 rule stay `provisional` until 30
  sampled reference items show the rule holds there. One anchor answer never
  resolves an item alone; the owner's answer on a checked item is final.
- Gold. `croatian-stemmer-labels gold` builds bootstrap gold where the corpus is
  unambiguous; the curator imports it, sets, retires, retracts and discloses
  gold in the dashboard; the anchors' seed answers become consensus gold.
  Gold is invisible to annotators.
- Scheduling and admission. The announced knowledge check (first 12 items of a
  kind, without the suggestion), unannounced known-answer checks at a keyed
  rate, 20 % of pair and lemma showings without the suggestion, the experts'
  queues, and per-item budgets (5 low, 3 expert) applied at answer time. Answers
  need an item served by `/next` (409 `not_assigned`); annotator responses no
  longer carry word refs, the sampling stratum or the algorithm hash.
- Abuse resistance. Signals (fast, straight, accuracy, copy, review loss, burst)
  quarantine an account automatically at two hard flags; the quarantine is
  silent to the person, visible in their export, reviewed by the curator within
  14 days and lifted by the next run if nobody decides. Blocking stays a
  person's decision with a reason.
- Trusted list. Managed in the dashboard; a verified email on it makes the
  account an anchor; removal or erasure revokes it retroactively.
- People's view. "Moji podaci" shows a reliability card (tier and band per
  kind); the self-service export gains the complete trust section.
- Curator dashboard in tabs: overview and readiness, contributors, quarantine
  review, gold, disputed items (adjudicate, ambiguous, reopen), trusted
  addresses, scoring (runs, calibration, pins, bundles, agreement, parameters).
- Exports and releases. `resolved.tsv` and `resolved.jsonl` per run; public
  releases (`croatian-stemmer-labels release` and `release-check`) contain
  aggregate labels only, from items with at least three crowd voters and no
  pivotal one, and are published as GitHub release assets only.
- Data protection. Privacy notice 1.3 (hr/en) describes the profiling;
  everyone is asked to accept again. New public page "Kako radi pouzdanost"
  (`/legal/trust.hr`, `/legal/trust.en`, version 1.0, not part of the gate).
  Only people who accepted 1.3 are scored. Erasure also revokes anchors,
  deletes trusted-list identity, retracts consensus gold the person supported,
  deletes their scores and redacts their events. A daily retention job removes
  scores and computed item results 30 days after their run, answer timing after
  90 days and unanswered showings after 30 days. The DPIA is in
  `docs/labeling-dpia.md`; the model is described in `docs/trust.md`.
- New settings: `LABELING_SCORING_INTERVAL` (default 600 s),
  `LABELING_SCORING_RUN_TIMEOUT` (120 s), `LABELING_SCORING_MAX_JUDGMENTS`
  (2,000,000), each checked at startup. Deployments must set
  `LABELING_PRIVACY_VERSION=1.3`.

## 0.2.3

Labeling web app follow-ups to 0.2.2. Deploy with a pre-deploy database backup:
migration 002a is forward-only (rollback is the previous image plus a restore).

- Separate participation consent and age 18. New document, the participation
  statement 1.0 (hr/en): what is recorded, that the public receives only
  aggregated labels, how to withdraw, and what erasure keeps. The gate now links
  the privacy notice as information and has three unticked checkboxes: terms,
  participation statement, "I am at least 18". Consent rows record
  `age_threshold = 18`; a request for 16 is refused. Documents: privacy notice
  1.2, terms 1.1 (18+), participation statement 1.0. New setting
  `LABELING_PARTICIPATION_VERSION` (default `1.0`, checked against the shipped
  document at startup like the others). Deployments must set
  `LABELING_PRIVACY_VERSION=1.2`, `LABELING_TERMS_VERSION=1.1` and
  `LABELING_PARTICIPATION_VERSION=1.0`; everyone is asked to accept again.
- Profiles that never accept the gate are erased 30 days after the first
  sign-in by a daily background task, through the erasure path, which queues
  the Keycloak user for the curator. Signing in again before that deletion shows
  a notice worded for this case.
- The erasure request keeps only the Keycloak user id (`keycloak_user_id`, the
  token's `sub`) instead of username and email; the curator's list shows that
  id and completion still clears it.
- Erasure keeps the answers under a new random identifier: the person's
  judgments and consents move to a fresh erased annotator with new row ids,
  day-level timestamps and no timing, and nothing records the old-to-new link.
  A blocked or set-aside person's answers and consents are deleted instead.
  The append-only triggers allow exactly this move and the deletion of an
  erased annotator's rows.
- Erasure-safe profile refresh: the periodic email refresh no longer writes the
  email back onto a profile erased meanwhile (the request gets 409
  `erasure_pending`), and consent, `/next` and `/answer` refuse to write for a
  profile erased after the request was authenticated. Migration 002a clears any
  email such a race left and forbids emails on erased rows.

## 0.2.2

- Privacy notice 1.1 (hr/en): states that the profile (sign-in account
  identifier and verified email) is created at first sign-in, before
  acceptance, on the basis of Article 6(1)(b), records nothing else until
  acceptance, and is kept until erased even if the person never accepts.
  Deployments must set `LABELING_PRIVACY_VERSION=1.1` with this release;
  everyone is asked to accept again.

## 0.2.1

Labeling web app fixes from the first live sign-in.

- Croatian is the default language for every visitor; English only with
  `?lang=en`, which the language switch now writes to the address so a reload
  keeps it.
- Reloading the page no longer signs you out. After sign-in the tab keeps a
  token-free `labeling-signed-in` marker in sessionStorage; on reload the page
  asks Keycloak for the existing session (`prompt=none`) and comes straight
  back. The cookies and storage notice is now version 1.1 and lists it.

## 0.2.0

The labeling web app becomes a public, multi-user site. The stemmer and the
offline `croatian-stemmer-labels` tools are unchanged.

- Shared corpora: a curator (Keycloak group `curator`) imports candidates and
  publishes a corpus under a labels licence compatible with the source licence;
  annotators label published corpora through `/next`. Per-annotator revisions;
  people never block each other.
- Anyone with an account in the realm can take part with
  `LABELING_ANNOTATOR_POLICY=open` (`group`, the default, keeps the role check).
  `LABELING_OIDC_IDP_HINT` sends the sign-in button straight to an identity
  provider such as Google.
- Provenance on every judgment: pseudonymous annotator id, server time, item
  revision, UI version, source and time taken. Database triggers keep the
  judgment, consent and admin journals append-only.
- Privacy notice, terms of participation and licence, and a storage notice, in
  Croatian and English (drafts for review), with a consent gate and age 16+
  confirmation. Self-service JSON export and erasure. New required settings:
  `LABELING_CONTROLLER_NAME`, `LABELING_CONTROLLER_EMAIL`,
  `LABELING_HOSTING_SUMMARY`, `LABELING_EDGE_LOG_RETENTION`,
  `LABELING_BACKUP_RETENTION`.
- Curator panel: import, publish, exports (TSV schema v1 and JSONL), annotator
  status (quarantine, block), a kill switch, and erasure completion.
- Rate limits and a daily cap per annotator; `LABELING_READ_ONLY`.
- The interface is Croatian with an English version, keyboard shortcuts, and
  annotation guidelines.
- Migration 002 replaces the 0.1 tables and refuses to run while judgments exist
  unless `LABELING_MIGRATION_ALLOW_DROP=true`. Export first.

## 0.1.1

- Ship `py.typed`, so type checkers use the package's annotations.
- Leave the labeling web app out of the wheel. It could not run from an
  installed wheel (its JS assets and migrations are not packaged); run it from a
  checkout or the `Dockerfile.web` container. The offline `croatian-stemmer-labels`
  command is unchanged.
- `croatian_stemmer.__version__` now comes from the installed package metadata.
- README: how the rules were tuned and the full repository layout.
- The sdist now carries `docs/labeling.md` and no longer carries `tests/web`,
  `docs/research.md` or `.gitignore`.

## 0.1.0

First release. A rule-based Croatian stemmer extending the Ljubešić–Pandžić
v0.1 rules with verb, participle, jotation and fleeting-*a* handling, tuned on
hr500k and checked on held-out ParlaMint-HR. Ships as a Python library with a
`croatian-stemmer` command, and as the `dict_croatian_stem` PostgreSQL text
search dictionary that produces identical stems. Includes offline tools for
preparing and scoring human labels (`croatian-stemmer-labels`).
