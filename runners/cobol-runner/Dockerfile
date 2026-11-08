FROM debian:13.7-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gnucobol3=3.2-3 \
        make=4.4.1-2 \
        python3=3.13.5-1 \
        libseccomp-dev=2.6.0-2 \
    && rm -rf /var/lib/apt/lists/*

COPY runners/common/nonet.c /tmp/nonet.c
RUN gcc -O2 -Wall -Wextra -Werror -static -o /usr/local/bin/nonet /tmp/nonet.c -lseccomp \
    && rm /tmp/nonet.c \
    && apt-get purge -y libseccomp-dev \
    && apt-get autoremove -y --purge

COPY runners/common/runner_auth.py runners/cobol-runner/server.py /opt/runner/

RUN groupadd --gid 10001 runner \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin runner \
    && install -d -o 10001 -g 10001 /work /out

USER 10001:10001
ENV HOME=/tmp
WORKDIR /app/billrite
CMD ["python3", "/opt/runner/server.py"]
