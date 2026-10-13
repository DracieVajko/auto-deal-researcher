"""Config check command."""

import typer


def config_check():
    """Validate config.yaml against schema (importable function for tests)."""
    from src.config import load_config

    config = load_config()
    typer.echo("✅ Config valid")
    typer.echo(f"  Sites enabled: {[s.name for s in config.search.websites if s.enabled]}")
    return True
