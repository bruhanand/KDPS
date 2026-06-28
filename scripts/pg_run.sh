#!/bin/bash
# KDPS Postgres bootstrap — supervisor-managed, idempotent, self-healing.
# Binaries/users are ephemeral in this container; only /app persists, so the
# data directory lives at /app/.pgdata and we (re)install the server if missing.
set -e
PGBIN=/usr/lib/postgresql/15/bin
export PATH="$PGBIN:$PATH"
DATA=/app/.pgdata

# 1) ensure the server is installed (it is wiped on container recycle)
if [ ! -x "$PGBIN/postgres" ] || ! id postgres >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y postgresql postgresql-contrib
fi

# 2) ensure a persistent, initialised data directory
if [ ! -f "$DATA/PG_VERSION" ]; then
  mkdir -p "$DATA"
  chown -R postgres:postgres "$DATA"
  chmod 700 "$DATA"
  su postgres -c "$PGBIN/initdb -D $DATA -U kdps --auth=trust --auth-host=trust --auth-local=trust"
  {
    echo "listen_addresses='localhost'"
    echo "unix_socket_directories='/tmp'"
    echo "port=5432"
  } >> "$DATA/postgresql.conf"
fi
chown -R postgres:postgres "$DATA"

# 3) ensure the application database exists (brief temp start)
su postgres -c "$PGBIN/pg_ctl -D $DATA -o '-k /tmp' -w -t 60 start"
su postgres -c "$PGBIN/psql -h /tmp -U kdps -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='kdps_dev'\" | grep -q 1 || $PGBIN/createdb -h /tmp -U kdps kdps_dev"
su postgres -c "$PGBIN/pg_ctl -D $DATA -w stop"

# 4) run in the foreground for supervisor
exec su postgres -c "$PGBIN/postgres -D $DATA -k /tmp"
