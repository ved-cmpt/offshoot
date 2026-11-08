# Production image (ADR-007, ADR-047): the orchestrator API and the built Angular app on one
# origin, in one process, sized for a 512 MB free web service. It holds no COBOL compiler, no
# .NET SDK and no facade, so it cannot compile or run code of any kind: EXECUTION_ENABLED is
# false and the module screens show stored runs of the real sandbox instead.
#
#   docker build -t offshoot .
#   docker compose -f compose.prod.yaml up --build -d     (local, with its own Postgres)

FROM node:26.13.0-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS web
ENV NG_CLI_ANALYTICS=false
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build --configuration production

FROM python:3.12.16-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    APP_ENV=production \
    DEMO_MODE=true \
    AI_MODE=mock \
    EXECUTION_ENABLED=false \
    JOB_WORKER_ENABLED=true \
    STATIC_DIR=/app/static \
    BILLRITE_PATH=/legacy/billrite \
    PORT=8080

RUN pip install --no-cache-dir --root-user-action=ignore uv==0.13.7
WORKDIR /app
COPY orchestrator/pyproject.toml orchestrator/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --no-cache \
    && pip uninstall -y --root-user-action=ignore uv \
    && groupadd --gid 10000 app \
    && useradd --uid 10000 --gid 10000 --no-create-home --shell /usr/sbin/nologin app

COPY orchestrator/alembic.ini ./
COPY orchestrator/alembic ./alembic
COPY orchestrator/app ./app
# The bundled sources, read by the seed. The answer key in docs/ is never copied (ADR-025).
COPY legacy/billrite/src /legacy/billrite/src
COPY legacy/billrite/copy /legacy/billrite/copy
COPY legacy/billrite/data/LAYOUTS.txt /legacy/billrite/data/LAYOUTS.txt
COPY --from=web /web/dist/frontend/browser /app/static

USER 10000:10000
EXPOSE 8080
# One process: the API, the static app and the job worker thread (ADR-023, ADR-047).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT}\" --no-server-header --no-proxy-headers --timeout-keep-alive 30"]
