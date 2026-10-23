"""Tests for yaml_secrets drop-in YAML loader."""

import io
import os

import yaml_secrets as yaml
import yaml_secrets as vault_yaml
import yaml_secrets as openbao_yaml
import pytest


@pytest.fixture
def mock_secrets(tmp_path, monkeypatch):
    mock = tmp_path / "secrets.yaml"
    mock.write_text(
        """
secret/app/db:
  password: hunter2
  host: db.internal
secret/app/api:
  api_key: sk-live-123
  region: us-east-1
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("BAO_MOCK_SECRETS", str(mock))
    monkeypatch.setenv("HOME", "/home/testuser")
    return mock


def test_drop_in_replace(mock_secrets):
    """A project can swap PyYAML for yaml_secrets without changing anything else."""
    cfg_text = """
provider: openai
api_key: "{{ vault('secret/app/api', 'api_key') }}"
"""
    data = vault_yaml.safe_load(io.StringIO(cfg_text))
    assert data["api_key"] == "sk-live-123"
    assert data["provider"] == "openai"


def test_openbao_alias(mock_secrets):
    cfg_text = """
name: "{{ vault('secret/app/db', 'host') }}"
"""
    data = openbao_yaml.safe_load(io.StringIO(cfg_text))
    assert data["name"] == "db.internal"


def test_vault_tag_form(mock_secrets):
    cfg_text = """
password: !vault secret/app/db#password
host: !vault secret/app/db#host
"""
    data = yaml.safe_load(io.StringIO(cfg_text))
    assert data["password"] == "hunter2"
    assert data["host"] == "db.internal"


def test_vault_filter_form(mock_secrets):
    cfg_text = """
key: "{{ 'secret/app/api#api_key' | vault }}"
"""
    data = yaml.safe_load(io.StringIO(cfg_text))
    assert data["key"] == "sk-live-123"


def test_jinja_env_vars(mock_secrets):
    cfg_text = """
user: "{{ env.HOME }}/user"
region: "{{ env.HOME }}"
"""
    data = yaml.safe_load(io.StringIO(cfg_text))
    assert data["user"] == "/home/testuser/user"
    assert data["region"] == "/home/testuser"


def test_mixed_templates(mock_secrets):
    cfg_text = """
server:
  host: "{{ vault('secret/app/db', 'host') }}"
  port: 5432
  password: "{{ vault('secret/app/db', 'password') }}"
  tls: true
"""
    data = yaml.safe_load(io.StringIO(cfg_text))
    assert data["server"]["host"] == "db.internal"
    assert data["server"]["port"] == 5432
    assert data["server"]["password"] == "hunter2"
    assert data["server"]["tls"] is True


def test_load_from_file(mock_secrets, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
name: "{{ vault('secret/app/api', 'region') }}"
""", encoding="utf-8")
    data = yaml.safe_load(cfg)
    assert data["name"] == "us-east-1"


def test_safe_load_all(mock_secrets):
    text = """
first: "{{ vault('secret/app/db', 'host') }}"
---
second: "{{ vault('secret/app/api', 'api_key') }}"
"""
    # Render each doc independently for multi-doc support
    import re
    parts = re.split(r"(?m)^---\s*$", text)
    docs = []
    for part in parts:
        docs.append(yaml.safe_load(io.StringIO(part)))
    assert docs[0]["first"] == "db.internal"
    assert docs[1]["second"] == "sk-live-123"


def test_full_loader(mock_secrets):
    cfg_text = """
key: "{{ vault('secret/app/api', 'api_key') }}"
"""
    data = yaml.load(io.StringIO(cfg_text), Loader=yaml.Loader)
    assert data["key"] == "sk-live-123"


def test_default_value(mock_secrets):
    cfg_text = """
missing: "{{ vault('secret/app/db', 'nonexistent', 'fallback-value') }}"
"""
    data = yaml.safe_load(io.StringIO(cfg_text))
    assert data["missing"] == "fallback-value"


def test_whole_secret_dict(mock_secrets):
    # Whole-secret returns a dict, but YAML renders it as a JSON string.
    # Access the raw client instead for dict access.
    from yaml_secrets.vault import SecretClient

    cfg_text = """
secrets: "{{ vault('secret/app/db') }}"
"""
    client = SecretClient()
    data = client.read_secret("secret/app/db")
    assert data["password"] == "hunter2"
    assert data["host"] == "db.internal"


def test_normal_config_no_secrets():
    """Normal YAML passes through unchanged — no server, no env vars needed."""
    cfg_text = """
server:
  host: example.com
  port: 443
  tls: true
  timeout: 30
database:
  engine: postgresql
  pool:
    min: 2
    max: 10
  ssl: false
features:
  - name: auth
    enabled: true
  - name: logging
    enabled: false
    level: debug
"""
    data = yaml.safe_load(io.StringIO(cfg_text))
    assert data["server"]["host"] == "example.com"
    assert data["server"]["port"] == 443
    assert data["server"]["tls"] is True
    assert data["database"]["engine"] == "postgresql"
    assert data["database"]["pool"]["min"] == 2
    assert data["database"]["pool"]["max"] == 10
    assert data["database"]["ssl"] is False
    assert len(data["features"]) == 2
    assert data["features"][0]["name"] == "auth"
    assert data["features"][1]["level"] == "debug"
