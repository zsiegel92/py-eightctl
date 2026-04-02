from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx

from py_eightctl.eightsleep.client import EightSleepClient
from py_eightctl.eightsleep.models import (
    EmptyRequest,
    SetAlarmEnabledRequest,
    SetPowerRequest,
    SetSmartTemperatureRequest,
    SmartTemperatureStage,
    StoredConfig,
)


def test_get_status_populates_user_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/users/me":
            return httpx.Response(
                200,
                json={"user": {"userId": "uid-123", "currentDevice": {"id": "dev-1"}}},
            )
        if request.url.path == "/v1/users/uid-123/temperature":
            return httpx.Response(
                200,
                json={"currentLevel": 5, "currentState": {"type": "on"}},
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = EightSleepClient(
        StoredConfig(
            email="user@example.com",
            password="secret",
            token="token",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    status = client.get_status(EmptyRequest())

    assert client.export_config().user_id == "uid-123"
    assert status.current_level == 5
    assert status.current_state.type == "on"


def test_set_power_uses_app_temperature_endpoint() -> None:
    power_states: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/users/me":
            return httpx.Response(200, json={"user": {"userId": "uid-123"}})
        if request.url.path == "/v1/users/uid-123/temperature" and request.method == "PUT":
            payload = json.loads(request.content.decode())
            power_states.append(payload["currentState"]["type"])
            return httpx.Response(204)
        if request.url.path == "/v1/users/uid-123/temperature" and request.method == "GET":
            return httpx.Response(
                200,
                json={"currentLevel": 5, "currentState": {"type": "smart:initial"}, "smart": None},
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = EightSleepClient(
        StoredConfig(
            email="user@example.com",
            password="secret",
            user_id="uid-123",
            token="token",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.set_power(SetPowerRequest(on=True))
    client.set_power(SetPowerRequest(on=False))

    assert power_states == ["smart", "off"]


def test_set_smart_temperature_preserves_other_stages() -> None:
    put_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/users/uid-123/temperature" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "currentLevel": 5,
                    "currentState": {"type": "smart:bedtime"},
                    "smart": {
                        "bedTimeLevel": 10,
                        "initialSleepLevel": -20,
                        "finalSleepLevel": 0,
                    },
                },
            )
        if request.url.path == "/v1/users/uid-123/temperature" and request.method == "PUT":
            put_body.update(json.loads(request.content.decode()))
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = EightSleepClient(
        StoredConfig(
            email="user@example.com",
            password="secret",
            user_id="uid-123",
            token="token",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    status = client.set_smart_temperature(
        SetSmartTemperatureRequest(stage=SmartTemperatureStage.NIGHT, level=-30)
    )

    assert status.smart is not None
    assert status.smart.night == -30
    assert put_body == {
        "smart": {
            "bedTimeLevel": 10,
            "initialSleepLevel": -30,
            "finalSleepLevel": 0,
        }
    }


def test_disable_one_off_alarm_updates_routines_endpoint() -> None:
    enabled = True

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal enabled
        if request.url.path == "/v2/users/uid-123/routines" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "settings": {
                        "routines": [],
                        "oneOffAlarms": [
                            {
                                "alarmId": "alarm-1",
                                "time": "07:15:00",
                                "enabled": enabled,
                                "settings": {
                                    "vibration": {"enabled": False},
                                    "thermal": {"enabled": True, "level": 40},
                                },
                                "dismissedUntil": "1970-01-01T00:00:00Z",
                                "snoozedUntil": "1970-01-01T00:00:00Z",
                            }
                        ],
                    },
                    "state": {"nextAlarm": {}},
                },
            )
        if request.url.path == "/v2/users/uid-123/routines" and request.method == "PUT":
            assert request.url.params.get("ignoreDeviceErrors") == "false"
            payload = json.loads(request.content.decode())
            enabled = payload["oneOffAlarms"][0]["enabled"]
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = EightSleepClient(
        StoredConfig(
            email="user@example.com",
            password="secret",
            user_id="uid-123",
            token="token",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    alarm = client.set_alarm_enabled(SetAlarmEnabledRequest(selector="07:15", enabled=False))

    assert enabled is False
    assert alarm.enabled is False
