# Changelog

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
