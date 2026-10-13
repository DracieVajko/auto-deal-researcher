def test_cli_commands_import():
    from src.cli.commands.monitor import monitor
    from src.cli.commands.run import run
    assert callable(run)
    assert callable(monitor)
