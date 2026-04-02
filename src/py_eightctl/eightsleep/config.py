from __future__ import annotations

import json
from pathlib import Path

from py_eightctl.eightsleep.errors import ConfigurationError
from py_eightctl.eightsleep.models import EmptyRequest, StoredConfig

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "py-eightctl" / "config.json"


class ConfigStore:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or DEFAULT_CONFIG_PATH

    def load(self, _: EmptyRequest) -> StoredConfig:
        if not self.config_path.exists():
            return StoredConfig()

        try:
            payload = json.loads(self.config_path.read_text())
        except json.JSONDecodeError as error:
            raise ConfigurationError(f"invalid config file: {self.config_path}") from error

        return StoredConfig.model_validate(payload)

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
