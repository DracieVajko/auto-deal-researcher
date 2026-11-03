def test_cli_commands_import():
    from src.cli.commands.monitor import monitor
    from src.cli.commands.run import run
    assert callable(run)
    assert callable(monitor)


def test_sites_command_lists_the_catalogue():
    from typer.testing import CliRunner

    from src.cli import app

    result = CliRunner().invoke(app, ["sites", "--all"])
    assert result.exit_code == 0, result.output
    assert "alza" in result.output
    assert "nkon_nl" in result.output
    assert "status" in result.output
