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
    DOTNET_CLI_USE_MSBUILD_SERVER=0 \
    STRYKER_PATH=/opt/stryker/dotnet-stryker

# The runner API is standard-library Python, like the cobol-runner's.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3=3.12.3-0ubuntu2.1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=nonet /nonet /usr/local/bin/nonet
COPY runners/dotnet-builder/build-and-test /usr/local/bin/build-and-test

# Everything is restored and installed while the image builds, so that nothing at run time
# needs the network, which the container does not have (ADR-016, ADR-030): the modern
# solution, the sandbox template with its analyzers and test packages, and Stryker.NET.
COPY modern/ /tmp/restore/
COPY runners/dotnet-builder/template/ /opt/template/
RUN chmod 0755 /usr/local/bin/build-and-test \
    && dotnet restore /tmp/restore/ParityForge.Modern.sln --locked-mode \
    && dotnet restore /opt/template/ParityForge.Sandbox.slnx --locked-mode \
    && dotnet restore /opt/template/Equivalence/ParityForge.Equivalence.Tests.csproj --locked-mode \
    && dotnet tool install dotnet-stryker --version 4.16.0 --tool-path /opt/stryker \
    && find /opt/template -type d \( -name obj -o -name bin \) -prune -exec rm -rf {} + \
    && rm -rf /tmp/restore /tmp/dotnet-home /tmp/nuget-http /tmp/nuget-scratch \
    && chmod -R a+rX /opt/nuget /opt/template /opt/stryker \
    && groupadd --gid 10001 runner \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin runner \
    && install -d -o 10001 -g 10001 /work /run/builder

COPY runners/common/runner_auth.py runners/dotnet-builder/server.py /opt/runner/

USER 10001:10001
WORKDIR /work
CMD ["python3", "/opt/runner/server.py"]
