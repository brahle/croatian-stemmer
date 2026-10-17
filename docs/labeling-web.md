# Human labeling application

The app stores candidate questions separately from an append-only answer journal.
Imports never create annotations. Each signed-in user owns a separate corpus
namespace, even when two users import the same corpus UUID. TSV exports include
all revisions; the shared evaluator resolves the latest answer per annotator.
Invitations and shared browser adjudication are follow-up work.

## Local development

The web app runs from a source checkout or from the container image
(`Dockerfile.web`), not from the PyPI package: the wheel leaves out
`croatian_stemmer.labeling.web`, because its JavaScript assets are built by npm
and its Alembic migrations live outside the package. The `web` extra installs the
app's Python dependencies into a checkout. The offline `croatian-stemmer-labels`
command does ship in the wheel.

Use Python 3.10+ (CI runs the web suite on 3.14), Node 22 and PostgreSQL. The
base stemmer has no web dependency; install the optional application
dependencies explicitly:

```sh
uv sync --frozen --extra web --extra dev
npm ci --ignore-scripts
npm run build
export LABELING_DATABASE_URL='postgresql+asyncpg://USER:URI_ENCODED_PASSWORD@HOST:5432/labeling'
export LABELING_OIDC_ISSUER='https://YOUR_KEYCLOAK/realms/YOUR_REALM'
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn croatian_stemmer.labeling.web.serve:app --port 8000
```

`LABELING_OIDC_CLIENT_ID`, `LABELING_OIDC_AUDIENCE` and `LABELING_OIDC_ROLE`
default to `croatian-stemmer-labeling-web`, `croatian-stemmer-labeling-api` and
`annotator`. The issuer is mandatory and must use HTTPS. `LABELING_ALLOW_LOCAL_HTTP=true`
permits only a loopback HTTP issuer for the synthetic test fixture; it does not
skip authentication. Keep it absent in deployment.

Prepare candidates using the offline command in [labeling.md](labeling.md),
then import its JSONL in the UI. Each upload must contain one corpus, at most
20,000 candidates and at most 32 MiB of JSON. Split larger candidate sets into
multiple uploads; existing source questions and saved answers remain intact.
No source corpus or human export is committed to this repository.

## Identity provider registration

The browser side uses the Keycloak JavaScript adapter, so the issuer must be a
Keycloak realm (`https://KEYCLOAK_HOST/realms/REALM`).

Register a **public** browser client `croatian-stemmer-labeling-web` with standard
flow and PKCE S256 required. Disable implicit flow, direct grants and service
accounts. Set exact app redirect URI (`https://APP_HOST/`), post-logout redirect
URI and Web Origin; do not use wildcards. The adapter keeps access and refresh
tokens in memory. It stores short-lived authorization callback state, not tokens.

Create the API audience client `croatian-stemmer-labeling-api` and its client role
`annotator`. Add an audience mapper to browser-client access tokens, and map the
API client role into `resource_access.croatian-stemmer-labeling-api.roles`.
Assign that role explicitly to participating human accounts.

Alternatively, set `LABELING_OIDC_ROLE_SOURCE=groups` to read authorization from a
flat `groups` claim instead (exact group name, not a path). Use this with a realm
that has a group mapper emitting names (full path off) and an audience mapper that
adds `croatian-stemmer-labeling-api` to the browser client's access tokens; members
of group `annotator` may label. The default, `client-role`, ignores `groups`
entirely, and `groups` mode ignores `resource_access`; no deployment accepts both.
Because the mapper emits names, not paths, any group named `annotator`, including
a subgroup with that name anywhere in the realm, grants labeling access.

The backend accepts only RS256 access tokens with the configured issuer/audience, required expiry,
issue time and subject, `typ=Bearer`, browser client `azp`, and annotator role.
ID tokens and service-client access tokens cannot label data. JWKS refresh fails
closed after the five-minute cache expires. A failed refresh imposes a
ten-second retry cooldown starting after the failed fetch completes, shared by
queued requests; they receive 503 without serially repeating the eight-second
fetch timeout. A successful refresh resumes normal validation. Fresh cached
known keys retain normal validation; expired keys are not accepted during an
outage. No user IDs or timestamps are accepted from the answer payload.

A submitted answer includes the last revision and a request UUID. Concurrent
edits receive HTTP 409 and reload the current answer. If a save response is lost,
the UI retains the UUID and exact payload for an idempotent retry. Old revisions
are retained. Unsure answers withdraw previous definite judgments from current
progress without erasing the journal.

## Verification

Create a separate PostgreSQL database whose name ends in `_test`, then run:

```sh
uv sync --frozen --extra web --extra dev
npm ci --ignore-scripts
npx playwright install chromium  # add --with-deps on a minimal Linux host
export LABELING_TEST_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/labeling_test'
./scripts/test-web.sh
```

The script runs Alembic upgrade/check, the full Python suite and Chromium.
The loopback OIDC fixture verifies real PKCE challenges/nonces and signs RS256
JWTs. It is test-only code, outside the packaged application. All browser answers
use `urn:test` questions and never count as human gold. API tests cover ownership,
immutable imports, cross-kind rejection, stale revisions, concurrent writers,
idempotency, streamed export and body bounds. JWT tests cover issuer/audience,
expiry, algorithms, role shapes, service-client rejection, rotation and JWKS failure.

## Container image

`Dockerfile.web` locks Python dependencies with hashes, the official browser
adapter with the npm lock, and the Python/Node base images with verified registry
digests. It runs as UID 10001, serves one worker on port 8000, bundles the adapter
and its Apache license, and performs no migration automatically during normal
startup. Update `requirements-web.txt` from `uv.lock` with:

```sh
uv export --frozen --extra web --no-dev --no-emit-project --output-file requirements-web.txt
```

Releases are semver. `./build.sh` builds a clean commit for linux/amd64 and loads
it locally as `croatian-stemmer/labeling:v<version>`, where the version is
`[project].version` in `pyproject.toml`. `REGISTRY=registry.example.com/team
./build.sh --push` pushes `registry.example.com/team/labeling:v<version>` instead
and prints its digest; it refuses to overwrite an existing tag. Pin that exact tag
in your deployment, never `latest`.

## Deploying

The application is one stateless container plus a PostgreSQL database. What a
deployment needs:

- Environment: `LABELING_DATABASE_URL` (a `postgresql+asyncpg://` URL; URL-encode
  the password) and `LABELING_OIDC_ISSUER` (HTTPS) are required.
  `LABELING_OIDC_CLIENT_ID`, `LABELING_OIDC_AUDIENCE`, `LABELING_OIDC_ROLE` and
  `LABELING_OIDC_ROLE_SOURCE` are optional, with the defaults above. Never set
  `LABELING_ALLOW_LOCAL_HTTP` outside tests.
- Migrations: run `python -m alembic upgrade head` with the same
  `LABELING_DATABASE_URL` before the app serves, for example as an init container
  or a one-off job using the same image. It is idempotent.
- One replica. The initial migration design assumes a single writer.
- Probes: `/healthz` for liveness and `/readyz` for readiness, both on port 8000.
- The container runs as a non-root user and works with a read-only root
  filesystem. It needs outbound HTTPS to the issuer for JWKS and inbound HTTP on
  8000 from your TLS-terminating proxy.
- Back up the database. The answer journal is the only copy of human judgments;
  TSV exports are a useful second copy.

Before accepting human labels, check real sign-in with an `annotator` member, a
403 for a non-member, two-account isolation, revise/export/re-import, and
persistence across a restart.

Roll back the application image first. Alembic's initial downgrade deletes the
label tables and is for disposable test databases only; preserve backups and
exports before any destructive schema operation.

Then enroll diverse, licensed corpus sources, collect an actual human pilot and
report agreement/coverage. Reach at least 10,000 **new human pair judgments**.
Candidate counts, synthetic tests and extra revisions cannot satisfy that
criterion.
