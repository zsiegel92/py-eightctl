from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx

from py_eightctl.eightsleep.client import EightSleepClient
from py_eightctl.eightsleep.config import ConfigStore
from py_eightctl.eightsleep.models import (
    Alarm,
    AlarmList,
    CredentialsInput,
    EmptyRequest,
    PodStatus,
    SetAlarmEnabledRequest,
    SetCurrentTemperatureRequest,
    SetPowerRequest,
    SetSmartTemperatureRequest,
    SmartTemperatureStatus,
    StoredConfig,
)

ResultT = TypeVar("ResultT", StoredConfig, PodStatus, SmartTemperatureStatus, AlarmList, Alarm)
TokenRefreshHook = Callable[[], None]


class EightSleepService:
    def __init__(
        self,
        *,
        config_path: Path | None = None,
        http_client: httpx.Client | None = None,
        post_token_refresh_hook: TokenRefreshHook | None = None,
    ) -> None:
        self.store = ConfigStore(config_path=config_path)
        self.http_client = http_client
        self.post_token_refresh_hook = post_token_refresh_hook

    def get_config(self, request: EmptyRequest) -> StoredConfig:
        return self.store.load(request)

    def save_credentials(self, request: CredentialsInput) -> StoredConfig:
        config = self.store.load(EmptyRequest())
        updated = config.model_copy(update=request.model_dump())
        updated.token = None
        updated.token_expires_at = None
        return self.store.save(updated)

    def get_status(self, request: EmptyRequest) -> PodStatus:
        return self._run(lambda client: client.get_status(request))

    def set_power(self, request: SetPowerRequest) -> PodStatus:
        return self._run(lambda client: client.set_power(request))

    def set_current_temperature(self, request: SetCurrentTemperatureRequest) -> PodStatus:
        return self._run(lambda client: client.set_current_temperature(request))

    def get_smart_temperature_status(self, request: EmptyRequest) -> SmartTemperatureStatus:
        return self._run(lambda client: client.get_smart_temperature_status(request))

    def set_smart_temperature(self, request: SetSmartTemperatureRequest) -> SmartTemperatureStatus:
        return self._run(lambda client: client.set_smart_temperature(request))

    def list_alarms(self, request: EmptyRequest) -> AlarmList:
        return self._run(lambda client: client.list_alarms(request))

    def set_alarm_enabled(self, request: SetAlarmEnabledRequest) -> Alarm:
        return self._run(lambda client: client.set_alarm_enabled(request))

    def _run(self, action: Callable[[EightSleepClient], ResultT]) -> ResultT:
        config = self.store.load(EmptyRequest())
        client = EightSleepClient(config, http_client=self.http_client)
        result = action(client)
        updated_config = client.export_config()
        self.store.save(updated_config)
        if (
            self._token_was_refreshed(config, updated_config)
            and self.post_token_refresh_hook is not None
        ):
            self.post_token_refresh_hook()
        return result

    def _token_was_refreshed(self, before: StoredConfig, after: StoredConfig) -> bool:
        if after.token is None or after.token_expires_at is None:
            return False
        return before.token != after.token or before.token_expires_at != after.token_expires_at
