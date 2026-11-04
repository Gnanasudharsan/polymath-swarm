"""Command-line entry point (`polymath ...`)."""

import typer

from polymath import __version__

app = typer.Typer(
    name="polymath",
    help="Polymath Swarm: verification-first multi-agent research & math solver.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Polymath Swarm CLI."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
