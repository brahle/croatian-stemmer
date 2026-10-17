# Changelog

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
