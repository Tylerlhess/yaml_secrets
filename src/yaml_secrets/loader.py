"""Drop-in PyYAML-compatible loaders with secret substitution.

Usage is identical to PyYAML::

    import yaml_secrets as yaml
    cfg = yaml.safe_load(open("config.yaml"))

Templates use Jinja2 syntax::

    api_key: "{{ vault('secret/app/db', 'api_key') }}"
    # or the shorter tag form:
    api_key: !vault secret/app/db#api_key
    # or the filter form:
    api_key: "{{ 'secret/app/db#api_key' | vault }}"

Any Jinja2 expression works — ``{{ env.HOME }}``, ``{{ region }}`` — as long as
it is a complete value. Jinja does not split string values, so keep the
template as the whole YAML value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, BinaryIO, IO, TextIO

import yaml as _pyyaml
from jinja2 import Environment, BaseLoader, StrictUndefined, Undefined

from yaml_secrets.vault import SecretClient, SecretError, SecretSettings

__all__ = [
    "SafeLoader",
    "Loader",
    "FullLoader",
    "UnsafeLoader",
    "CSafeLoader",
    "CLoader",
    "CFullLoader",
    "dump",
    "dump_all",
    "safe_dump",
    "safe_dump_all",
    "load",
    "safe_load",
    "load_all",
    "safe_load_all",
]

# Jinja delimiters kept as class attributes so users can rebind them.
BLOCK_START = "{{"
BLOCK_END = "}}"
STATEMENT_START = "{%"
STATEMENT_END = "%}"
COMMENT_START = "{#"
COMMENT_END = "#}"

_VAULT_TAG_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>[^\s:]+)\s*:\s*!vault\s+(?P<ref>\S+)$",
    re.MULTILINE,
)


def _build_env(client: SecretClient, strict: bool = True) -> Environment:
    env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined if strict else Undefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def vault(path: str, key: str | None = None, default: Any = ...) -> Any:
        if key is None:
            return client.read_secret(path)
        return client.get(path, key, default=default)

    def vault_get(path: str) -> dict[str, Any]:
        return client.read_secret(path)

    def vault_filter(path_and_key: str, default: Any = ...) -> Any:
        if "#" not in path_and_key:
            raise SecretError(f"vault filter needs 'path#key', got: {path_and_key!r}")
        path, key = path_and_key.split("#", 1)
        return client.get(path.strip(), key.strip(), default=default)

    env.globals["vault"] = vault
    env.globals["vault_get"] = vault_get
    env.filters["vault"] = vault_filter
    return env


def _expand_vault_tags(text: str) -> str:
    """Rewrite ``key: !vault path#field`` to Jinja before rendering."""

    def repl(match: re.Match[str]) -> str:
        indent = match.group("indent")
        key = match.group("key")
        ref = match.group("ref").strip().strip("'\"")
        if "#" not in ref:
            raise SecretError(f"!vault needs 'path#key', got: {ref!r}")
        path, field = ref.split("#", 1)
        expr = "{{ vault('%s', '%s') }}" % (path.strip(), field.strip())
        return f"{indent}{key}: {expr}"

    return _VAULT_TAG_RE.sub(repl, text)


class _SecretMixin:
    """Mixin that renders Jinja2 + expands !vault tags before handing off to
    the underlying PyYAML loader."""

    strict: bool = True

    def __init__(self, stream: IO[str] | TextIO | BinaryIO | str | os.PathLike[str]) -> None:
        if isinstance(stream, (str, os.PathLike)):
            raw = Path(stream).read_text(encoding="utf-8")
        else:
            raw = stream.read()  # type: ignore[union-attr]

        client = SecretClient()
        env = _build_env(client, strict=self.strict)
        rendered = env.from_string(_expand_vault_tags(raw)).render(env=os.environ)

        import io

        super().__init__(io.StringIO(rendered))


class SafeLoader(_SecretMixin, _pyyaml.SafeLoader):
    """Drop-in replacement for ``yaml.SafeLoader`` with Vault substitution."""

    strict = True


class Loader(_SecretMixin, _pyyaml.Loader):
    strict = True


class FullLoader(_SecretMixin, _pyyaml.FullLoader):
    strict = True


class UnsafeLoader(_SecretMixin, _pyyaml.UnsafeLoader):
    strict = True


# C-Loader variants map to the pure-Python loaders (functionally identical).
CSafeLoader = SafeLoader
CLoader = Loader
CFullLoader = FullLoader


def _load_with(
    LoaderCls: type,
    stream: IO[str] | TextIO | BinaryIO | str | os.PathLike[str],
    Loader: type | None = None,
) -> Any:
    obj = LoaderCls(stream)
    return obj.get_single_data()


def _load_all_with(
    LoaderCls: type,
    stream: IO[str] | TextIO | BinaryIO | str | os.PathLike[str],
    Loader: type | None = None,
):
    obj = LoaderCls(stream)
    return obj.get_data()


def safe_load(stream):
    return _load_with(SafeLoader, stream)


def load(stream, Loader=None):
    return _load_with(Loader or Loader, stream)


def safe_load_all(stream):
    return _load_all_with(SafeLoader, stream)


def load_all(stream, Loader=None):
    return _load_all_with(Loader, stream)


def safe_dump(data, stream=None, **kwargs):
    return _pyyaml.safe_dump(data, stream, **kwargs)


def safe_dump_all(data, stream=None, **kwargs):
    return _pyyaml.safe_dump_all(data, stream, **kwargs)


def dump(data, stream=None, **kwargs):
    return _pyyaml.dump(data, stream, **kwargs)


def dump_all(data, stream=None, **kwargs):
    return _pyyaml.dump_all(data, stream, **kwargs)
