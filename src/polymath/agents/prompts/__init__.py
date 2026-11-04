"""Versioned system prompts, stored as ``<name>.v<N>.md`` files next to this module."""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

_VERSION = re.compile(r"^(?P<name>[a-z_]+)\.v(?P<version>\d+)\.md$")


class PromptNotFoundError(LookupError):
    pass


def available_versions(name: str) -> list[int]:
    versions = []
    for entry in resources.files(__package__).iterdir():
        match = _VERSION.match(entry.name)
        if match and match["name"] == name:
            versions.append(int(match["version"]))
    return sorted(versions)


@cache
def load_prompt(name: str, version: int | None = None) -> str:
    """Load prompt ``name`` at ``version`` (latest if omitted)."""
    versions = available_versions(name)
    if not versions:
        raise PromptNotFoundError(f"no prompt named {name!r}")
    chosen = versions[-1] if version is None else version
    if chosen not in versions:
        raise PromptNotFoundError(f"prompt {name!r} has no version {chosen} (have {versions})")
    return resources.files(__package__).joinpath(f"{name}.v{chosen}.md").read_text("utf-8").strip()
