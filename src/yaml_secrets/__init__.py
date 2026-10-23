"""yaml_secrets — drop-in YAML with secret substitution from HashiCorp Vault or OpenBao."""

from yaml_secrets.loader import (
    SafeLoader,
    Loader,
    FullLoader,
    UnsafeLoader,
    CSafeLoader,
    CLoader,
    CFullLoader,
    dump,
    dump_all,
    safe_dump,
    safe_dump_all,
    load,
    safe_load,
    load_all,
    safe_load_all,
)
from yaml_secrets.vault import SecretClient, SecretError, SecretSettings

__all__ = [
    "SecretClient",
    "SecretError",
    "SecretSettings",
    "CFullLoader",
    "CLoader",
    "CSafeLoader",
    "FullLoader",
    "Loader",
    "SafeLoader",
    "UnsafeLoader",
    "dump",
    "dump_all",
    "load",
    "load_all",
    "safe_dump",
    "safe_dump_all",
    "safe_load",
    "safe_load_all",
]

__version__ = "0.1.0"
