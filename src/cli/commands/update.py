"""CLI command: update the application from GitHub."""

from __future__ import annotations

import typer

from src.updater import check_for_updates, update_from_github


def update(
    check: bool = typer.Option(False, "--check", help="Only check for updates, do not apply"),
    branch: str = typer.Option("master", "--branch", help="Branch to track"),
    no_deps: bool = typer.Option(False, "--no-deps", help="Skip dependency reinstall"),
    stash: bool = typer.Option(False, "--stash", help="Stash local changes before updating"),
) -> None:
    """Check for and apply updates from GitHub."""
    info = check_for_updates(branch=branch)
    typer.echo(f"Branch: {info.branch}")
    typer.echo(f"Current: {info.current_commit or '(unknown)'}")
    typer.echo(f"Latest:  {info.latest_commit or '(unknown)'}")
    if not info.success and info.error:
        typer.echo(f"Warning: {info.error}", err=True)

    if check:
        if info.update_available:
            typer.echo("Update available.")
            raise typer.Exit(code=0)
        typer.echo("Already up to date.")
        return

    if not info.update_available and info.current_commit and info.latest_commit:
        typer.echo("Already up to date. Forcing pull anyway...")

    result = update_from_github(
        branch=branch,
        install_deps=not no_deps,
        stash=stash,
    )
    if result.success:
        typer.echo(result.message)
        if result.current_commit:
            typer.echo(f"Now at: {result.current_commit}")
    else:
        typer.echo(f"Update failed: {result.error or result.message}", err=True)
        raise typer.Exit(code=1)
