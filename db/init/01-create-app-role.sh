#!/bin/sh
# Runs once, when the Postgres data volume is first initialized. Creates the
# least-privilege login the API uses. Grants are applied by the Alembic migration.
set -eu
psql -v ON_ERROR_STOP=1 -v app_role="$APP_DB_ROLE" -v app_password="$APP_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_role" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
SQL
