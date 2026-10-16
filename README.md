# Auto Deal Researcher

An intelligent deal searching application that automates finding the best deals across multiple online marketplaces in Slovakia, Czech Republic, and international sites.

## Features

- **Multi-platform support**: Works on Windows, Linux, and macOS
- **Site Adapters**: Alza, Bazos (verified working), eBay via the official Browse API; Facebook (needs login), BackMarket and eBay HTML scraping are disabled by default with reasons documented in `config.yaml`
- **Diamond Search**: optional 7-agent pipeline (query expansion, site selection, market intel, domain expert, latest tech, price hunter, recommendation) with LLM budget tracking
- **Condition & Category Filtering**: Filter by `new`, `used`, `refurbished`, `open_box` × `electronics`, `appliances`, `auto`, `general`
- **LLM Integration**: Local LLMs (LM Studio/Ollama) with cloud API fallbacks (OpenRouter, Gemini, Mistral)
- **Browser Automation**: Playwright with CDP connection to existing browser or persistent context fallback
- **Multi-Round Search**: LLM generates query → searches all sites → judges results → refines query for next round
- **Smart Deduplication**: SQLite-based tracking across runs with automatic pruning of stale entries
- **Two Prompt Modes**: Single-run (`--prompt`) or scheduled auto-mode (`--prompt-file`)
- **Cross-Platform Output**: Timestamped JSON + Markdown reports
- **Scheduled Execution**: Windows Task Scheduler + Linux/macOS cron via helper scripts

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/DracieVajko/auto-deal-researcher.git
   cd auto-deal-researcher
   ```

2. **Configure secrets** — keys are **never** stored in `config.yaml`.
   ```bash
   cp config.example.yaml config.yaml   # non-secret settings only
   cp .env.example .env                 # secrets go here, and .env is git-ignored
   # then edit .env and fill in your own keys
   ```
   `config.yaml` references them with `${VAR}` / `${VAR:-default}` placeholders, and
   `.env` is loaded automatically (real environment variables always win).

3. **Install dependencies**
   ```bash
   # Windows
   install_requirements.bat
   
   # Or manually (Linux/macOS/Windows)
   pip install -r requirements.txt
   playwright install chromium
   ```

   Requires Python 3.11–3.13. (The suite also passes on 3.14, but Playwright and
   `pydantic-core` do not publish 3.14 wheels for every platform.)

## Environment variables

All secrets live in `.env` (git-ignored). See `.env.example` for the full list.

| Variable | Used by | Notes |
|---|---|---|
| `LMSTUDIO_ENDPOINT` | config | Optional override; default `http://localhost:1234` |
| `OPENROUTER_API_KEY` | `src/llm/client.py` | https://openrouter.ai/keys |
| `GEMINI_API_KEY` | `src/llm/client.py` | https://aistudio.google.com/apikeys |
| `MISTRAL_API_KEY` | `src/llm/client.py` | https://console.mistral.ai/api-keys |
| `ADS_LOCAL_LLM_TIMEOUT` | `LLMClient` | Seconds, default `900` |
| `ADS_CLOUD_LLM_TIMEOUT` | `LLMClient` | Seconds, default `60` |

`config-check` fails loudly when a `${VAR}` has no value and no default.

## Configuration

The application uses `config.yaml` (copy from `config.example.yaml`):

```yaml
search:
  websites:
    - name: "alza"
      base_url: "https://www.alza.sk"
      enabled: true
      adapter_class: "alza"
      categories: ["electronics", "appliances"]
      conditions: ["new", "open_box"]
    - name: "bazos"
      base_url: "https://www.bazos.sk"
      enabled: true
      adapter_class: "bazos"
      categories: ["electronics", "appliances", "auto", "general"]
      conditions: ["used"]
    # ... more sites
  winners_count: 3
  max_rounds: 3
  retry_on_empty: true
  prune_after_days: 30

llm:
  local:
    - type: "lmstudio"
      endpoint: "http://localhost:1234"
      model: "qwen/qwen3-coder-30b"   # must be a model id LM Studio actually serves
  api_fallback:
    - provider: "openrouter"
      api_key_env: "OPENROUTER_API_KEY"
      model: "mistralai/mistral-7b-instruct"

output:
  format: "both"
  directory: "./results"

schedule:
  tasks:
    - name: "daily-drone-search"
      prompt_file: "prompts/auto.yaml"
      times: ["08:00", "20:00"]
      enabled: true
```

## Usage

### Single Run (Manual)
```bash
# With inline prompt
python -m src.cli run --prompt "DJI drone under 350 euros" --condition refurbished --category electronics

# With prompt file
python -m src.cli run --prompt-file prompts/auto.yaml

# Keep only the best N, and force an output format
python -m src.cli run --prompt "laptop under 1000" --winners 5 --format markdown
```

### Diamond Search (7-agent pipeline)
```bash
python -m src.cli diamond-search --prompt "DJI drone under 350" --condition any --category electronics
```
Runs query expansion → site selection → market intel → domain expert →
latest-tech → price hunter → recommendation, and prints the ranking with the
expert score attached. Agents use the configured LLM and fall back to
deterministic heuristics when no model is reachable, so this never hangs.

### Monitoring
```bash
# One cycle only (useful for smoke tests)
python -m src.cli monitor --prompt-file prompts/auto.yaml --max-runs 1

# Continuous, every 12 hours
python -m src.cli monitor --prompt-file prompts/auto.yaml --interval 12
```
Each cycle writes `results/monitoring/<run_id>.md` with new deals, price
drops/increases, removals and condition changes versus the previous run.

### Logging in to sites that need a real browser (Facebook)

Facebook Marketplace needs a signed-in session and often 2FA or mobile
approval, which a throwaway Playwright profile cannot satisfy. Log in once,
by hand, in a visible browser; the cookies are saved and reused:

```bash
python scripts/login.py --site facebook            # you log in manually
python scripts/login.py --site facebook --check    # is it still valid?
python scripts/login.py --site facebook --logout   # delete it
```

Sessions land in `data/sessions/<site>.json` (git-ignored). They contain real
login cookies — treat them like a password.

### Choosing a browser

Any Chromium-family browser works, and the project detects what you have:

```bash
python -m src.cli browsers
```

```
  brave      Brave (Chromium)           installed  CDP attach OK
  chrome     Google Chrome              installed  CDP attach OK
  msedge     Microsoft Edge             not found  CDP attach OK
  firefox    Mozilla Firefox            not found  no CDP (launch only)
  safari     Safari (WebKit)            not found  no CDP (launch only)
```

Pick one in `config.yaml`:

```yaml
browser:
  browser_id: "brave"        # brave, chrome, msedge, opera, vivaldi, chromium, firefox, safari
```

Left empty, the first installed Chromium browser is chosen, falling back to
Playwright's bundled Chromium. `ADS_BROWSER_EXECUTABLE` overrides everything.
With `separate_profiles: true` (default) each browser gets its own profile
directory, so switching browsers keeps separate logins.

> **CDP attach is Chromium-only.** Playwright cannot attach to a running
> Firefox or Safari; those can only be launched by us. That is a Playwright
> limitation, not a preference.

### Logging in to sites that need a real browser

Sites with 2FA or mobile approval cannot be logged into automatically. Sign
in once, by hand, in a visible browser; the cookies are saved and reused:

```bash
python scripts/login.py --list                 # which sites need it
python scripts/login.py --site facebook        # opens a browser, you log in
python scripts/login.py --all                  # every site that needs it
python scripts/login.py --site facebook --check # still valid?
python scripts/login.py --site facebook --logout
```

Which sites are included comes from `browser.login_sites` in `config.yaml`
plus any adapter declaring `requires_login`.

Sessions are written to `data/sessions/<site>.json`, which is git-ignored.
**They are real login cookies — treat them like a password.**

### Using your own browser over CDP

To drive the browser you already use, start it with a remote debugging port;
the project attaches and reuses that profile's cookies and logins:

```powershell
# Brave (or Chrome), dedicated profile so your everyday one is not locked
& "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$PWD\browser_profile\brave"
```

```yaml
# config.yaml
browser:
  cdp_endpoint: "http://127.0.0.1:9222"
```

Check what the project sees (read-only, loads nothing):

```bash
python -m src.cli local-state
```

> Use `127.0.0.1`, not `localhost`: Chromium binds its debugging port to
> IPv4, while `localhost` may resolve to `::1` first and fail with
> `ECONNREFUSED`. This was the original reason the CDP path silently fell
> back to a fresh profile.

Or let the project launch Brave/Edge/Chrome itself instead of bundled Chromium:

```yaml
browser:
  browser_executable: "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
```

### Diagnostics & health
```bash
# Per-site health: are selectors still valid?
python -m src.cli doctor
python -m src.cli doctor --site bazos

# Recent selector-health events + summary
python -m src.cli selector-health --limit 20

# Historical price / trend queries
python -m src.cli history trends --category electronics
python -m src.cli history watchlist watchlist-cmd list
```

### Sharing a local LLM backend safely

LM Studio and Ollama load models into RAM on demand. Loading our model while
another one is already resident risks OOM or heavy swap on a
RAM-constrained machine. The client therefore checks what is resident before
touching the backend:

```bash
# Read-only: shows what is loaded and what would happen. Loads nothing.
python -m src.cli local-state
```

```
lmstudio: lmstudio:mistralai/ministral-3-14b-reasoning
ollama: not reachable

policy      : wait
quiet window: 300s
foreign models resident (we would wait, then unload after quiet):
  - lmstudio:mistralai/ministral-3-14b-reasoning
```

Configured under `llm.local_coordination` in `config.yaml`:

| Setting | Default | Meaning |
|---|---|---|
| `policy` | `wait` | `wait` respects a resident foreign model and unloads it only after the quiet window; `cloud` never loads or unloads and falls back to cloud providers; `never` does not even probe; `force` unloads immediately |
| `quiet_seconds` | `300` | How long the resident set must stay unchanged before unloading |
| `poll_seconds` | `15` | How often the resident set is re-checked while waiting |
| `max_wait_seconds` | `0` | `0` waits as long as it takes; set a value to fall back to cloud instead of blocking |
| `probe_busy` | `false` | Send a 1-token completion to time queue latency (never loads anything, but occupies a request slot) |

Environment overrides: `ADS_LOCAL_POLICY`, `ADS_LOCAL_QUIET_SECONDS`,
`ADS_LOCAL_POLL_SECONDS`, `ADS_LOCAL_MAX_WAIT`.

> **Known limitation.** Neither backend exposes a read-only "a generation is
> in progress" endpoint — LM Studio replies HTTP 200 with an error body for
> every unknown route, so even the status code carries no signal. "Quiet"
> therefore means the *set of resident models* has not changed for
> `quiet_seconds`. A single long streaming generation keeps the same model
> resident, so it still looks idle after five minutes. Enable `probe_busy`
> for tighter detection if you accept the extra request.

### Scheduled (Auto Mode)
```bash
# Install scheduled tasks (Windows Task Scheduler / cron)
python -m src.cli schedule-install

# Remove scheduled tasks
python -m src.cli schedule-uninstall
```

### Validation & Helpers
```bash
# Validate config
python -m src.cli config-check

# Run via wrapper scripts
# Windows:
.\scripts\run_once.ps1 --Prompt "laptop under 1000€" --Condition new
.\scripts\install_task.ps1

# Linux/macOS:
./scripts/run_once.sh --prompt "laptop under 1000€" --condition new
./scripts/install_cron.sh
```

## Architecture

```
src/
├── cli/
│   ├── app.py                    # Typer CLI (run, monitor, doctor, diamond-search,
│   │                             #   config-check, schedule-*, selector-health)
│   └── commands/                 # monitor, doctor, config_check, history
├── config/                       # Pydantic models + YAML loader with ${VAR} support
├── browser/                      # BrowserManager (CDP + persistent context) + fingerprint
│   └── pom/                      # Page objects and reusable components
├── llm/                          # LLMClient (local-first fallback chain) + MockLLMClient
├── searcher/
│   ├── playwright_searcher.py    # Multi-round search + Diamond orchestration
│   └── adapters/                 # Site-specific adapters
│       ├── base.py               # BaseAdapter, Deal, SiteBlockedError, parse_price_eur
│       ├── alza.py               # https://www.alza.sk/search.htm?exps=
│       ├── bazos.py
│       ├── backmarket.py         # blocked by Cloudflare — disabled by default
│       ├── facebook.py
│       ├── ebay.py               # HTML scraper (unreliable, disabled)
├── agents/                       # 7-agent Diamond Search pipeline
│   ├── coordinator.py            # orchestration + LLM budget
│   ├── llm_support.py            # LLM mixin, JSON extraction, list coercion
│   ├── research/                 # query_expansion, site_selection, market_intel
│   ├── expertise/                # domain_expert, latest_tech_tracker
│   ├── price/                    # price_hunter
│   └── synthesis/                # recommendation
├── intelligence/                 # change_detector, price_tracker
├── diagnostics/                  # doctor, selector_health (JSON + JSONL)
├── history/                      # watchlist, trends
├── notifications/                # console/webhook/discord/email channels + rules
├── storage/                      # StorageManager, schema migrations
├── output/                       # ResultProcessor (JSON + Markdown)
├── scheduler/                    # Cross-platform task installation
└── utils/
```

## Supported Sites (Adapters)

| Site | Adapter id | Status | Notes |
|------|------------|--------|-------|
| Alza.sk/cz | `alza` | ✅ working | Retailer. Uses `/search.htm?exps=`, results are `.browsingitem` |
| Bazos.sk/cz | `bazos` | ✅ working | Classifieds, high volume. Consent handling included |
| eBay (HTML) | `ebay` | ⚠️ disabled | Rate-limited and serves decoy listings to scrapers |
| BackMarket.sk | `backmarket` | ⚠️ disabled | Cloudflare challenge that does not clear for automated sessions |
| Facebook Marketplace | `facebook` | ⚠️ disabled | Requires an authenticated CDP session |

Enable a site by setting `enabled: true` under its entry in `config.yaml`.

## Prompts

Create YAML prompt files in `prompts/`:

```yaml
# prompts/auto.yaml
prompt: |
  I want a DJI drone for under €350 with a 3-axis gimbal, all-around obstacle sensors,
  at least 20 minutes flight time. Prefer DJI Mini 3 Pro, Air 2S, or Mavic 3 Classic.
  Condition: refurbished or open-box acceptable. Sites: BackMarket, Alza (open-box), eBay, Bazos.
  Category: electronics. Exclude: broken, for parts, no controller.
```

See `prompts/example_prompts.md` for more examples.

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
mypy src/
```

## License

MIT