"""Monitor command - scheduler loop."""

import typer


def monitor(max_runs: int | None = None, prompt: str | None = None):
    """Run scheduler loop (importable function for tests)."""
    from src.config import load_config

    config = load_config()
    runs = 0
    while max_runs is None or runs < max_runs:
        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
    return runs
