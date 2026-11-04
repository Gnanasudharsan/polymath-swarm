"""Polymath Swarm: verification-first multi-agent system for research and mathematics."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("polymath")
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
