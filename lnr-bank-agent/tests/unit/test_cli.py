from typer.testing import CliRunner

from lnrbank.cli import app

runner = CliRunner()


def test_help_lists_commands():
    out = runner.invoke(app, ["--help"]).output
    for cmd in ("check", "run", "build", "notify"):
        assert cmd in out


def test_unimplemented_command_exits_nonzero():
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 2
