"""Doctor command."""

import typer


def doctor(site: str | None = None, offline: bool = False):
    """Run site health diagnostics (importable function for tests)."""
    import asyncio

    from src.cli.app import doctor_async

    return asyncio.run(doctor_async(site, offline))


def typer_doctor(
    site: str | None = typer.Option(None, "--site", "-s"),
    offline: bool = typer.Option(False, "--offline"),
):
    """Typer wrapper."""
    return doctor(site, offline)
