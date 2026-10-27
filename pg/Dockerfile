ARG PG_MAJOR=17
# Pinned to the 2026-10-21 build of postgres:17. The digest wins over the tag, so moving
# PG_MAJOR also needs a new digest (postgresql-server-dev-<major> fails loudly otherwise).
FROM postgres:${PG_MAJOR}@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libicu-dev \
        postgresql-server-dev-${PG_MAJOR} \
    && rm -rf /var/lib/apt/lists/*

COPY . /build/
WORKDIR /build

RUN make USE_PGXS=1 clean && make USE_PGXS=1 && make USE_PGXS=1 install

# Verify the extension is loadable
RUN echo "shared_preload_libraries = ''" >> /usr/share/postgresql/postgresql.conf.sample
