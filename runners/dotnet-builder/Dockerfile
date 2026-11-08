FROM debian:13.7-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4 AS nonet
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev libseccomp-dev=2.6.0-2
COPY runners/common/nonet.c /tmp/nonet.c
RUN gcc -O2 -Wall -Wextra -Werror -static -o /nonet /tmp/nonet.c -lseccomp

FROM mcr.microsoft.com/dotnet/sdk:10.0.403@sha256:de4fe90a98845d75910b9769662465c84de1a934665c431279d1382b2bddc02b
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_CLI_HOME=/tmp/dotnet-home \
    NUGET_PACKAGES=/opt/nuget/packages \
    NUGET_HTTP_CACHE_PATH=/tmp/nuget-http \
    NUGET_SCRATCH=/tmp/nuget-scratch \
    HOME=/tmp \
    MSBUILDDISABLENODEREUSE=1 \
    DOTNET_CLI_USE_MSBUILD_SERVER=0

COPY --from=nonet /nonet /usr/local/bin/nonet
COPY runners/dotnet-builder/build-and-test /usr/local/bin/build-and-test

# Restore while the image builds so that builds at run time never need the network.
COPY modern/ /tmp/restore/
RUN chmod 0755 /usr/local/bin/build-and-test \
    && dotnet restore /tmp/restore/ParityForge.Modern.sln --locked-mode \
    && rm -rf /tmp/restore /tmp/dotnet-home /tmp/nuget-http /tmp/nuget-scratch \
    && chmod -R a+rX /opt/nuget \
    && groupadd --gid 10001 runner \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin runner \
    && install -d -o 10001 -g 10001 /work

USER 10001:10001
WORKDIR /work
CMD ["tail", "-f", "/dev/null"]
