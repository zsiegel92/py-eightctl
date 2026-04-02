from __future__ import annotations

import json
import os
from pathlib import Path

from py_eightctl.eightsleep.errors import ConfigurationError
from py_eightctl.eightsleep.models import EmptyRequest, StoredConfig

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "py-eightctl" / "config.json"
CONFIG_PATH_ENV_VAR = "PY_EIGHTCTL_CONFIG_PATH"
EMAIL_ENV_VAR = "PY_EIGHTCTL_EMAIL"
PASSWORD_ENV_VAR = "PY_EIGHTCTL_PASSWORD"


def resolve_config_path(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return config_path

    env_value = os.environ.get(CONFIG_PATH_ENV_VAR, "").strip()
    if env_value:
        return Path(env_value).expanduser()

    return DEFAULT_CONFIG_PATH


def _get_env_value(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def apply_env_overrides(config: StoredConfig) -> StoredConfig:
    email = _get_env_value(EMAIL_ENV_VAR)
    password = _get_env_value(PASSWORD_ENV_VAR)

    updates: dict[str, str] = {}
    if email is not None:
        updates["email"] = email
    if password is not None:
        updates["password"] = password

    if not updates:
        return config
    return config.model_copy(update=updates)


class ConfigStore:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = resolve_config_path(config_path)

    def load(self, _: EmptyRequest) -> StoredConfig:
        if not self.config_path.exists():
            return apply_env_overrides(StoredConfig())

        try:
            payload = json.loads(self.config_path.read_text())
        except json.JSONDecodeError as error:
            raise ConfigurationError(f"invalid config file: {self.config_path}") from error

        return apply_env_overrides(StoredConfig.model_validate(payload))

    def save(self, config: StoredConfig) -> StoredConfig:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            config.model_dump_json(
                indent=2,
                exclude_none=True,
                exclude_computed_fields=True,
            )
        )
        self.config_path.chmod(0o600)
        return config
