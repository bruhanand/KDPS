# The KDPS API as a container.
#
# Deliberately the same shape Render runs the alpha in (`uvicorn server:app`,
# uv-managed deps from the committed lock) so "works in Docker" and "works on
# the alpha" mean the same thing — this is a local mirror of the deploy, not a
# second way of running the app.
#
#   docker compose up -d db api      # http://localhost:8001
#
# Postgres is NOT in this image: the kernel's guarantees are database triggers,
# so the API always talks to the real Postgres 16 service in docker-compose.yml
# (ADR-0005), never to something bundled and throwaway.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Copy rather than hardlink: the build cache and the layer live on
    # different filesystems, which uv warns about on every sync otherwise.
    UV_LINK_MODE=copy \
    # Keep the venv outside the workdir so `COPY . .` below cannot clobber it.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# curl is the healthcheck's only need; build-essential covers any source-only
# wheel in the lock (psycopg ships binaries, but the AI-gateway client does not).
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --no-cache-dir uv

WORKDIR /srv/app

# Dependencies first and on their own layer: editing a view must not re-resolve
# the whole lock. `--frozen` means the lock is the truth, exactly as on Render.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
