#!/bin/bash
# KDPS app init — waits for Postgres, applies migrations, seeds demo data if the
# DB is empty. Runs once per container boot (supervisor oneshot).
PGBIN=/usr/lib/postgresql/15/bin
PY=/root/.venv/bin/python
cd /app/app/backend || exit 0

for _ in $(seq 1 90); do
  if "$PGBIN/pg_isready" -h localhost -p 5432 -U kdps >/dev/null 2>&1; then break; fi
  sleep 1
done

"$PY" manage.py migrate --noinput

COUNT=$("$PY" manage.py shell -c "from accounts.models import User; print(User.objects.count())" 2>/dev/null | tail -1)
if [ "$COUNT" = "0" ] || [ -z "$COUNT" ]; then
  "$PY" manage.py seed_foundation
fi
echo "app_init done (users=$COUNT)"
