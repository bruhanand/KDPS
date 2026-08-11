# CI

Read this before touching CI config, the `mypy` scope, or any serializer, view, or URL.

## The gates

`npm run ci` is the **local acceptance gate**: ruff · mypy strict · migration check · schema-drift check · import-linter · pytest · API-client drift · tsc · vitest.
`docker-compose` gives a local Postgres, and pre-commit hooks run ruff/mypy.

**API-client drift (#192):** `npm run api:client` regenerates the PWA's typed client (`app/frontend/src/lib/api-schema.ts`) from the backend's own OpenAPI document.
It must run in the same commit as any serializer/view/URL change, and the file is generated - never hand-edit it.

## Cloud CI

`.github/workflows/ci.yml` triggers on **push only** - no `pull_request` (the push run already covers the PR head) and, deliberately, **no `paths-ignore` on the trigger**: a run a path filter suppresses reports no check at all, which is indistinguishable from a run GitHub silently dropped and makes the workflow useless as a required check (#301).
The workflow therefore always starts, and filtering happens per job.

Jobs: `changes` (which trees moved), `lint` (ruff format · ruff check · `mypy .` · import-linter), `backend-kernel` (kernel anti-cheat + migration-drift guards), `backend-suite` (**8 parallel shards** via `pytest-split`, each with its own Postgres + seed + uvicorn), `api-client` (regenerates the typed client and refuses a difference), `frontend` (build + tsc + vitest), and `ci` - an always-run job that aggregates the rest and is **the single required check on `main`**.
Typical full run ~4-5 min; a push touching neither tree finishes green in well under a minute.

Shard balance comes from `app/backend/.test_durations`.
Regenerate it when the suite's shape changes materially: `uv run pytest tests --store-durations`.

## The mypy scope and its traps

The `lint` job runs **`mypy .`** - the whole backend, not a list of apps (#292 closed the `core config` hole).
Keep that string identical in the four places it lives: `package.json` (`ci:backend`, `ci:backend:fast`), the workflow, and `.pre-commit-config.yaml`.

Two traps before you widen or narrow it:

- Django's `admin.ModelAdmin` is **not subscriptable at runtime**, so `class FooAdmin(ModelAdmin[Foo])` raises `TypeError` and crashes admin autodiscover at import. DRF's serializers and generic views, and Django's `Manager`, *are* subscriptable.
- `from __future__ import annotations` does not defer **base-class** expressions, only annotations, so a bad base class is an import-time crash rather than a type error.
