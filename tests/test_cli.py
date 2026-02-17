from typer.testing import CliRunner

from pupil_labs.deck.cli import main

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "render" in result.stdout
    assert "tui" in result.stdout


def test_render_no_recordings():
    result = runner.invoke(main, ["render", "non_existent_dir"])
    assert result.exit_code == 1
