# Auto Deal Researcher

An intelligent deal-searching application that automates finding the best
deals across multiple online marketplaces in Slovakia, Czechia, and
international sites. It searches, judges, ranks and reports second-hand
listings so you do not have to browse dozens of shops by hand.

## What it does

Give it a plain-language request such as *"Mini PC 32 GB RAM under €500"* or
*"used iPhone 15 128 GB"*, and the project:

1. Turns the request into structured filters (price, condition, category,
   brand, location, shipping).
2. Picks the marketplaces that fit your country and the requested category.
3. Opens the shops, extracts listings, and normalises prices to EUR
   (including shipping, bundles, coupons and gated prices).
4. Judges every listing against your request, ranks them by relevance and
   effective price, and writes a readable Markdown/JSON report with the
   winner, runner-ups and a full comparison table.

It works offline-first with local LLMs (LM Studio / Ollama) and falls back to
cloud APIs (Gemini, Mistral, OpenRouter) when no local model is reachable.

## Key features

- **Multi-platform** — Windows, Linux and macOS.
- **30 registered marketplaces** — profile-driven discovery plus dedicated
  adapters for Alza, Bazos, BackMarket, eBay, Facebook Marketplace and more.
- **Location-aware shop selection** — local shops come first, cross-border
  ones only when they make sense.
- **Runtime filters** — price, condition, brand, location, shipping, seller
  type and sort, applied via URL parameters, UI controls and a Python
  post-filter.
- **Currency normalisation** — CZK, USD and GBP converted to EUR; original
  amount kept alongside.
- **Effective-price ranking** — shipping, bundles, coupons and gated prices
  are factored into a comparable price and a trust score.
- **Diamond Search** — optional 7-agent pipeline (query expansion, site
  selection, market intel, domain expert, latest tech, price hunter,
  recommendation) with LLM budget tracking.
- **Product domains** — bike, computer, phone, car, furniture and generic;
  unknown domains can be proposed by the LLM and reviewed before adoption.
- **LLM integration** — local models (LM Studio / Ollama) with cloud API
  fallbacks and a model lifecycle monitor (load / wait / unload).
- **Browser automation** — Playwright with CDP attach to your existing
  browser or a persistent context fallback; login sessions saved for
  sites that need them (e.g. Facebook Marketplace).
- **Smart deduplication** — SQLite-based tracking across runs with
  automatic pruning of stale entries.
- **Scheduled searches** — plain-text prompt folders (`prompts/single/`
  run once, `prompts/watchdog/` run daily) plus database jobs, through a
  serial monitor with a daily Windows Task Scheduler entry.
- **Cross-platform output** — timestamped JSON, Markdown, CSV and optional
  XLSX reports.

## Installation

One command does the whole first run:

```bash
# Windows
scripts\setup.bat

# macOS / Linux
./scripts/setup.sh
```

It checks Python, creates a virtualenv, installs dependencies and Playwright,
creates `config.yaml` and `.env` from the templates, asks which browser to
use, and verifies the result. Re-run it any time; finished steps are skipped.
`setup.bat --check` / `setup.sh --check` only report what is in place without
changing anything.

Then, once, sign in to the sites that need it:

```bash
scripts\login.bat              # Windows, every site that needs a login
python scripts/login.py --all
```

### Manual install

1. **Clone the repository**

   ```bash
   git clone https://github.com/DracieVajko/auto-deal-researcher.git
   cd auto-deal-researcher
   ```

2. **Configure secrets** — keys are never stored in `config.yaml`.

   ```bash
   cp config.example.yaml config.yaml   # non-secret settings only
   cp .env.example .env                 # secrets go here, and .env is git-ignored
   ```

   `config.yaml` references secrets with `${VAR}` / `${VAR:-default}`
   placeholders, and `.env` is loaded automatically. Real environment
   variables always win.

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

   Requires Python 3.11-3.13.

## Quick start

Search once:

```bash
python -m src.cli run --prompt "Mini PC 32 GB RAM under 500 euros" \
  --condition refurbished --category electronics --winners 5
```

Run interactively (the wizard prints what it understood before searching):

```bash
python -m src.cli ask
```

Schedule a daily watchdog:

```bash
python -m src.cli schedule new --name ev --mode watchdog \
  --prompt "electric car under 10000 EUR" --category auto --max-price 10000
python -m src.cli schedule service --exit-when-idle
```

Register the daily Windows task (runs at 05:00 local time):

```bash
python -m src.cli schedule install-startup --at 05:00
```

## Configuration

The application uses `config.yaml` (copy from `config.example.yaml`):

```yaml
search:
  user_country: "SK"
  user_city: ""
  max_sites: 8
  currency_rates:
    EUR: 1.0
    CZK: 0.0265
  winners_count: 3
  max_rounds: 3
  retry_on_empty: true
  prune_after_days: 30

llm:
  local_coordination:
    enabled: true
    policy: "wait"
    preload: true
    unload_after_job: true
  local:
    - type: "lmstudio"
      endpoint: "http://localhost:1234"
      model: "nvidia-nemotron-3.5-bolt-e4b"
  api_fallback:
    - provider: "mistral"
      api_key_env: "MISTRAL_API_KEY"
      model: "ministral-14b-2512"
    - provider: "gemini"
      api_key_env: "GEMINI_API_KEY"
      model: "gemini-2.5-flash"

output:
  format: "both"
  directory: "./results"

schedule:
  tasks: []
```

All secrets live in `.env` (git-ignored). See `.env.example` for the full
list.

| Variable | Used by | Notes |
|---|---|---|
| `LMSTUDIO_ENDPOINT` | config | Optional override; default `http://localhost:1234` |
| `OPENROUTER_API_KEY` | `src/llm/client.py` | https://openrouter.ai/keys |
| `GEMINI_API_KEY` | `src/llm/client.py` | https://aistudio.google.com/apikeys |
| `MISTRAL_API_KEY` | `src/llm/client.py` | https://console.mistral.ai/api-keys |
| `ADS_LOCAL_LLM_TIMEOUT` | `LLMClient` | Seconds, default `180` |
| `ADS_CLOUD_LLM_TIMEOUT` | `LLMClient` | Seconds, default `120` |
| `ADS_GEMINI_MIN_OUTPUT_TOKENS` | `LLMClient` | Output-token floor for Gemini thinking models |
| `ADS_BAZOS_DETAILS` | `BazosAdapter` | `1` fetches each listing's detail page; `0` skips |

`config-check` fails loudly when a `${VAR}` has no value and no default:

```bash
python -m src.cli config-check
python -m src.cli llm-check
```

## Scheduled searches (single run vs watchdog)

The `schedule` subsystem runs jobs through one serial monitor. There are two
job modes:

| Mode | What it does |
|---|---|
| `single` | Search once, then a `.done` sidecar stops it repeating. |
| `watchdog` | Repeat on a trigger (daily by default). |

### Prompt folders (recommended)

Put plain-text prompts in one of two folders:

- `prompts/single/` — run once, then `<name>.txt.done` stops repeats.
- `prompts/watchdog/` — run once per day; `<name>.txt.state.json` stores the
  run date.

Create a file with the CLI (or copy `_template.txt`):

```bash
python -m src.cli schedule new --name ev --mode watchdog \
  --prompt "electric car under 10000 EUR" --category auto --max-price 10000
```

File format (settings before `---`, prompt after it):

```text
category: auto
condition: any
max_price: 10000
schedule: 05:00
---
Electric car under 10000 EUR, used or new, battery in good condition,
real range at least 250 km.
```

The service scans both folders on every run. Delete the `.txt` file to remove
the job; `schedule rm-file <name>` also removes the sidecars.
`schedule files` lists file prompts and their status, and `schedule list`
shows both database jobs and file prompts.

### Manual run

Drain every job that is due now, then exit:

```bash
python -m src.cli schedule service --exit-when-idle
```

Omit `--exit-when-idle` for a permanent daemon (`Ctrl+C` to stop).

### Automatic run

Register a daily Windows task at 05:00 local time:

```bash
python -m src.cli schedule install-startup --at 05:00
```

The task runs `python -m src.cli schedule service --exit-when-idle`, so it
drains all due jobs, unloads the local model and exits. Remove it with:

```bash
python -m src.cli schedule uninstall-startup
```

On Linux/macOS use cron instead:

```cron
0 5 * * * cd /path/to/repo && python -m src.cli schedule service --exit-when-idle
```

The daily batch keeps the local model loaded between jobs and releases it at
the end; `config.yaml` sets `llm.local_coordination.preload: true` and
`unload_after_job: true`.

## Supported sites (adapters)

| Site | Adapter | Status | Notes |
|---|---|---|---|
| Alza.sk | alza | working | Retailer. Uses `/search.htm?exps=` |
| Bazos.sk | bazos | working | Classifieds, high volume. Consent handling included |
| BackMarket.sk | backmarket | blocked | Cloudflare challenge does not clear for automated sessions |
| eBay.de | ebay | blocked | Rate-limited and serves decoy listings to scrapers |
| Facebook Marketplace | facebook | needs auth | Requires an authenticated CDP session |
| Mall.sk/cz | mall | planned | Run discovery to create a validated profile |
| Nay.sk | nay | planned | Run discovery to create a validated profile |
| Heureka.sk | heureka | planned | Price comparison; discovery profile needed |
| Idealo.de | idealo | planned | German price comparison; discovery profile needed |

Enable a site by setting `enabled: true` under its entry in `config.yaml`.
Planned sites need a validated profile from
`scripts/discover_sites.py` unless their adapter is registered.

## Development

```bash
# Run tests
pytest tests/

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Format / lint
black src/
ruff check src/

# Type check
mypy src --no-incremental --python-version 3.12
```

CI runs `mypy src` and `pytest -q` on every push and pull request.

## Architecture

```
src/
├── cli/
│   ├── app.py                    # Typer CLI (run, ask, watch, monitor,
│   │                             #   diamond-search, schedule-*, ...)
│   └── commands/                 # schedule, monitor, doctor, ...
├── scheduler/                    # plan, queue, service, task install
├── config/                       # Pydantic models + YAML loader
├── browser/                      # BrowserManager (CDP + persistent context)
│   └── pom/                      # Page objects and components
├── llm/                          # LLMClient (local-first fallback chain)
├── text/                         # Text normalisation
├── searcher/
│   ├── playwright_searcher.py    # Multi-round search + Diamond orchestration
│   ├── filters.py                # Canonical filters, CLI/prompt parsing
│   ├── filter_engine.py          # URL / UI / post-filter application
│   ├── site_profiles.py          # Profile schema, loader, sanitizer
│   ├── site_registry.py          # Registered sites, categories, markets
│   ├── site_selection.py         # Location-aware ranking + LLM shop selection
│   ├── currency.py               # Currency detection and EUR conversion
│   ├── site_profiles/            # Sanitized committed profile YAML maps
│   └── adapters/                 # Site-specific adapters
├── agents/                       # 7-agent Diamond Search pipeline
├── intelligence/                 # change_detector, price_tracker
├── diagnostics/                  # doctor, selector_health
├── history/                      # watchlist, trends
├── notifications/                # console/webhook/discord/email channels
├── storage/                      # StorageManager, schema migrations
├── output/                       # ResultProcessor (JSON + MD + CSV + XLSX)
└── utils/
```

## Roadmap

Short-term priorities:

- Expand the set of validated site profiles (Mall, Nay, Heureka, Idealo).
- Add more notification channels and digest reports.
- Improve the LLM judge/rank reliability on smaller local models.
- Add more export formats and scheduled-report emailing.

Longer-term:

- Public web dashboard for browsing historical runs and price trends.
- Cross-marketplace price-change alerts (price-drop watchdog).
- Mobile-friendly report rendering.

## Sponsors

Auto Deal Researcher is developed and maintained in my spare time. Sponsorship
helps fund:

- Ongoing development and new marketplace integrations
- Bug fixes and reliability improvements
- Maintenance of adapters as sites change their markup
- Documentation and example prompt files
- Testing and CI coverage

If you find the project useful, consider sponsoring the work on
[GitHub Sponsors](https://github.com/sponsors/DracieVajko). Sponsorship helps
keep the project actively maintained and accelerates new integrations.

You can also support the project by opening issues, submitting pull requests,
or spreading the word.
See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are licensed under the
MIT License.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Never commit `.env`, `data/sessions/`, or
flows recordings — they contain real cookies and secrets and are git-ignored.
