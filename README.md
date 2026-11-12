# python-seo-scripts

Semantic SEO research and planning tools you run on your own computer, from a local dashboard or the command line.

The tools follow the principles in [docs/semantic-seo-principles.md](docs/semantic-seo-principles.md): how Google reads, groups and ranks content, and how the semantic SEO framework turns that into plans.

## Quick start

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`). It installs the right Python version for you.

```bash
uv sync                      # install everything
cp .env.example .env         # then add your keys (all optional to start)
uv run seo app               # open the dashboard at http://localhost:8501
```

The dashboard only accepts connections from your own computer.

**Setting up your site:**
1. Copy `config/sites/example.yaml` to `config/sites/<your-site>.yaml`.
2. Fill it in: domain, source context, central entity, sections, brand terms, competitors.
3. Set `SEO_SITE=<your-site>` in `.env`, or pick the site in the dashboard's sidebar.

Your site files and `.env` are gitignored.

## The dashboard

| Page | What it's for |
|---|---|
| **Home** | Your site's semantic context, and which tools are ready to run |
| **Setup** | What's configured, what each key unlocks, and a live test of each API |
| **Results** | Every saved run, to view or download |
| **One page per tool** | A form for its inputs, a "How it works" explanation, and the results table |

Every run is saved to `data/outputs/<tool>/`. API responses are cached in `.cache/`, so a rerun is instant and free. Switch on **Ignore cache** in the sidebar to fetch fresh data.

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
| `GEMINI_API_KEY` | Query fan-out, clustering, content analysis ([get a key](https://aistudio.google.com/apikey)) |
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

The module docstring becomes the tool's "How it works" text. The tool then appears in the dashboard, `seo tools` and `seo run` with no other changes. [tools/research/autocomplete.py](src/seo_toolkit/tools/research/autocomplete.py) is the reference example.

## Development

```bash
uv run pytest                 # tests (no API calls, no keys needed)
uv run ruff check src tests   # lint
uv run mypy src               # types
```
