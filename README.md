# python-seo-scripts

Semantic SEO research and planning tools you run on your own computer, from a local dashboard or the command line.

The tools follow the principles in [docs/semantic-seo-principles.md](docs/semantic-seo-principles.md): how Google reads, groups and ranks content, and how the semantic SEO framework turns that into plans. How the code fits together, and the stack, are in [docs/architecture.md](docs/architecture.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/), Postgres and Node.js:

```bash
brew install uv postgresql@17 pgvector node
brew services start postgresql@17   # runs in the background from now on
```

Then:

```bash
uv sync                      # install everything
cp .env.example .env         # then add your keys (all optional to start)
uv run seo db setup          # create the database and its tables (safe to repeat)
uv run seo dev               # start the app: http://localhost:3000
```

`seo dev` starts the API and the web app together (the first run also installs the web app's packages); Ctrl+C stops both. Both only accept connections from your own computer.

`uv run seo app` does the same.

**Setting up your site:** open **Sites → New site** in the web app and fill in the domain, source context, central entity, sections, brand terms and competitors. The new site is selected straight away. Sites are stored in the database; **Export YAML** on a site's page saves a copy, and any YAML files in `config/sites/` are imported by `uv run seo db setup` (your own site files there are gitignored, like `.env`).

## The web app

| Page | What it's for |
|---|---|
| **Overview** | Your site's semantic context, which tools are ready, recent runs, and anything in Setup that needs attention |
| **One page per tool** | A form built from the tool's inputs, a "How it works" explanation, live progress, and the results: sortable, filterable, resizable, downloadable as CSV or Excel |
| **Content editor** | Write a page in a full editor with a live score beside it: the words the top-ranking pages use (and how often), the questions to answer, a checklist for the title, headings and answers, and **Check my answers** (Gemini says what's missing and where to add it). Drafts save as you type; **Copy** pastes with formatting into Google Docs or WordPress |
| **Runs** | Every run, filterable by tool, status and site |
| **Sites** | Create, edit, export and delete sites |
| **Setup** | What's configured, what each key unlocks, and a live test of each API |

Runs happen in the background, so you can leave the page and come back; the run's address (`?run=…`) always shows it again. Every run is saved to `data/outputs/<tool>/` and recorded in the database. API responses are cached in `.cache/`, so a rerun is instant and free; tick **Ignore cache** to fetch fresh data. Pick the site to run against in the sidebar.

## The command line

```bash
uv run seo doctor                    # check settings and keys
uv run seo doctor --live             # also make one small real call to each API
uv run seo tools                     # list tools and whether they're ready
uv run seo run research/autocomplete seeds="pool cost" seeds="pool size"
```

## Keys

| Key | Unlocks |
|---|---|
| `GEMINI_API_KEY` | Related searches, Keyword planner, Content editor ([get a key](https://aistudio.google.com/apikey)) |
| `GOOGLE_API_KEY` | Knowledge Graph, PageSpeed, Natural Language |
| `GOOGLE_APPLICATION_CREDENTIALS` | Search Console and GA4, via a service-account JSON in `credentials/` |
| `DATAFORSEO_*` / `SERPAPI_API_KEY` | SERP data and search volumes (paid, optional) |

The Autocomplete tool needs no key at all.

## Adding a tool

Create `src/seo_toolkit/tools/<group>/<name>.py` with a class that subclasses `Tool`:
- `name`, `group`, `title` and `summary`
- `needs`: the settings it requires
- an `Inputs` pydantic model
- a `run()` method that returns a `ToolResult`
- optionally `page`: a screen of its own in the web app (like the content editor's `/editor`) instead of the generated form

The module docstring becomes the tool's "How it works" text. The tool then appears in the dashboard, `seo tools` and `seo run` with no other changes. [tools/research/autocomplete.py](src/seo_toolkit/tools/research/autocomplete.py) is the reference example.

## Development

```bash
uv run pytest                 # tests: no API calls or keys; needs Postgres running (uses a throwaway database)
uv run ruff check src tests   # lint
uv run mypy src               # types

cd web
corepack pnpm test            # front-end unit tests
corepack pnpm typecheck       # TypeScript
corepack pnpm e2e             # browser tests in your installed Chrome (own database and ports)
corepack pnpm gen:api         # regenerate the API types after changing the Python API
```

A Python test fails if the API changed without `gen:api`, so the front end's types can't drift from the API.
