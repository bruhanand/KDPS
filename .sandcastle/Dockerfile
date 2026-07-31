FROM node:22-bookworm

# Install system dependencies.
#
# PostgreSQL 16 is not optional here. The kernel's guarantees — append-only
# ledgers, the docstatus FSM, gap-free voucher numbering — are enforced by
# database triggers, so `pytest` is only meaningful against real Postgres
# (ADR-0005). 16 matches docker-compose.yml, scripts/dev.sh and the Render alpha.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    ca-certificates \
    gnupg \
  && install -d /usr/share/postgresql-common/pgdg \
  && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
  && apt-get update && apt-get install -y --no-install-recommends postgresql-16 \
  && rm -rf /var/lib/apt/lists/* \
  && ln -s /usr/lib/postgresql/16/bin/* /usr/local/bin/

# Note: the symlinks above are load-bearing, not a convenience. Debian keeps the
# server binaries off PATH, and a login shell (`bash -lc`, which is how hook and
# agent commands arrive) re-sources /etc/profile and discards the image's
# ENV PATH — so pg_ctl must be somewhere the default PATH already looks.

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && apt-get update && apt-get install -y gh \
  && rm -rf /var/lib/apt/lists/*

# Headless Chromium + the Playwright MCP server, for the browser-QA phase.
# Debian's chromium rather than a Playwright download, so the browser and its
# system libraries stay in step on arm64; sandbox-setup.sh points the MCP
# server at it explicitly. The Noto fonts keep ₹ and Devanagari from rendering
# as tofu in screenshots.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium fonts-noto-core fonts-noto-ui-core \
  && rm -rf /var/lib/apt/lists/* \
  && npm install -g @playwright/mcp

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# Rename the base image's "node" user to "agent" and align UID/GID.
# The host GID/UID may already exist in the base image (macOS staff=20 collides
# with Debian's dialout), so reuse the existing group/free the existing user
# rather than failing the build.
RUN set -eux; \
  if ! getent group "$AGENT_GID" >/dev/null; then groupmod -g "$AGENT_GID" node; fi; \
  clash="$(getent passwd "$AGENT_UID" | cut -d: -f1 || true)"; \
  if [ -n "$clash" ] && [ "$clash" != node ]; then userdel "$clash"; fi; \
  usermod -u "$AGENT_UID" -g "$AGENT_GID" -d /home/agent -m -l agent node
USER ${AGENT_UID}:${AGENT_GID}

# Claude's CLI, uv's shims and the Postgres server binaries all live off PATH.
ENV PATH="/home/agent/.local/bin:/usr/lib/postgresql/16/bin:$PATH"
ENV PGDATA="/home/agent/pgdata"
# The server's socket lives in /tmp (see the cluster setup below) because `agent`
# cannot write Debian's default /var/run/postgresql. psql/createdb compile in that
# default, so point every local client at the real socket.
ENV PGHOST="/tmp"

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash

# uv, and the interpreter app/backend pins. bookworm ships Python 3.11 but
# pyproject.toml requires >=3.12, so uv manages its own.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
  && uv python install 3.12

# A Postgres cluster owned by `agent`, so the server starts in this rootless
# container without sudo. Trust auth and a /tmp socket dir are safe because the
# cluster is throwaway and reachable only from inside the sandbox.
# `.sandcastle/sandbox-setup.sh` starts it when the sandbox comes up.
RUN set -eux; \
  initdb --pgdata="$PGDATA" --username=kdps --auth-local=trust --auth-host=trust --encoding=UTF8; \
  echo "unix_socket_directories = '/tmp'" >> "$PGDATA/postgresql.conf"; \
  pg_ctl --pgdata="$PGDATA" --log=/tmp/initdb.log -w start; \
  createdb --username=kdps kdps_dev; \
  pg_ctl --pgdata="$PGDATA" -w stop

WORKDIR /home/agent

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
