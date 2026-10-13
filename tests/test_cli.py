def test_cli_commands_import():
    from src.cli.commands.run import run
    from src.cli.commands.doctor import doctor
    from src.cli.commands.config_check import config_check
    assert callable(run)
