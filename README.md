# bao_yaml

Drop-in PyYAML replacement with secret substitution from HashiCorp Vault or OpenBao.

## Install

```bash
cd configvault
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

Replace `import yaml` with `import bao_yaml as yaml` — nothing else changes.

```python
import bao_yaml as yaml  # or: import vault_yaml as yaml / openbao_yaml as yaml

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)
```

### Template syntax

Three equivalent ways to reference a secret:

```yaml
# Jinja2 function (most common)
api_key: "{{ vault('secret/app/db', 'api_key') }}"

# YAML tag shortcut
api_key: !vault secret/app/db#api_key

# Jinja2 filter
api_key: "{{ 'secret/app/db#api_key' | vault }}"
```

Any Jinja2 expression works:

```yaml
user: "{{ env.HOME }}/user"
region: "{{ region }}"
```

## Configuration

Set environment variables before importing bao_yaml:

```bash
# HashiCorp Vault
export VAULT_ADDR=https://vault.example.com:8200
export VAULT_TOKEN=hvs.xxxxx

# OpenBao (same API, different env prefix)
export OPENBAO_ADDR=https://openbao.example.com:8200
export OPENBAO_TOKEN=root-token-xxxxx

# Local mock (no server required — for dev/tests)
export BAO_MOCK_SECRETS=/path/to/mock-secrets.yaml
```

Mock file format:

```yaml
secret/app/db:
  password: hunter2
  host: db.internal
secret/app/api:
  api_key: sk-live-123
```

## Testing

```bash
.venv/bin/python -m pytest tests/ -v
```
