#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${LABELING_TEST_DATABASE_URL:?Set an isolated, migrated PostgreSQL *_test database URL}"
export LABELING_DATABASE_URL=$LABELING_TEST_DATABASE_URL
export LABELING_OIDC_ISSUER=http://127.0.0.1:55485/realms/test
export LABELING_ALLOW_LOCAL_HTTP=true
# Deployment-like identity: any realm human may label, curators come from groups.
export LABELING_ANNOTATOR_POLICY=open LABELING_OIDC_ROLE_SOURCE=groups LABELING_OIDC_IDP_HINT=google
# Synthetic compliance values (the legal notices refuse to start without them).
export LABELING_CONTROLLER_NAME='Synthetic Test Controller' LABELING_CONTROLLER_EMAIL=privacy@example.org
export LABELING_HOSTING_SUMMARY='Example Hosting Ltd, Germany (synthetic)'
export LABELING_EDGE_LOG_RETENTION='7 days (synthetic)' LABELING_BACKUP_RETENTION='14 days (synthetic)'
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic check
.venv/bin/python -m pytest
npm ci --ignore-scripts
npm run build
.venv/bin/python -m uvicorn croatian_stemmer.labeling.web.serve:app --host 127.0.0.1 --port 55484 --no-access-log > "${TMPDIR:-/tmp}/labeling-test-app.log" 2>&1 &
app_pid=$!
PYTHONPATH=tests/web .venv/bin/python -m uvicorn oidc_fixture:app --host 127.0.0.1 --port 55485 --no-access-log > "${TMPDIR:-/tmp}/labeling-test-oidc.log" 2>&1 &
oidc_pid=$!
trap 'kill "$app_pid" "$oidc_pid" 2>/dev/null || true; wait "$app_pid" "$oidc_pid" 2>/dev/null || true' EXIT
.venv/bin/python - <<'PY'
import time, urllib.request
for url in ('http://127.0.0.1:55484/readyz','http://127.0.0.1:55485/realms/test/protocol/openid-connect/certs'):
    for attempt in range(50):
        try:
            with urllib.request.urlopen(url,timeout=1):
                break
        except OSError:
            time.sleep(.1)
    else:
        raise SystemExit('Test server did not start')
PY
npx playwright test
