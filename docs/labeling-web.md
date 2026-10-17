# Human labeling application

A public, multi-user site where people sign in, accept the terms and the
participation statement, and label items from shared corpora that a curator has
published. Every
judgment is stored with provenance in an append-only journal. Imports never
create annotations. TSV exports include all revisions; the shared evaluator
resolves the latest answer per annotator.

The pieces:

- **Annotators** are people with an account in the Keycloak realm. Each gets a
  random pseudonymous id (`label_annotator.id`); that id, never the login
  subject or email, is what judgments reference and exports print as
  `annotator_id`.
- **Curators** (Keycloak group `curator`) import candidate files, publish a
  corpus under a labels licence, export judgments, set an annotator's status
  (`active`, `quarantined`, `blocked`), pause intake, and complete erasures.
- **Corpora** are shared: one copy per corpus id for everybody. A corpus is a
  `draft` until published; annotators see published corpora only.
- **Judgments** are per annotator per item, with revisions. Each row records
  who (pseudonym), when (server clock), the item revision, the UI version
  (`client_version`), how it arrived (`source`) and the time taken
  (`elapsed_ms`, curator-only, removed on erasure). Database triggers keep
  `label_judgment`, `label_consent` and `label_admin_event` append-only apart
  from what erasure does (see "Consent, legal documents and data-subject
  rights").

## Local development

The web app runs from a source checkout or from the container image
(`Dockerfile.web`), not from the PyPI package: the wheel leaves out
`croatian_stemmer.labeling.web`, because its JavaScript assets are built by npm
and its Alembic migrations live outside the package. The `web` extra installs the
app's Python dependencies into a checkout. The offline `croatian-stemmer-labels`
command does ship in the wheel.

Use Python 3.10+ (CI runs the web suite on 3.14), Node 22 and PostgreSQL:

```sh
uv sync --frozen --extra web --extra dev
npm ci --ignore-scripts
npm run build   # vendors the Keycloak adapter and writes static/version.js
export LABELING_DATABASE_URL='postgresql+asyncpg://USER:URI_ENCODED_PASSWORD@HOST:5432/labeling'
export LABELING_OIDC_ISSUER='https://YOUR_KEYCLOAK/realms/YOUR_REALM'
export LABELING_CONTROLLER_NAME='Example Project Lead'
export LABELING_CONTROLLER_EMAIL='privacy@example.org'
export LABELING_HOSTING_SUMMARY='Example Hosting Ltd, Germany'
export LABELING_EDGE_LOG_RETENTION='7 days'
export LABELING_BACKUP_RETENTION='14 days'
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn croatian_stemmer.labeling.web.serve:app --port 8000
```

Prepare candidates with the offline command in [labeling.md](labeling.md), sign
in as a curator, import the JSONL in the curator panel and publish the corpus.
Each upload must contain one corpus, at most 20,000 candidates and at most 32 MiB
of JSON. No source corpus or human export is committed to this repository.

## Configuration

Required:

| Variable | Example | Meaning |
|---|---|---|
| `LABELING_DATABASE_URL` | `postgresql+asyncpg://labeling:…@db:5432/labeling` | PostgreSQL via asyncpg; URL-encode the password |
| `LABELING_OIDC_ISSUER` | `https://login.example.org/realms/labeling` | Keycloak realm, HTTPS |
| `LABELING_CONTROLLER_NAME` | `Example Project Lead` | data controller named in the notices and on the landing page |
| `LABELING_CONTROLLER_EMAIL` | `privacy@example.org` | contact for privacy requests and appeals |
| `LABELING_HOSTING_SUMMARY` | `Example Hosting Ltd, Germany` | hosting provider and country, named as a processor |
| `LABELING_EDGE_LOG_RETENTION` | `7 days` | how long the reverse proxy in front of the app keeps access logs |
| `LABELING_BACKUP_RETENTION` | `14 days` | how long database backups are kept |

Optional:

| Variable | Default | Meaning |
|---|---|---|
| `LABELING_CONTROLLER_ADDRESS` | unset | postal address; the notices leave the address out when unset |
| `LABELING_ANNOTATOR_POLICY` | `group` | `open`: any human account of the realm may label; `group`: only holders of the annotator role/group |
| `LABELING_OIDC_ROLE_SOURCE` | `client-role` | where roles are read: `client-role` or `groups` (see below) |
| `LABELING_OIDC_ROLE` | `annotator` | annotator role/group (used by `group` policy) |
| `LABELING_CURATOR_GROUP` | `curator` | curator group name (`groups` source) |
| `LABELING_CURATOR_ROLE` | `curator` | curator client role (`client-role` source) |
| `LABELING_OIDC_IDP_HINT` | unset | Keycloak identity-provider alias, e.g. `google`; the sign-in button then goes straight to it |
| `LABELING_OIDC_CLIENT_ID` | `croatian-stemmer-labeling-web` | public browser client |
| `LABELING_OIDC_AUDIENCE` | `croatian-stemmer-labeling-api` | required token audience |
| `LABELING_PRIVACY_VERSION`, `LABELING_TERMS_VERSION`, `LABELING_PARTICIPATION_VERSION` | `1.2`, `1.1`, `1.0` | document versions people must accept; must equal the versions the shipped documents declare |
| `LABELING_DAILY_CAP` | `3000` | judgments per annotator per 24 hours |
| `LABELING_TARGET_VOTES` | `3` | `/next` stops serving an item once this many people gave a definite answer |
| `LABELING_READ_ONLY` | `false` | `true` pauses intake regardless of the curator's setting |
| `LABELING_ALLOW_LOCAL_HTTP` | `false` | test-only: allows a loopback HTTP issuer; never set it in a deployment |
| `LABELING_MIGRATION_ALLOW_DROP` | unset | see "Migrations" |

The app refuses to start when a required value is missing, when a document's
declared version differs from the configured one, or when the Croatian and
English versions of a document differ.

## Identity

The browser uses the Keycloak JavaScript adapter with PKCE S256, so the issuer
must be a Keycloak realm. Register a **public** browser client
`croatian-stemmer-labeling-web` with standard flow and PKCE required; disable
implicit flow, direct grants and service accounts; set exact redirect URI
(`https://APP_HOST/`), post-logout redirect URI and Web Origin, no wildcards.
Add an audience mapper so access tokens carry `croatian-stemmer-labeling-api`.
The adapter keeps tokens in memory; the page does not contact the identity
server until the person clicks sign in.

To let anyone with a Google account take part, add Google as an identity
provider of the realm (with "trust email" on) and set
`LABELING_OIDC_IDP_HINT=google` and `LABELING_ANNOTATOR_POLICY=open`. Enable the
identity provider only after the notices are published and the app serves the
consent gate: Google's OAuth consent screen needs the public privacy notice URL
(`https://APP_HOST/legal/privacy.en`).

Roles come from one source only:

- `LABELING_OIDC_ROLE_SOURCE=groups` reads a flat `groups` claim of group names
  (a group mapper with full path off). Members of `curator` are curators;
  members of `annotator` may label under `group` policy. Any group with that
  exact name, including a subgroup anywhere in the realm, grants the role.
- `client-role` (the default) reads `resource_access.<audience>.roles` and
  ignores `groups` entirely.

The backend accepts only RS256 access tokens with the configured issuer and
audience, required expiry, issue time and subject, `typ=Bearer`, the browser
client as `azp`, and no `service-account-` username, in every policy. ID tokens
and service-client tokens cannot label. An email address is stored only when the
token says it is verified. JWKS refresh fails closed after the five-minute cache
expires, with a ten-second shared cooldown after a failed fetch.

Each route declares its authorization in code (`api.py` lists the dependencies):
public (`/`, `/static`, `/legal/*`, `/api/config`, probes); any signed-in
annotator including a blocked one (`/api/me`, `/api/me/export.json`,
`/api/me/erase`); a non-blocked annotator; one who accepted the current
documents (`/next`, `/items`, `/answer`); and curator (`/api/import`, publish,
unpublish, archive, exports, `/api/admin/*`).

## Consent, legal documents and data-subject rights

`/legal/{privacy,terms,participation,storage}.{hr,en}` serve the privacy notice,
the terms of participation and licence, the participation statement (the
consent to recording answers) and the cookie and storage notice, with the
controller values substituted from configuration. The templates are in
`src/croatian_stemmer/labeling/web/documents/`; the controller reviews and
publishes them (there is no external legal review). Each declares
`<meta name="document-version">`. Publishing a new version means editing the
documents and the matching `LABELING_*_VERSION` together; everyone is asked to
accept again before their next answer, and earlier consent records are kept.

The consent gate links the privacy notice as information and has three
separate, unticked checkboxes: the terms (including the CC BY-SA 4.0 licence of
contributions and a CC0 waiver for labels alone), the participation statement,
and age 18 or over. `POST /api/me/consent` records one row per document
(privacy, terms, participation) with `age_threshold = 18`. Without all three at
the configured versions and age 18, `/next`, `/items` and `/answer` return 403
`consent_required`.

A profile is created at the first sign-in, before the gate. A daily background
task erases active profiles that have no consent row 30 days after they were
created, through the same erasure path (no actor; the `erasure.requested` event
carries `reason: unconsented_expiry`), which queues the Keycloak user for the
curator. Signing in again before that deletion shows a notice worded for this
case (409 `erasure_pending` with the reason).

"My data" offers a JSON export of everything linked to the pseudonym and
erasure. Erasure, in one transaction, records an erasure request, nulls the
subject and email and deletes the assignment rows. The person's judgments and
consent records move to a new erased annotator id: each row gets a fresh id,
its time is cut to the UTC day and `elapsed_ms` is dropped, and nothing records
which new id followed which old one. If the person was `blocked` or
`quarantined` at that moment, their judgments and consents are deleted instead.
The triggers allow exactly this move and the deletion of an erased annotator's
rows. Requests authenticated just before an erasure commits cannot write to
the erased profile (409 `erasure_pending`), and a profile refresh never writes
an email back onto an erased row.

Until the curator has deleted the Keycloak user, signing in again returns 409
`erasure_pending` rather than creating a new profile. The curator panel lists
pending requests with the Keycloak user id (the token's `sub`) to delete; after
deleting the user in the Keycloak admin console, the curator confirms, which
removes the stored id. The app logs a warning (with the request id only) for
requests older than 14 days, so the 30-day limit is not missed. If a database
backup taken before an erasure is ever restored, re-apply the erasures
requested after it.

The app origin sets no cookies and no persistent storage; the adapter's
short-lived `kc-callback-*` record is removed when sign-in completes. The
browser test enforces this; any feature that stores something must update the
storage notice and that test first.

## Labeling, limits and the kill switch

`GET /api/corpora/{id}/next?kind=` returns one item the caller has not answered,
not shown to them in the last 30 minutes, and with fewer than
`LABELING_TARGET_VOTES` definite answers (fewest first). Skipped items come back
after 30 minutes. `/items?state=mine_labelled|mine_unsure` are the caller's own
review queues. No response contains another person's answers.

An answer carries the last revision (`base_revision`), a request UUID,
`client_version` and optionally `elapsed_ms`. Concurrent edits by the same
person get 409 and reload; different people never block each other. A lost
response is retried with the same UUID and payload, which is idempotent.

Limits per annotator: 15 answers burst and 30 per minute, 120 queue reads per
minute, 10 consent/export/erasure calls per hour (in process; they reset on
restart), and `LABELING_DAILY_CAP` judgments per 24 hours (counted in the
database). Bodies are limited to 16 KiB, imports to 32 MiB. The curator's
"pause" switch, or `LABELING_READ_ONLY=true`, makes `/answer` return 503
`judgments_paused` without writing anything.

Publishing checks licences: share-alike sources (hr500k is CC BY-SA 4.0) may
only be published as CC BY-SA 4.0; CC BY sources as CC BY 4.0 or CC BY-SA 4.0;
CC0/public domain as any of the three; NC, ND or unknown licences are refused.

Exports (curator): `export.tsv` is schema v1 and feeds the offline evaluator
unchanged; `export.jsonl` has every judgment column plus the candidate and the
annotator status. Judgments of blocked annotators (also after they erase their
account) are left out unless `?include_excluded=true`.

## Verification

Create a separate PostgreSQL database whose name ends in `_test`, then run:

```sh
uv sync --frozen --extra web --extra dev
npm ci --ignore-scripts
npx playwright install chromium  # add --with-deps on a minimal Linux host
export LABELING_TEST_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/labeling_test'
./scripts/test-web.sh
```

The script runs Alembic upgrade/check, the full Python suite and Chromium. The
migration guard test creates and drops a scratch database, so the test role
needs `CREATEDB`. The loopback OIDC fixture verifies real PKCE challenges and
nonces and signs RS256 tokens for named synthetic people, one of them a curator.
All browser answers use `urn:test` questions and never count as human gold.

## Container image

`Dockerfile.web` locks Python dependencies with hashes, the official browser
adapter with the npm lock, and the base images with registry digests. It runs as
UID 10001, serves one worker on port 8000 and performs no migration during
normal startup. Update `requirements-web.txt` from `uv.lock` with:

```sh
uv export --frozen --extra web --no-dev --no-emit-project --output-file requirements-web.txt
```

Releases are semver. `./build.sh` builds a clean commit for linux/amd64 and loads
it locally as `croatian-stemmer/labeling:v<version>`. `REGISTRY=registry.example.com/team
./build.sh --push` pushes `registry.example.com/team/labeling:v<version>` and
prints its digest; it refuses to overwrite an existing tag. Pin that exact tag,
never `latest`.

## Deploying

The application is one stateless container plus a PostgreSQL database:

- Environment: see "Configuration".
- Migrations: run `python -m alembic upgrade head` with the same
  `LABELING_DATABASE_URL` before the app serves, for example as an init container.
  Migration 002 (0.2.0) drops the 0.1 tables. It refuses to run while
  `label_judgment` has rows unless `LABELING_MIGRATION_ALLOW_DROP=true`; export
  and back up first. Never set that variable permanently. Migration 002a
  (0.2.3) is forward-only: it adds the participation consent and the confirmed
  age, clears any email left on an erased profile and lets erasure move or
  delete a person's rows. Take a backup before deploying it.
- One replica. Rate limits are in process and migrations run per pod.
- Probes: `/healthz` for liveness and `/readyz` for readiness, on port 8000.
- The container runs as a non-root user with a read-only root filesystem. It
  needs outbound HTTPS to the issuer for JWKS and inbound HTTP on 8000 from your
  TLS-terminating proxy.
- Back up the database. The judgment journal is the only copy of human answers.

Roll back the application image first. From 0.2.3 a rollback is the previous
image plus a restore of the pre-deploy backup; `alembic downgrade` refuses to
undo 002a. Downgrading 002 recreates the 0.1 tables empty and is only for a
database with nothing worth keeping.
