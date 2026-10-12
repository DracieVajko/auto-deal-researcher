# Auto Deal Researcher

An intelligent deal searching application that automates finding the best deals across multiple online marketplaces in Slovakia, Czech Republic, and international sites.

## Features

- **Multi-platform support**: Works on Windows, Linux, and macOS
- **Site Adapters**: Native adapters for Alza, Bazos, BackMarket, Facebook Marketplace, eBay (extensible)
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

2. **Configure** (copy template and add your API keys)
   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml with your endpoints and API keys
   ```

3. **Install dependencies**
   ```bash
   # Windows
   install_requirements.bat
   
   # Or manually (Linux/macOS/Windows)
   pip install -r requirements.txt
   playwright install chromium
   ```

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
      endpoint: "http://100.88.219.120:1234"
      model: "auto"
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
```

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
├── cli.py                    # Typer CLI with run/schedule/config-check
├── config/                   # Pydantic models + YAML loader
├── browser/                  # BrowserManager (CDP + persistent context)
├── llm/                      # LLMClient (local-first fallback chain)
├── searcher/
│   ├── playwright_searcher.py  # Multi-round search orchestrator
│   └── adapters/               # Site-specific adapters
│       ├── base.py             # BaseAdapter + Deal dataclass
│       ├── alza.py
│       ├── bazos.py
│       ├── backmarket.py
│       ├── facebook.py
│       └── ebay.py
├── storage/                  # StorageManager (SQLite dedup + prune)
├── output/                   # ResultProcessor (JSON + Markdown)
└── scheduler/                # Cross-platform task installation
```

## Supported Sites (Adapters)

| Site | Adapter | Conditions | Categories | Notes |
|------|---------|------------|------------|-------|
| Alza.sk/cz | `alza` | new, open_box | electronics, appliances | Major SK/CZ retailer |
| Bazos.sk/cz | `bazos` | used | all | Classifieds, high volume |
| BackMarket.sk | `backmarket` | refurbished | electronics | Refurbished specialist |
| Facebook Marketplace | `facebook` | used, marketplace | all | Requires CDP login |
| eBay.de/co.uk | `ebay` | used, refurbished, new, open_box | all | International |

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

# Format code
black src/

# Lint
flake8 src/
```

## License

MIT