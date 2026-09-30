#!/bin/sh
set -eu

# This script runs only when PostgreSQL creates a new data volume.  The app
# connects as synthetic_writer; its chat connection uses synthetic_reader.
: "${APP_DB_PASSWORD:=change-me-before-starting}"
: "${ANALYTICS_DB_PASSWORD:=change-me-before-starting}"
: "${APP_DB_USER:=synthetic_writer}"
: "${ANALYTICS_DB_USER:=synthetic_reader}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v database_name="$POSTGRES_DB" \
  -v writer_user="$APP_DB_USER" \
  -v reader_user="$ANALYTICS_DB_USER" \
  -v writer_password="$APP_DB_PASSWORD" \
  -v reader_password="$ANALYTICS_DB_PASSWORD" <<'SQL'
CREATE ROLE :"writer_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'writer_password';
CREATE ROLE :"reader_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'reader_password';
REVOKE CREATE ON DATABASE :"database_name" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT, CREATE ON DATABASE :"database_name" TO :"writer_user";
GRANT CONNECT ON DATABASE :"database_name" TO :"reader_user";
SQL
