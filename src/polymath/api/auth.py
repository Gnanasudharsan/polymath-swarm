"""API users: named keys (stored as SHA-256 hashes), admin flag, run ownership checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from polymath.core.config import Settings

LEGACY_USER = "admin"
SCOPE_KEY = "polymath.principal"  # where middleware leaves the caller in the ASGI scope


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    user: str
    admin: bool = False

    def can_see(self, owner: str | None) -> bool:
        """Admins see every run; other users only their own. Runs without an owner (created
        before users existed) are admin-only."""
        return self.admin or (owner is not None and owner == self.user)


def hash_key(key: str) -> str:
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return "pm_" + secrets.token_urlsafe(32)


class KeyRing:
    """Maps presented keys to users. Keys are compared as hashes, in constant time, and every
    entry is checked (no early exit) so timing does not reveal which user matched."""

    def __init__(self, hashes: Mapping[str, str], admins: set[str]) -> None:
        for user, h in hashes.items():
            if not h.startswith("sha256:") or len(h) != 71:
                raise ValueError(f"API key hash for {user!r} must be 'sha256:<64 hex chars>'")
        self._hashes = dict(hashes)
        self._admins = admins

    @classmethod
    def from_settings(cls, settings: Settings) -> KeyRing:
        hashes = {u: h.get_secret_value() for u, h in settings.api_users.items()}
        if settings.api_key:
            hashes.setdefault(LEGACY_USER, hash_key(settings.api_key.get_secret_value()))
        return cls(hashes, set(settings.api_admins))

    def __bool__(self) -> bool:
        return bool(self._hashes)

    @property
    def users(self) -> list[str]:
        return sorted(self._hashes)

    def authenticate(self, key: str | None) -> Principal | None:
        if not key:
            return None
        presented = hash_key(key)
        found: str | None = None
        for user, h in self._hashes.items():
            if hmac.compare_digest(presented, h):
                found = user
        if found is None:
            return None
        return Principal(user=found, admin=found in self._admins)
