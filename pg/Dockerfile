ARG PG_MAJOR=17
FROM postgres:${PG_MAJOR}

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
