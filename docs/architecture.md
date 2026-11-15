# Architecture

How the toolkit is put together, and the decisions that let it run on one laptop today and as a hosted SaaS later without a rewrite.

## The pieces

```
Browser ──► Next.js app (web/)  ──/api──►  FastAPI (src/seo_toolkit/api)
                                                │
                                     ┌──────────┴──────────┐
                                RunManager             Tool registry
                              (core/runs.py)          (tools/base.py)
                                     │                       │
                                 Postgres              Tools (tools/<group>/)
                             runs, workspaces                │
                                                   Connectors (connectors/)
                                                  Gemini, autocomplete, …
```

- **Tools** do the SEO work: inputs in, table out. They know nothing about the web, the database or who is signed in, so they run the same from the API, the CLI (`seo run`) or a notebook (`run_tool`).
- **Connectors** are the only code that calls outside services.
- **RunManager** runs tools in the background, records progress and results, and scopes everything to a workspace.
- **The API** is a thin layer over the tool registry, RunManager and setup checks.
- **The web app** builds every tool's form from its input JSON Schema, so a new Python tool needs no front-end code.

## Stack

| Layer | Now (local) | When hosted |
|---|---|---|
| Front end | Next.js, TypeScript, Tailwind, shadcn/ui, TanStack Query and Table, ECharts | Same, on Vercel |
| API types | Generated from FastAPI's OpenAPI schema (openapi-typescript) | Same |
| Back end | Python, FastAPI, Pydantic | Same, on Render or Railway |
| Database | Postgres 17 (Homebrew), SQLAlchemy 2, Alembic | Neon (managed Postgres, pgvector) |
| Background runs | Thread pool inside the API process | Postgres-backed job queue (Procrastinate) with separate workers |
| Results files | `data/outputs/` | Cloudflare R2 / S3 |
| API cache | `.cache/` on disk | Postgres or Redis |
| Accounts | One local workspace | Clerk (organisations); WorkOS if enterprise SSO is needed |
| Billing | — | Stripe, usage-based (runs already record tokens and searches) |
| Monitoring | Server log | Sentry, PostHog |

## Decisions that keep the SaaS path open

1. **Every user-data table has `workspace_id`.** Locally it's `"local"`. A hosted version takes it from the signed-in user's organisation. Queries always filter by it (see `RunManager`).
2. **The same database everywhere.** Postgres locally and in production, so there's one set of behaviour to test. The tests create a throwaway database per session.
3. **Anything that changes when hosted sits behind one small interface:** job running (`RunManager`), file storage, cache (`core/cache.py`), and secrets (`.env` now, encrypted per-workspace keys later).
4. **Tools stay pure.** No database, web or auth code inside a tool.
5. **Progress lives in the database,** not in memory, so a separate worker process can report it later without the web app changing.

Known limitation while there's one process: when the API starts, it marks any queued or running runs as interrupted. With separate workers this becomes a heartbeat check.

## Database changes

Tables are defined in `src/seo_toolkit/core/db.py`. Every change goes through a migration in `src/seo_toolkit/migrations/versions/`:

```bash
# 1. Change the table classes in core/db.py
# 2. Generate a migration from the difference, then read and adjust it
uv run alembic revision --autogenerate -m "add sites table"
# 3. Apply it
uv run seo db setup
```

The tests apply every migration to their throwaway database, so a broken migration fails the tests.

## Running locally

```bash
brew install postgresql@17 pgvector && brew services start postgresql@17   # once
uv sync
uv run seo db setup      # creates the database and tables; safe to repeat
uv run seo api           # http://localhost:8000/api/docs
```

Everything listens on localhost only: the API can spend your Gemini quota.
