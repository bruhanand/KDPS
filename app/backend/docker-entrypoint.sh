#!/bin/sh
set -eu

# RDS generates a password that can contain URL-reserved characters.  Keep the
# generated value in ECS Secrets Manager and encode it only inside the task.
encoded_password="$(python -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["DATABASE_PASSWORD"], safe=""))')"
export DATABASE_URL="postgresql://${DATABASE_USER}:${encoded_password}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}?sslmode=require"

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed_foundation
python manage.py seed_ptmapper
python manage.py seed_outbound_demo

exec uvicorn server:app --host 0.0.0.0 --port 8000
