"""Run command - single search cycle."""

import typer


def run(
    prompt: str | None = None,
    prompt_file: str | None = None,
    condition: str = "any",
    category: str = "any",
    winners: int | None = None,
    output_format: str | None = None,
):
    """Run a single search cycle (importable function for tests)."""
    import asyncio

    from src.cli.app import _run_async

    return asyncio.run(_run_async(prompt, prompt_file, condition, category, winners, output_format))


def typer_run(
    prompt: str | None = typer.Option(None, "--prompt", "-p"),
    prompt_file: str | None = typer.Option(None, "--prompt-file", "-f"),
    condition: str = typer.Option("any", "--condition", "-c"),
    category: str = typer.Option("any", "--category", "-cat"),
    winners: int | None = typer.Option(None, "--winners", "-w"),
    output_format: str | None = typer.Option(None, "--format"),
):
    """Typer wrapper."""
    return run(prompt, prompt_file, condition, category, winners, output_format)
