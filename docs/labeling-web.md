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
  (`active`, `quarantined`, `blocked`), pause intake, and complete erasures. From
  0.3.0 they also run the trust system: the trusted list, known-answer items,
  disputed items, scoring runs and releases (see "Trust system").
- **Corpora** are shared: one copy per corpus id for everybody. A corpus is a
  `draft` until published; annotators see published corpora only.
- **Judgments** are per annotator per item, with revisions. Each row records
  who (pseudonym), when (server clock), the item revision, the UI version
  (`client_version`), how it arrived (`source`) and the time taken
  (`elapsed_ms`, curator-only, removed after 90 days and on erasure), and from
  0.3.0 whether the item was shown with or without the suggestion
  (`presentation`) and whether the answer was admitted as a vote. Database
  triggers keep `label_judgment`, `label_consent`, `label_admin_event`,
  `label_trust_event` and `label_item_audit` append-only apart from what erasure
  and the timing retention do (see "Consent, legal documents and data-subject
  rights" and "Trust system").

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
| `LABELING_PRIVACY_VERSION`, `LABELING_TERMS_VERSION`, `LABELING_PARTICIPATION_VERSION` | `1.4`, `1.1`, `1.0` | document versions people must accept; must equal the versions the shipped documents declare. Privacy 1.3 (0.3.0) describes trust scoring; only people who accepted 1.3 or later are scored. Privacy 1.4 (0.3.3) adds IT service providers as processors, their transfers and the erasure list |
| `LABELING_DAILY_CAP` | `3000` | judgments per annotator per 24 hours |
| `LABELING_TARGET_VOTES` | `3` | before scoring is enabled and while a corpus has no known-answer items, `/next` stops serving an item once this many people gave a definite answer; afterwards the trust scheduler's vote budgets apply instead |
| `LABELING_SCORING_INTERVAL` | `600` | seconds between scheduled scoring runs (60 to 86400); a tick does nothing while scoring is off |
| `LABELING_SCORING_RUN_TIMEOUT` | `120` | seconds a scoring run may take before it fails (10 to 3600) |
| `LABELING_SCORING_MAX_JUDGMENTS` | `2000000` | a run fails with `too_many_judgments` above this many judgments (1000 to 50,000,000); lower it to fit the pod's memory (about 400 bytes per judgment) |
| `LABELING_METRICS_PORT` | `0` (off) | when set (1024 to 65535), a second listener on this port serves Prometheus metrics at `GET /metrics`; see "Metrics" |
| `LABELING_METRICS_HOST` | `0.0.0.0` | the IP address the metrics listener binds |
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
annotator including a blocked one (`/api/me`, `/api/me/trust`,
`/api/me/export.json`, `/api/me/erase`); a non-blocked annotator; one who
accepted the current documents (`/next`, `/api/next`, `/items`, `/answer`); and
curator (`/api/import`, publish, unpublish, archive, exports, the resolved
exports, `/api/admin/*`).

## Consent, legal documents and data-subject rights

`/legal/{privacy,terms,participation,storage}.{hr,en}` serve the privacy notice,
the terms of participation and licence, the participation statement (the
consent to recording answers) and the cookie and storage notice, with the
controller values substituted from configuration. `/legal/trust.{hr,en}` ("Kako
radi pouzdanost", 0.3.0) explains the trust system to participants, with the
formulas of [trust.md](trust.md) in an appendix; it has its own version and is
not part of the gate. The templates are in
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
`consent_required`. 0.3.0 ships privacy notice 1.3, which adds the section on
trust scoring (profiling), so everyone is asked again before their next answer.
Scoring uses only the profiling cohort: people with privacy 1.3 or later, terms
1.1 and participation 1.0, all with age 18. Answers of anyone else are stored but
not scored or counted until they pass the 1.3 gate; the next run then includes
their earlier answers. 0.3.3 ships privacy notice 1.4 (IT service providers,
including AI-assisted development and operations tools, as processors; their
transfers; the 60-day erasure list), so everyone accepts again; people who had
accepted 1.3 stay in the cohort.

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

From 0.3.0 the same transaction also covers the trust system's stores: the
details of every other admin and trust event about the old id are reduced to
kind, from, to and run id (no reasons, flags or signal values); known-answer
items the person supported as an anchor are retracted (`gold.retracted`, reason
`erasure`) and their support is redacted to `{"redacted": true}`; their anchor
status is revoked; a trusted-list entry matching their verified email loses its
email, hash and label; and their score rows are deleted from every run, pinned
runs included. The new id starts with no tier memory and no anchor status and is
scored from the moved answers at the next run, so their answers keep counting;
earlier public releases are never rewritten.

Until the curator has deleted the Keycloak user, signing in again returns 409
`erasure_pending` rather than creating a new profile. The curator panel lists
pending requests with the Keycloak user id (the token's `sub`) to delete; after
deleting the user in the Keycloak admin console, the curator confirms, which
removes the stored id. The app logs a warning (with the request id only) for
requests older than 14 days, so the 30-day limit is not missed. If a database
backup taken before an erasure is ever restored, re-apply the erasures
requested after it (see "Erasure and restore" under "Trust system").

The app origin sets no cookies and no persistent storage; the adapter's
short-lived `kc-callback-*` record is removed when sign-in completes. The
browser test enforces this; any feature that stores something must update the
storage notice and that test first.

## Labeling, limits and the kill switch

`GET /api/corpora/{id}/next?kind=` returns one item the caller has not answered
and that was not shown to them in the last 30 minutes. Until scoring is enabled
and while the corpus has no known-answer items, it keeps the V1 order: items with
fewer than `LABELING_TARGET_VOTES` definite answers, fewest first. After that the
trust scheduler decides (see "Trust system"): the announced qualification items,
unannounced known-answer checks, the anchors' expert queues, then items by
priority within the per-item vote budgets. `GET /api/next?kind=` does the same
across published corpora, starting with the one with the lowest share of
resolved items; the UI calls it "Bilo koji korpus". Skipped items come back
after 30 minutes. `/items?state=mine_labelled|mine_unsure` are the caller's own
review queues. No response contains another person's answers, and no response
differs between a known-answer item and another item except in the item itself.

An answer carries the last revision (`base_revision`), a request UUID,
`client_version` and optionally `elapsed_ms`. From 0.3.0 an answer is accepted
only for an item that `/next` served to the caller (or one they already
answered); anything else gets 409 `not_assigned` and writes nothing. Concurrent
edits by the same person get 409 and reload; different people never block each
other. A lost response is retried with the same UUID and payload, which is
idempotent. A first answer beyond an item's vote budget, or from someone whose
votes are not counted, is still stored and gets the same 200; it is simply not
counted as a vote.

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
account) are left out unless `?include_excluded=true`. These are the raw,
unweighted judgments; the trust-weighted labels are in the resolved exports
described under "Trust system".

## Trust system

From 0.3.0 every counted answer is a vote weighted by its author's demonstrated
accuracy. Scoring runs compute, per annotator and kind, an accuracy θ, a tier, a
weight and abuse flags, and per item a posterior and a state; the model is in
[trust.md](trust.md) and the data-protection assessment in
[labeling-dpia.md](labeling-dpia.md). This section is for operators.

### Turning scoring on

Migration 003 sets `scoring_enabled` to false, so deploying 0.3.0 runs no scoring
and profiles nobody. Switch it on in the dashboard only when all of these hold:

1. The owner has signed off the DPIA ([labeling-dpia.md](labeling-dpia.md)).
2. The owner is on the trusted list ("Pouzdane adrese"), has signed in and passed
   the current gate, and the anchor badge shows in "Suradnici".
3. The hr500k known-answer items are imported ("Zlatni primjeri", below).

Then switch scoring on ("Pregled") and verify: one `done` run in "Bodovanje";
readiness shows qualification on and promotion off for `pair` and `lemma`, and
`stem` not ready. The owner then works the expert queues as time allows. Keep
watching: quarantines reviewed within 14 days, contested known-answer items,
calibration per cell, inter-annotator agreement and superseded runs. Switching
scoring off stops runs without a deploy; the existing pause switch still stops
intake.

### The curator dashboard

- "Pregled": intake, scoring on or off, the last run, alerts, readiness per kind,
  item states, import, corpora and erasures.
- "Suradnici": annotators with tiers, θ, flags and the anchor badge.
- "Karantena": open quarantines with their evidence; release, keep or block, each
  with a reason.
- "Zlatni primjeri": import of known-answer items, the pools, and retire,
  reactivate, retract or disclose per item.
- "Sporni primjeri": the queue of `contested`, `needs_expert` and `provisional`
  items; adjudicate, mark ambiguous, or reopen with or without discarding earlier
  answers.
- "Pouzdane adrese": the trusted list, an email and a note of at most a first
  name per entry. A verified sign-in with a listed email becomes an anchor; removing
  the entry revokes it. The list never leaves the dashboard.
- "Bodovanje": run now, calibration per cell with redraw, the runs with pin, bundle
  download and "Zabilježi izdanje", Krippendorff's alpha per corpus, and the
  parameter editor.

### Runs

A run is a pure function of the append-only journals up to a commit-safe
watermark and of the parameter set copied into its row. While scoring is on, a
background task checks every `LABELING_SCORING_INTERVAL` seconds and starts a run
if the journals have grown or the UTC day has changed since the last done run;
"run now" starts one at once (409 `scoring_busy` if one is running). Only one run
runs at a time. A run ends `done`, `failed` (with the error, never row contents;
three failures in a row raise an alert) or `superseded`: if a moderation event
(a status change, an erasure, a trusted-list or anchor change, a clear, a
known-answer or item decision by the curator, a parameter change or a calibration
redraw) committed after the watermark, the run is discarded and rerun at once, up
to three times in a row. Publication takes a lock that moderation writers share,
so a run can never publish over a block, a clear or an erasure it did not see. A
published run whose watermark is followed by a moderation event is stale: its
exports carry `X-Labeling-Run-Stale: true` and it cannot be pinned (409
`run_stale`).

Automatic quarantines and releases are applied when a run publishes. Blocking,
releasing, revoking an anchor, retracting or correcting a known answer and item
decisions take effect at the next run, because every run recomputes from the
journals; "run now" applies them at once.

Parameters: the editor replaces the whole parameter set, which is validated (every
key present, every number within bounds) and journaled with its hash and a diff.
Changing anything that can alter a vote, weight, tier or state draws new
calibration sets at the next run, reusing references the owner already gave.

### Known-answer items and the owner's expert work

Build the hr500k known-answer file offline with `croatian-stemmer-labels gold` (see
[labeling.md](labeling.md)) from the same candidates files the corpus was imported
from, and import it in "Zlatni primjeri". Prepare the corpus with `--gold-reserve`
(or import a supplement prepared with `--supplement` into the existing corpus) so that
the builder also has decoy items for the known answers that differ from the
suggestion; `gold` prints the coverage against the readiness targets and exits 3 when
a `pair` or `lemma` pool would be short, and `gold-check` checks files before an
import. The import skips calibration-sample items (reported as `held_out`), fills each
kind's qualification pool up to 60 and puts the rest in the audit pool; a row that
conflicts with an existing valid answer fails the whole import with 409
`gold_conflict`. For a top-up, build the next file with `--with` the files already
imported (their items are never reused) and a new seed.

Gold-reserve items are served only as known-answer checks: never in the normal queue,
the expert queues or the V1 order, not counted in progress, and never released. The
import marks them in `label_item_state.reserve` (migration 005).

Every `stem` known answer, and known answers that differ from the suggestion beyond
the gold-reserve decoys, come only from anchors. The owner is the only anchor today, and their answers on seed,
reference and review items are final. With "Rad za urednike" on (the default),
the owner's `/next` serves, in order: `needs_expert` items; the seed queue while a
pool is below its target (for `pair` and `lemma`, items where the crowd disagrees
with the suggestion first, shown without the suggestion; for `stem`, sampled stem
items), each answer becoming a known answer at the next run; calibration items still
waiting for a reference; review-sample items resolved without an anchor vote, oldest
first; then normal work. Switching it off gives the owner the normal queue. Expect
about 365 answers (2 to 2.5 hours) for the first round; later the review sample asks
about 20 answers per 1,000 further resolved items. If the owner's time runs out,
nothing breaks: the affected kind stays without promotion or its cells stay
`provisional`, and the dashboard shows what is missing.

### Quarantine review

Two different hard flags in one run quarantine an active, non-anchor annotator
automatically. The person is not told: their status shows as active, they keep
labeling, and their votes stop counting. Their self-service export shows the
quarantine with its flags. "Karantena" lists open quarantines with their age, the
flags with their signal values and the known-answer counts by type; the dashboard
alerts at 7 days. Decide within 14 days: release (the flags
start again from zero), keep (a human decision from then on) or block (the person
sees the reason). Without a decision, the first run after 14 days releases the
quarantine. Anchors are never quarantined automatically, and nothing is blocked
automatically. An objection by email is handled as a block with reason `objection`,
and erasure is offered.

### Restricted exports and downloads

From the latest done run, or `?run_id=` within the 30-day retention:
`resolved.tsv` (schema version 2: one row per item with its state, resolution
source, cell, answer, confidence, classes and counts), `resolved.jsonl` (the same
plus per-vote rows with pseudonymous ids; this is the run export a release is built
from, "Izračun za izdanje (JSONL)"), the annotators export (score rows and status,
no email) and the run bundle (journal rows up to the watermark, including answer
timing; never the secret key).

Every one of these files holds pseudonymous data. Keep downloads on the curator's
machine only, delete them within 30 days, and delete them at once when an erasure is
completed for a pseudonym they contain. Share a bundle with a third party only under
a written data-sharing agreement, for at most one year, and tell the recipient to
delete an erased person's rows.

### IT service providers

Development, debugging, operations and support may use IT service providers,
including AI-assisted development and operations tools, as processors under the
conditions of the DPIA (section 2.4): before first use, check that the provider's
data processing terms limit it to these purposes and the owner's instructions,
exclude training its models on the data, and give a transfer mechanism (an adequacy
decision, such as the EU-U.S. Data Privacy Framework where the provider is certified,
or the standard contractual clauses); record the provider, its terms and the
mechanism on the owner's list of providers. In use, give a tool only what the task
needs: code, configuration, aggregates or synthetic data first, then pseudonymous
rows from narrow queries; no database dumps or bundles, and no emails or names unless
the task cannot be done without them. Such tools never decide on a participant's
status, weight or block.

### Releases

Public releases are built offline from a pinned, non-stale run with
`croatian-stemmer-labels release` and `release-check` ([labeling.md](labeling.md)
has the procedure) and published only as GitHub release assets of
github.com/brahle/croatian-stemmer. They are never rewritten and contain no
annotator ids, counts or timestamps other than the release date.

### Retention

A retention task runs at startup and daily, independently of scoring, so data
expire even without runs and right after a restore. It deletes score and item
posterior rows 30 days after their run finished (pinned runs included; the latest
done run is kept while it is the latest), sets `elapsed_ms` to NULL 90 days after
the answer, and deletes unanswered showings 30 days after they were last shown. Run
rows, which hold no personal data, are kept. The daily task for never-consented
profiles is unchanged.

### Metrics

The app never serves `/metrics` on its own port (8000). With
`LABELING_METRICS_PORT` set, for example to `9464`, the process opens a second
plain-HTTP listener on that port that answers only `GET /metrics` (Prometheus
text format 0.0.4) and 404 for anything else. A separate port is used rather than
a path on the app's port: the ingress routes the public hostname to the app's
service port only, so the metrics are unreachable from outside as long as the
second port is not added to the ingress, and nothing depends on forwarded headers
being set or stripped correctly. Declare the port on the container and scrape it
from inside the cluster (a pod or service monitor that targets that port); do not
add it to the ingress. The values are aggregates; no annotator id, email, item or
corpus appears.

| metric | type | meaning |
|---|---|---|
| `labeling_scoring_enabled` | gauge | 1 when the curator has switched scoring on |
| `labeling_scoring_runs_total{outcome}` | counter | runs since the process started: `success`, `superseded`, `failed`, `timed_out`, and `skipped` (a scheduled tick that did not run: scoring off, nothing changed, or another run holding the lock) |
| `labeling_scoring_runs_in_progress` | gauge | runs in status `running`; a row a crashed process left behind counts too |
| `labeling_scoring_last_run_finish_timestamp_seconds{status}` | gauge | when the latest finished run finished, with its status (`done`, `superseded`, `failed`) |
| `labeling_scoring_last_success_timestamp_seconds` | gauge | when the latest `done` run finished; absent before the first |
| `labeling_scoring_seconds_since_last_success` | gauge | only while scoring is on: seconds since the later of the latest `done` run and the last write of the scoring switch (so switching scoring on does not page at once) |
| `labeling_job_last_success_timestamp_seconds{job}` | gauge | when a background job last completed without an error: `retention`, `unconsented_expiry`, `erasure_reminder`, `scoring`; absent until the job's first pass after a start (each runs at startup) |
| `labeling_job_failures_total{job}` | counter | background job passes that raised |
| `labeling_erasure_requests_pending` | gauge | erasure requests whose Keycloak deletion is not yet recorded |
| `labeling_erasure_request_oldest_pending_age_seconds` | gauge | age of the oldest of them (0 when none); the privacy notice promises completion within 30 days |
| `labeling_annotators_quarantined` | gauge | people currently set aside |
| `labeling_metrics_database_up` | gauge | 1 when the scrape could read the database (the database gauges are absent otherwise) |
| `labeling_build_info{version}`, `labeling_process_start_time_seconds` | gauge | the release and the process start |

Counters and job timestamps live in the process and restart from zero with it.

### Erasure and restore

When an erasure request appears in the panel, add its Keycloak user id and request
date to the erasure list kept outside the database, and delete each entry after 60 days
(backup retention plus margin). Complete the Keycloak deletion within 30 days as
before, and delete local downloads that contain the pseudonym.

If a backup is restored:

1. Pause intake and switch scoring off before the app serves again.
2. For every entry on the erasure list requested after the backup was taken, erase
   that profile again: `POST /api/admin/erasures/reapply` with
   `{"keycloak_user_ids": [...]}` (curator). It erases each restored profile exactly
   as the person's own erasure did and skips ids that are unknown or already erased.
3. The re-applied erasures appear as pending requests. Their Keycloak users were
   usually deleted already; check in the Keycloak admin console, delete any that
   remain, and confirm each request.
4. Switch scoring and intake back on. The retention task has already applied its
   rules at startup.

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
- Migration 003 (0.3.0) is forward-only too. It adds the journal sequence and
  its triggers, the trust tables and nullable columns, replaces the append-only
  functions (adding the 90-day timing retention and the erasure redaction),
  stores the default parameters, `scoring_enabled = false` and a random
  `audit_key`, and backfills an item state and the calibration and review sample
  bits for every existing item. It writes no known-answer items, trusted list or
  runs, so deploying it scores nobody. It waits at most 5 seconds for table locks;
  on a timeout the init container exits non-zero and the pod retries. Take a
  manual CNPG backup immediately before deploying it.
- Migration 004 (0.3.1) changes no schema. 0.3.1 has two new defaults: the `new`
  tier's ceiling 0.75 to 0.78 (two agreeing votes of an established and a new
  annotator can resolve an item) and `resolve_vote_min_theta` 0.70 (only votes for
  the answer from people with θ of at least 0.70 count as the two votes). Stored
  parameters that still equal the 0.3.0 defaults, never changed by a person, become
  the 0.3.1 defaults; any other stored parameters only gain
  `resolve_vote_min_theta` = 0.70 (0.3.1 refuses a set without it) and keep every
  chosen value. Each change appends the same `params.changed` event the dashboard
  does. Its downgrade puts the 0.3.0 defaults back when the stored value is still
  this migration's, and otherwise removes only the new key, which 0.3.0 refuses;
  run `python -m alembic downgrade 003_trust` with the 0.3.1 image before rolling
  back to 0.3.0, whose init container does not know revision 004.
- Migration 005 (0.3.4) adds `label_item_state.reserve` (boolean, default false,
  no table rewrite) and marks the gold-reserve items already imported. The import
  sets it for new items; the queues skip such items. Its downgrade drops the
  column: run `python -m alembic downgrade 004_two_vote_params` with the 0.3.4
  image before rolling back to 0.3.3, which would then serve any imported reserve
  item (a decoy shows a wrong suggestion) as ordinary work.
- One replica. Rate limits are in process and migrations run per pod. The
  scoring and retention tasks also run in the app process; a scoring run uses a
  worker thread and holds about 400 bytes per judgment in memory (see
  `LABELING_SCORING_MAX_JUDGMENTS`).
- Probes: `/healthz` for liveness and `/readyz` for readiness, on port 8000.
- The container runs as a non-root user with a read-only root filesystem. It
  needs outbound HTTPS to the issuer for JWKS and inbound HTTP on 8000 from your
  TLS-terminating proxy.
- Back up the database. The judgment journal is the only copy of human answers.

Roll back the application image first. From 0.2.3 a rollback is the previous
image plus a restore of the pre-deploy backup; `alembic downgrade` refuses to
undo 002a and 003. For 0.3.0: set the image tag back to the previous version,
then restore the backup taken before 003, in that order, accepting the loss of
anything written since the deploy; then follow "Erasure and restore" above. An
older image started against the 003 schema fails at its init container with
Alembic's unknown-revision error and never serves. Downgrading 002 recreates the
0.1 tables empty and is only for a database with nothing worth keeping. Scoring
can be stopped without any deploy by switching `scoring_enabled` off.
