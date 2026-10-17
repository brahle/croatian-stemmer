#!/bin/bash
# Build and test the PG extension against multiple PostgreSQL versions.
# Usage: ./docker-test.sh [pg_version...]
# Default: tests against PG 15, 16, 17, 18

set -euo pipefail

VERSIONS="${@:-15 16 17 18}"
PASS=0
FAIL=0

for PG_MAJOR in $VERSIONS; do
    echo "=========================================="
    echo "  Testing with PostgreSQL ${PG_MAJOR}"
    echo "=========================================="

    IMAGE="croatian-stemmer-test:pg${PG_MAJOR}"

    # Build
    if ! docker build --build-arg PG_MAJOR="${PG_MAJOR}" -t "${IMAGE}" -f Dockerfile .; then
        echo "FAIL: Build failed for PG ${PG_MAJOR}"
        FAIL=$((FAIL + 1))
        continue
    fi

    # Run regression tests. The official postgres image doesn't auto-create
    # a cluster, so we provision one (createuser/createdb under the postgres
    # account), start it, then run installcheck against it.
    if docker run --rm "${IMAGE}" bash -c '
        set -e
        chown -R postgres:postgres /build
        pg_createcluster '"${PG_MAJOR}"' main >/dev/null
        pg_ctlcluster '"${PG_MAJOR}"' main start
        su - postgres -c "make -C /build USE_PGXS=1 installcheck" 2>&1 \
            || { cat /build/regression.diffs; exit 1; }
    '; then
        echo "PASS: PG ${PG_MAJOR}"
        PASS=$((PASS + 1))
    else
        echo "FAIL: Regression tests failed for PG ${PG_MAJOR}"
        FAIL=$((FAIL + 1))
    fi

    # Cleanup
    docker rmi "${IMAGE}" >/dev/null 2>&1 || true
done

echo ""
echo "=========================================="
echo "  Results: ${PASS} passed, ${FAIL} failed"
echo "=========================================="

exit "${FAIL}"
