#!/usr/bin/env bash
# KDPS dev bootstrap for the Emergent container (Phase 0).
# Idempotent: safe to re-run. Brings up Postgres, deps, DB, migrations, seed.
set -euo pipefail

VENV=/root/.venv
BACKEND=/app/app/backend

echo "==> 1. PostgreSQL 15"
if ! command -v pg_lsclusters >/dev/null 2>&1; then
  apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib
fi
# Start via supervisor if configured, else directly.
if [ -f /etc/supervisor/conf.d/postgresql.conf ]; then
  supervisorctl reread >/dev/null 2>&1 || true
  supervisorctl update >/dev/null 2>&1 || true
  supervisorctl start postgresql >/dev/null 2>&1 || true
fi
pg_ctlcluster 15 main start 2>/dev/null || true
sleep 2

echo "==> 2. Role + database (kdps / kdps_dev)"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='kdps'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE kdps LOGIN SUPERUSER PASSWORD 'kdps';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='kdps_dev'" | grep -q 1 \
  || sudo -u postgres createdb -O kdps kdps_dev

echo "==> 3. Backend deps into served venv"
$VENV/bin/python -c "import django" 2>/dev/null || $VENV/bin/pip install \
  "django>=5.1,<5.2" "psycopg[binary]>=3.2" "dj-database-url>=2.3" \
  "djangorestframework>=3.15" "djangorestframework-simplejwt>=5.3" \
  "drf-spectacular>=0.27" "django-cors-headers>=4.4" "python-dotenv>=1.0" \
  "requests>=2.32" "openpyxl>=3.1" "xlrd>=2.0" "pyxlsb>=1.0" "whitenoise>=6.6"

echo "==> 4. Migrate + seed"
cd "$BACKEND"
$VENV/bin/python manage.py migrate --noinput
$VENV/bin/python manage.py seed_foundation
$VENV/bin/python manage.py seed_ptmapper || true

echo "==> 5. Restart backend"
supervisorctl restart backend >/dev/null 2>&1 || true
sleep 5
curl -s -m 8 -o /dev/null -w "login -> %{http_code}\n" -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"owner","password":"Owner@123"}'
echo "==> done."
