# P2Pool Merged Mining (V36) — Litecoin + Dogecoin
# https://github.com/frstrtr/p2pool-merged-v36
#
# Build:  docker build -t p2pool-ltc .
# Run:    docker run -p 9327:9327 -p 9326:9326 p2pool-ltc --help
#
# For full merged mining with MM-Adapter, use docker-compose.yml instead.

FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYPY_VERSION=7.3.17
ENV PYPY_DIR=/opt/pypy2.7-v${PYPY_VERSION}-linux64

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget ca-certificates build-essential libssl-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# PyPy 2.7
RUN cd /tmp && \
    wget -q https://downloads.python.org/pypy/pypy2.7-v${PYPY_VERSION}-linux64.tar.bz2 && \
    tar xjf pypy2.7-v${PYPY_VERSION}-linux64.tar.bz2 -C /opt && \
    ln -s ${PYPY_DIR}/bin/pypy /usr/local/bin/pypy && \
    rm /tmp/pypy2.7-v${PYPY_VERSION}-linux64.tar.bz2

# pip + Python dependencies (pin incremental first — required for twisted on Python 2.7)
RUN cd /tmp && \
    wget -q https://bootstrap.pypa.io/pip/2.7/get-pip.py && \
    pypy get-pip.py && \
    rm get-pip.py && \
    pypy -m pip install --no-cache-dir 'incremental<22' && \
    pypy -m pip install --no-cache-dir \
        twisted==20.3.0 \
        pycryptodome \
        'scrypt>=0.8.0,<=0.8.22' \
        ecdsa

# Verify scrypt works
RUN pypy -c "import scrypt; print('scrypt OK')"

# ── Application ──────────────────────────────────────────────────────────
FROM base AS app

WORKDIR /app
COPY . /app

# Verify ltc_scrypt wrapper loads via pip scrypt
RUN pypy -c "import ltc_scrypt; print('ltc_scrypt OK')"

# Data directory (shares, peer db, block history)
VOLUME /app/data

# Stratum/Web (9327) + P2Pool P2P (9326)
EXPOSE 9327 9326

# Health check: hit the local_stats API
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD pypy -c "import urllib2; urllib2.urlopen('http://localhost:9327/local_stats').read()" || exit 1

ENTRYPOINT ["pypy", "run_p2pool.py"]
CMD ["--net", "litecoin", "--help"]
