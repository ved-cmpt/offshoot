# The strangler facade (ADR-039). Built from the repository root:
#   docker build -f modern/src/Offshoot.Facade/Dockerfile .
FROM mcr.microsoft.com/dotnet/sdk:10.0.403@sha256:de4fe90a98845d75910b9769662465c84de1a934665c431279d1382b2bddc02b AS build
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
WORKDIR /src
COPY modern/ ./
RUN dotnet restore src/Offshoot.Facade/Offshoot.Facade.csproj --locked-mode \
    && dotnet publish src/Offshoot.Facade/Offshoot.Facade.csproj -c Release --no-restore -o /out

FROM mcr.microsoft.com/dotnet/aspnet:10.0.14@sha256:1a48394b6f29d3a32c79d9edecd4abda0ecbe8776d567dbfc4590ed6979c740c
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    ASPNETCORE_URLS= \
    DOTNET_gcServer=0
COPY --from=build /out /app
RUN groupadd --gid 10002 facade && useradd --uid 10002 --gid 10002 --no-create-home --shell /usr/sbin/nologin facade
USER 10002:10002
WORKDIR /app
EXPOSE 8080
CMD ["dotnet", "Offshoot.Facade.dll"]
