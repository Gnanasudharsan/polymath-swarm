"""Bootstrap smoke tests: the package imports and the CLI runs."""

from typer.testing import CliRunner

import polymath
from polymath.cli import app


def test_package_has_version() -> None:
    assert isinstance(polymath.__version__, str)
    assert polymath.__version__


def test_cli_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == polymath.__version__
