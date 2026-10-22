"""Secret backend for Vault and OpenBao.

Works with zero configuration: it auto-discovers a running Vault or OpenBao from
environment variables. If none is reachable, lookups return defaults or raise
clear errors — no server is ever required just to import the library.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


class BaoError(RuntimeError):
    """Raised when a secret lookup fails."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class BaoSettings:
    """Connection settings.

    OpenBao is detected automatically when ``BOPENBAO_ADDR`` or ``OPENBAO_ADDR``
    is set; otherwise standard ``VAULT_ADDR`` / ``VAULT_TOKEN`` variables are
    used. Both servers share the KV API, so no code paths differ between them.
    """

    addr: str = field(
        default_factory=lambda: _env("OPENBAO_ADDR", _env("VAULT_ADDR", _env("BAO_ADDR")))
    )
    token: str = field(
        default_factory=lambda: _env("OPENBAO_TOKEN", _env("VAULT_TOKEN", _env("BAO_TOKEN")))
    )
    namespace: str = field(
        default_factory=lambda: _env("OPENBAO_NAMESPACE", _env("VAULT_NAMESPACE"))
    )
    role_id: str = field(
        default_factory=lambda: _env("OPENBAO_ROLE_ID", _env("VAULT_ROLE_ID"))
    )
    secret_id: str = field(
        default_factory=lambda: _env("OPENBAO_SECRET_ID", _env("VAULT_SECRET_ID"))
    )
    kv_mount: str = field(
        default_factory=lambda: _env("OPENBAO_KV_MOUNT", _env("VAULT_KV_MOUNT", "secret"))
    )
    kv_version: int = field(
        default_factory=lambda: int(
            _env("OPENBAO_KV_VERSION", _env("VAULT_KV_VERSION", "2")) or 2
        )
    )
    cache_ttl_seconds: float = field(
        default_factory=lambda: float(_env("BAO_CACHE_TTL", "60") or 60)
    )
    # Local fallback map for offline dev/tests. JSON or YAML, path -> {key: value}.
    mock_secrets_path: str = field(
        default_factory=lambda: _env("BAO_MOCK_SECRETS", _env("AICONF_MOCK_SECRETS"))
    )

    @property
    def backend(self) -> str:
        return "openbao" if _env("OPENBAO_ADDR", _env("BOPENBAO_ADDR")) else "vault"


class BaoClient:
    """Read KV secrets from Vault or OpenBao with local caching.

    Usage is identical for both servers::

        client = BaoClient()
        value = client.get("secret/app/db", "password")
        whole = client.read_secret("secret/app/db")
    """

    def __init__(self, settings: BaoSettings | None = None) -> None:
        self.settings = settings or BaoSettings()
        self._client: Any | None = None
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._mock: dict[str, dict[str, Any]] | None = None

        if self.settings.mock_secrets_path:
            self._mock = self._load_mock(self.settings.mock_secrets_path)

    @staticmethod
    def _load_mock(path: str) -> dict[str, dict[str, Any]]:
        import json
        from pathlib import Path

        import yaml

        file_path = Path(path)
        if not file_path.exists():
            return {}
        text = file_path.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        data = yaml.safe_load(text) if path.endswith((".yaml", ".yml")) else json.loads(text)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise BaoError(f"Mock secrets file must be a mapping: {path}")
        return {str(k): dict(v) for k, v in data.items()}

    def _ensure_client(self) -> Any:
        if self._mock is not None:
            return None
        if self._client is not None:
            return self._client

        if not self.settings.addr:
            raise BaoError(
                "No Vault/OpenBao server configured. Set VAULT_ADDR (or OPENBAO_ADDR) "
                "and VAULT_TOKEN (or OPENBAO_TOKEN), or use BAO_MOCK_SECRETS for local mocks."
            )

        import hvac

        client = hvac.Client(url=self.settings.addr, namespace=self.settings.namespace or None)

        if self.settings.token:
            client.token = self.settings.token
        elif self.settings.role_id and self.settings.secret_id:
            client.auth.approle.login(
                role_id=self.settings.role_id,
                secret_id=self.settings.secret_id,
            )
        else:
            raise BaoError("No auth configured. Set VAULT_TOKEN or VAULT_ROLE_ID + VAULT_SECRET_ID.")

        if not client.is_authenticated():
            raise BaoError("Authentication failed.")

        self._client = client
        return client

    @staticmethod
    def _normalize_path(path: str, mount: str, kv_version: int) -> tuple[str, str]:
        """Return (mount, secret_path) for a Vault path."""
        path = path.strip().strip("/")
        mount = mount.strip("/")
        if path.startswith(f"{mount}/"):
            rest = path[len(mount) + 1 :]
            if kv_version == 2 and rest.startswith("data/"):
                rest = rest[5:]
            return mount, rest
        return mount, path

    def read_secret(self, path: str) -> dict[str, Any]:
        """Read all key/value pairs at a KV path."""
        now = time.monotonic()
        cached = self._cache.get(path)
        if cached and (now - cached[0]) < self.settings.cache_ttl_seconds:
            return dict(cached[1])

        if self._mock is not None:
            data = self._mock.get(path) or self._mock.get(path.strip("/"))
            if data is None:
                mount, secret_path = self._normalize_path(
                    path, self.settings.kv_mount, self.settings.kv_version
                )
                data = self._mock.get(secret_path) or self._mock.get(f"{mount}/{secret_path}")
            if data is None:
                raise BaoError(f"Secret not found: {path}")
            self._cache[path] = (now, dict(data))
            return dict(data)

        client = self._ensure_client()
        mount, secret_path = self._normalize_path(
            path, self.settings.kv_mount, self.settings.kv_version
        )

        try:
            if self.settings.kv_version == 2:
                response = client.secrets.kv.v2.read_secret_version(
                    path=secret_path, mount_point=mount
                )
                data = response["data"]["data"]
            else:
                response = client.secrets.kv.v1.read_secret(
                    path=secret_path, mount_point=mount
                )
                data = response["data"]
        except Exception as exc:  # noqa: BLE001
            raise BaoError(f"Failed to read '{path}': {exc}") from exc

        if not isinstance(data, dict):
            raise BaoError(f"Unexpected secret payload at '{path}'")

        self._cache[path] = (now, dict(data))
        return dict(data)

    def get(
        self, path: str, key: str, default: Any = ..., *, required: bool = True
    ) -> Any:
        """Read one key from a secret path.

        ``default=...`` (ellipsis) requires the key. Pass ``required=False`` to
        return None when the key is missing.
        """
        data = self.read_secret(path)
        if key not in data:
            if default is not ...:
                return default
            if not required:
                return None
            raise BaoError(f"Key '{key}' not found at '{path}'")
        return data[key]

    def clear_cache(self) -> None:
        self._cache.clear()
