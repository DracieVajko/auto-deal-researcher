# Auto Deal Researcher

An intelligent deal searching application that automates finding the best deals across multiple online marketplaces in Slovakia, Czech Republic, and international sites.

## Features

- **Multi-platform support**: Works on Windows, Linux, and macOS
- **Site Adapters + Auto-Mapping**: 30 registered marketplaces, profile-driven discovery and a generic profile adapter; Alza, Bazos and Nay adapters verified working
- **Location-Aware Shop Selection**: the AI picks which shops to visit, ranked by your market (`user_country`), so local shops come first and cross-border ones only when they make sense
- **Runtime Filters**: canonical price/condition/brand/location/shipping/seller/sort filters applied through URL parameters, UI controls, then a Python post-filter
- **Currency Normalisation**: CZK, USD and GBP prices are converted to EUR, with the original amount kept alongside
- **Diamond Search**: optional 7-agent pipeline (query expansion, site selection, market intel, domain expert, latest tech, price hunter, recommendation) with LLM budget tracking
- **Condition & Category Filtering**: Filter by `new`, `used`, `refurbished`, `open_box` × `electronics`, `appliances`, `auto`, `home`, `hobby`, `general`
- **LLM Integration**: Local LLMs (LM Studio/Ollama) with cloud API fallbacks (OpenRouter, Gemini, Mistral)
- **Browser Automation**: Playwright with CDP connection to existing browser or persistent context fallback
- **Multi-Round Search**: LLM generates query → searches all sites → judges results → refines query for next round
- **Smart Deduplication**: SQLite-based tracking across runs with automatic pruning of stale entries
- **Two Prompt Modes**: Single-run (`--prompt`) or scheduled auto-mode (`--prompt-file`)
- **Cross-Platform Output**: Timestamped JSON + Markdown reports
- **Scheduled Execution**: Windows Task Scheduler + Linux/macOS cron via helper scripts

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
`setup.bat --check` / `setup.sh --check` only reports what is in place without
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

2. **Configure secrets** — keys are **never** stored in `config.yaml`.
   ```bash
   cp config.example.yaml config.yaml   # non-secret settings only
   cp .env.example .env                 # secrets go here, and .env is git-ignored
   ```
   `config.yaml` references them with `${VAR}` / `${VAR:-default}` placeholders, and
   `.env` is loaded automatically (real environment variables always win).

3. **Install dependencies**
   ```bash
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
| `ADS_LOCAL_LLM_TIMEOUT` | `LLMClient` | Seconds, default `180` |
| `ADS_CLOUD_LLM_TIMEOUT` | `LLMClient` | Seconds, default `120` |
| `ADS_GEMINI_MIN_OUTPUT_TOKENS` | `LLMClient` | Output-token floor for Gemini thinking models, default `512` |
| `ADS_BAZOS_DETAILS` | `BazosAdapter` | `1` (default) fetches each listing's detail page for description and town; `0` skips the extra requests |
| `ADS_BAZOS_DETAIL_LIMIT` | `BazosAdapter` | Maximum detail pages fetched per search, default `10` |

`config-check` fails loudly when a `${VAR}` has no value and no default.

### Which LLM providers actually work?

`run` logs a single line per failed provider, and a dead key otherwise shows up
only as a slow run. Probe every provider on its own instead:

```bash
python -m src.cli llm-check
```

```
provider     kind   status    latency  model
------------------------------------------------------------
lmstudio     local  http        6.37s  qwen/qwen3-coder-30b
             HTTP 400: Failed to load model "qwen/qwen3-coder-30b". Error: Engine protocol startup was aborted.
openrouter   cloud  auth        0.46s  poolside/laguna-s-2.1:free
             HTTP 401: User not found.
             hint: Create or rotate the key at https://openrouter.ai/keys.
gemini       cloud  ok          0.71s  gemini-2.5-flash
mistral      cloud  ok          0.88s  ministral-14b-2512

2/5 providers healthy
```

Exit code is `1` when no provider is healthy, so it works as a pre-flight
check. Useful flags: `--no-local`, `--no-cloud`, `--timeout`, `--local-timeout`.

Runtime behaviour worth knowing:

- A provider that answers **HTTP 401/403** is disabled for the rest of the run
  instead of being retried on every LLM call.
- Other provider failures open a circuit breaker after two attempts
  (`ADS_LOCAL_BREAKER_THRESHOLD`, cooldown `ADS_LOCAL_BREAKER_COOLDOWN`).
- Gemini thinking models spend the output budget on reasoning first; a tiny
  `max_tokens` returns `200 OK` with no text. The client enforces a floor
  (`ADS_GEMINI_MIN_OUTPUT_TOKENS`). Prefer `gemini-2.5-flash` over 3.x thinking
  models for short queries — 3.x can take a minute per reply.

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
      country: "SK"
      currency: "EUR"
    - name: "bazos"
      base_url: "https://www.bazos.sk"
      enabled: true
      adapter_class: "bazos"
      categories: ["electronics", "appliances", "auto", "general"]
      conditions: ["used"]
      country: "SK"
      currency: "EUR"
    # ... more sites (all 30 registered sites are listed in config.example.yaml)
  # Optional baseline filters. Precedence: CLI > prompt/LLM > these defaults.
  default_filters: {}
  # Where you shop. Local shops are preferred, neighbouring markets next.
  user_country: "SK"
  user_city: ""
  # How many shops may be opened per search round.
  max_sites: 8
  # Static EUR rates; adjust when they drift.
  currency_rates:
    EUR: 1.0
    CZK: 0.0265
  winners_count: 3
  max_rounds: 3
  retry_on_empty: true
  prune_after_days: 30

llm:
  local:
    - type: "lmstudio"
      endpoint: "http://localhost:1234"
      model: "google/gemma-4-26b-a4b"   # gemma 26B; small bonsai/qwen 9B preferred for tagging
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
  domain: ""          # force a product domain; empty = auto-detect

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

### Runtime filters

Filters can come from the prompt, the CLI, or `search.default_filters`.
Precedence is **CLI > prompt/LLM > config default**. The canonical keys are
`min_price`, `max_price`, `condition`, `brand`, `location`, `shipping`,
`seller_type`, `sort`, plus arbitrary extras.

```bash
python -m src.cli run --prompt "notebook" --max-price 500 --condition used
python -m src.cli run --prompt "grafická karta" --min-price 100 --max-price 250 \
  --brand amd --sort price_asc --filter socket=AM5
python -m src.cli run --prompt "notebook do 400 EUR, doprava zdarma"
```

Each site profile declares which filters it supports. At runtime the engine
tries URL parameters first, then visible form controls, and finally removes
anything still outside the requested range/condition in Python. Unknown
prices are kept (the site did not expose a price), while known metadata is
enforced.

### Which shops get searched

The searcher does not open every registered shop. It works in three steps:

1. **Deterministic filter** — enabled sites that carry the requested
   category and condition, and that have an adapter or a validated profile.
2. **Location ranking** — sites in your market (`search.user_country`) come
   first, neighbouring EU markets second, the rest last.
3. **AI selection** — the LLM narrows the ranked list down to the shops worth
   visiting for this prompt. It can only narrow the list, never widen it, and
   it falls back to the ranking when it fails.

```bash
# Prefer Slovak shops, open at most 5 of them.
python -m src.cli run --prompt "stol" --category home --country SK --max-sites 5

# Prefer Czech shops and look at cars.
python -m src.cli run --prompt "octavia" --category auto --country CZ
```

`--country` overrides `search.user_country` for a single run.

### Product domains

Every listing is matched to a **product domain** from its own text (title and
metadata), never from the shop or the search category. Each domain tracks the
specs that matter for that product type and scores only the rows the domain
enables.

Built-in domains: `bike`, `computer`, `phone`, `car`, `furniture`. Anything
unrecognised falls back to `generic`, which scores neutral on specs rather
than guessing.

```bash
# Force the domain instead of auto-detecting it.
python -m src.cli run --prompt "mini pc" --domain computer
python -m src.cli run --prompt "kolo 26 palcove" --domain bike
```

`--domain` overrides `output.domain` in the config, and both override
auto-detection. An unknown name is rejected with the list of valid domains.

When an LLM is configured and a listing matches no built-in domain, the model
may **propose** a new one — its keywords, the specs worth tracking and the
values it found. The proposal is validated, applied only to listings that
match its own keywords, and cached under `data/domains/ai/*.yaml` (git-ignored)
for later runs. A cached draft is never written into `src/`; promoting it to a
real domain with deterministic extractors is a human decision.

### Prompt-only search

The prompt alone is enough. Condition, category, price, brand, shipping,
location and sort are read from it (in five languages); the explicit
`--condition` / `--category` / `--max-price` flags remain as overrides.
`--category any` forces the old broad shop list even when the model guesses
a category.

```bash
# Only the prompt is required.
python -m src.cli run --prompt "used refurbished DJI drone under 350 euros"

# Or the interactive wizard, which prints what it understood before searching.
python -m src.cli ask
```

The wizard asks three questions (the prompt is mandatory; country and max
shops accept Enter for the config defaults) and prints `Understood:
condition=..., category=...` plus the selected shops before any browser opens.
When both a local (lmstudio/ollama) and a cloud (mistral/gemini/openrouter)
backend are configured it also asks which LLM to use; with only one available
it picks it silently. `run` accepts the same choice via `--llm {local,cloud,auto}`.

### Launcher scripts

Double-click entry points for users who do not want to remember the CLI flags.
They live at the repository root (and are also available under `scripts/`):

```bash
# Windows (root or scripts/)
search.bat

# Linux / macOS (root or scripts/, once, after clone)
chmod +x search.sh
./search.sh
```

Both start `src.cli ask`. On Windows the window stays open at the end so the
report paths can be copied; on POSIX the exit code is propagated.
`run_once.ps1` and `run_once.sh` still work as scheduled-run wrappers, and
now forward `-Condition`/`-Category` only when you supply them.

### Currency

Prices are converted to EUR, so `--max-price` means the same thing on every
site. A car at `242 000 Kč` is stored as `€6 413` with the original amount
kept in `original_price` / `original_currency`. The rates are static and live
in `search.currency_rates`; adjust them there when they drift.

### Site discovery and profiles

All 30 registered sites are listed in `config.example.yaml`. Sites without an
adapter need a validated profile before they participate in a search.

```bash
# Record a search page, filters and extraction selectors.
python scripts/discover_sites.py discover --all --headed

# One site/category, or resume only unfinished work.
python scripts/discover_sites.py discover --site mall --category electronics
python scripts/discover_sites.py discover --site jysk_sk --category home --headed
python scripts/discover_sites.py discover --all --resume

# Replay saved profiles and update their status.
python scripts/discover_sites.py validate --all
```

`discover` opens each site, accepts cookie banners, submits a category seed
query, records controls/cards, and writes a sanitized profile. If Cloudflare
or a login wall appears, the headed browser pauses so you can solve it and
press Enter. Use `--no-pause` for non-interactive batch runs.

- Raw recordings (HTML, controls, optional screenshots) go to
  `flows/<site>/<category>.json` and are **git-ignored**.
- Sanitized profiles go to `src/searcher/site_profiles/<site>.yaml` and are
  safe to commit. Cookies, headers, raw HTML, tokens and e-mail addresses are
  stripped.
- Profile status is one of `draft`, `validated`, `failed`, `needs_login`,
  `blocked`, `needs_manual`. Only `validated` profiles drive a generic
  `ProfileAdapter` at runtime; registered adapters also run without a profile.

A profile stores `search` (URL template/query parameter), `filters` (canonical
key → URL/UI descriptor) and `extraction` (card/title/price/link selectors).
The generic `ProfileAdapter` uses that data directly; registered adapters
(Alza, Bazos, etc.) keep their own extraction but receive profile filters.

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

# Check which LLM providers are reachable and authorised
python -m src.cli llm-check

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
│   │                             #   config-check, llm-check, schedule-*, selector-health)
│   └── commands/                 # monitor, doctor, config_check, history
├── config/                       # Pydantic models + YAML loader with ${VAR} support
├── browser/                      # BrowserManager (CDP + persistent context) + fingerprint
│   └── pom/                      # Page objects and reusable components
├── llm/                          # LLMClient (local-first fallback chain) + MockLLMClient
├── searcher/
│   ├── playwright_searcher.py    # Multi-round search + Diamond orchestration
│   ├── filters.py                # Canonical filters, CLI/prompt parsing
│   ├── filter_engine.py          # URL → UI → post-filter application
│   ├── site_profiles.py          # Profile schema, loader, sanitizer
│   ├── site_registry.py          # 30 sites, categories, markets and discovery seeds
│   ├── site_selection.py         # Location-aware ranking + LLM shop selection
│   ├── currency.py               # Currency detection and EUR conversion
│   ├── site_profiles/            # Sanitized committed profile YAML maps
│   └── adapters/                 # Site-specific adapters
│       ├── base.py               # BaseAdapter, Deal, SiteBlockedError, parse_price_eur
│       ├── profile_adapter.py    # Generic adapter driven by a SiteProfile
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
| Alza.sk | `alza` | ✅ working | Retailer. Uses `/search.htm?exps=`, results are `.browsingitem` |
| Bazos.sk | `bazos` | ✅ working | Classifieds, high volume. Consent handling included |
| BackMarket.sk | `backmarket` | ⛔ blocked | Cloudflare challenge that does not clear for automated sessions |
| eBay.de | `ebay` | ⛔ blocked | Rate-limited and serves decoy listings to scrapers |
| Facebook Marketplace | `facebook` | 🔐 needs auth | Requires an authenticated CDP session |
| Mall.sk/cz | `mall` | 🧭 planned | Run discovery to create a validated profile |
| Nay.sk | `nay` | 🧭 planned | Run discovery to create a validated profile |
| Heureka.sk | `heureka` | 🧭 planned | Price comparison; discovery profile needed |
| Idealo.de | `idealo` | 🧭 planned | German price comparison; discovery profile needed |
| Aukro.cz | `aukro` | 🧭 planned | Auction marketplace; bid logic not implemented |
| Bazos.cz | `bazos` | 🧭 planned | Reuses the Bazos adapter with `base_url: https://www.bazos.cz` |
| Amazon.de | `amazon` | 🧭 planned | Official Product Advertising API is the supported route |
| Alza.cz | `alza` | 🧭 planned | Reuses the Alza adapter with `base_url: https://www.alza.cz` |
| AliExpress | `aliexpress` | 🧭 planned | Official Affiliate API is the supported route |
| Prisiel.sk | `prisiel` | 🧭 planned | SK classifieds; discovery profile needed |
| Bazar.sk | `bazar_sk` | 🧭 planned | SK classifieds; discovery profile needed |
| Sreality.cz | `sreality` | 🧭 planned | CZ real estate; general category only |
| Mimibazar.sk | `mimibazar` | 🧭 planned | SK classifieds; lots of used electronics |
| Autobazar.sk | `autobazar` | 🧭 planned | Ringier SK auto portal; prices in EUR |
| Autobazar.EU | `autobazar` | 🧭 planned | 310k+ listings across SK/CZ/PL |
| Autobazar.cz | `autobazar` | 🧭 planned | Redirects to Autobazar.EU |
| mobile.de | `mobile_de` | 🧭 planned | Germany's largest vehicle marketplace |
| OBI Slovensko | `obi` | 🧭 planned | Home, flat, garden and building supplies |
| Merkury Market | `merkurymarket` | 🧭 planned | Building materials, furniture and garden |
| BAUHAUS Slovensko | `bauhaus` | 🧭 planned | Workshop, house and garden |
| Hornbach Slovensko | `hornbach` | ⛔ blocked | Serves a bot wall to automated sessions |
| JYSK Slovensko | `jysk` | 🧭 planned | Furniture, mattresses and textiles |
| FAVI.sk | `favi` | 🧭 planned | Furniture search engine that links out to shops |
| IKEA Slovensko | `ikea` | 🧭 planned | Furniture and home accessories |
| Decathlon Slovensko | `decathlon` | ⛔ blocked | Cloudflare wall |

Enable a site by setting `enabled: true` under its entry in `config.yaml`.
Planned sites need a validated profile from `scripts/discover_sites.py` unless
their adapter is registered. `alza_cz` and `bazos_cz` already reuse working
adapters; they are disabled by default to avoid cross-border duplicates.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
