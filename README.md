# Auto Deal Searcher

An intelligent deal searching application that automates finding the best deals across multiple online marketplaces.

## Features

- **Multi-platform support**: Works on Windows, Linux, and macOS
- **Configurable search**: Define your preferred websites and search parameters
- **LLM Integration**: Uses local LLMs (Ollama/LM Studio) with cloud API fallbacks
- **Browser Automation**: Playwright-based scraping with login state preservation
- **Smart Filtering**: LLM-powered judgment to filter and rank results
- **Cross-platform Output**: Results saved in both JSON and Markdown formats
- **Deduplication**: Prevents duplicate results across search runs
- **Scheduled Execution**: Can be run via task schedulers

## Installation

1. Clone the repository
2. Run `install_requirements.bat` (Windows) or `pip install -r requirements.txt` (Linux/macOS)
3. Install Playwright browsers with `playwright install`

## Configuration

The application uses a YAML configuration file (`config.yaml`) to define:
- Preferred websites (allowlist/blocklist)
- LLM endpoints (local and API fallbacks)
- Output formats
- Number of winners to return

Example configuration:
```yaml
search:
  websites:
    - name: "Alza"
      url_pattern: "https://www.alza.sk"
      allowlisted: true
      blocklisted: false
    - name: "Bazoš"
      url_pattern: "https://www.bazos.sk"
      allowlisted: true
      blocklisted: false
  llm:
    local_endpoint: "http://localhost:11434"
    api_key: null
    model_name: "llama3"
  output_format: "both"
  winners_count: 3
```

## Usage

### Command Line Interface
```bash
# Show help
python -m src.cli --help

# Run deal search
python -m src.cli run
```

## Architecture

The application follows a modular design:
- **Configuration Management**: YAML-based configuration loading
- **Browser Manager**: Playwright integration with CDP and persistent context fallback
- **Search Engine**: Playwright-based web scraping
- **LLM Integration**: Local (Ollama) and API (OpenAI-style) support
- **Result Processor**: JSON and Markdown output generation
- **Storage Manager**: SQLite-based deduplication across runs

## Development

### Running Tests
```bash
pytest tests/
```

### Code Style
This project uses black for code formatting and flake8 for linting.

## License

MIT