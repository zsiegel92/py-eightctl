from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

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


def _client_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
) -> EightSleepClient:
    return EightSleepClient(
        StoredConfig(
            email="user@example.com",
            password="secret",
            user_id="uid-123",
            token="token",
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _one_off_alarm(
    alarm_id: str,
    time: str,
    *,
    enabled: bool,
    dismissed_until: str = "1970-01-01T00:00:00Z",
    snoozed_until: str = "1970-01-01T00:00:00Z",
) -> dict[str, Any]:
    return {
        "alarmId": alarm_id,
        "time": time,
        "enabled": enabled,
        "settings": {
            "vibration": {"enabled": False, "pattern": "INTENSE", "powerLevel": 50},
            "thermal": {"enabled": True, "level": 50},
        },
        "dismissedUntil": dismissed_until,
        "snoozedUntil": snoozed_until,
    }


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


def test_refetch_alarm_by_fingerprint_when_id_changes() -> None:
    enabled = True

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal enabled
        if request.url.path == "/v2/users/uid-123/routines" and request.method == "GET":
            alarm_id = "alarm-1" if enabled else "alarm-2"
            return httpx.Response(
                200,
                json={
                    "settings": {
                        "routines": [],
                        "oneOffAlarms": [
                            {
                                "alarmId": alarm_id,
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

    assert alarm.id == "alarm-2"
    assert alarm.enabled is False
    assert len(alarm.fingerprint) == 16


def test_list_alarms_interprets_one_off_alarm_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/users/uid-123/routines":
            return httpx.Response(
                200,
                json={
                    "settings": {
                        "routines": [],
                        "oneOffAlarms": [
                            _one_off_alarm("next", "06:40:00", enabled=True),
                            _one_off_alarm("later", "07:30:00", enabled=True),
                            _one_off_alarm(
                                "dismissed",
                                "07:10:00",
                                enabled=True,
                                dismissed_until="2026-06-12T11:10:00Z",
                            ),
                            _one_off_alarm("off", "08:20:00", enabled=False),
                        ],
                    },
                    "state": {"nextAlarm": {"alarmId": "next"}},
                },
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = _client_with_handler(handler)

    alarms = client.list_alarms(EmptyRequest())

    assert [(alarm.id, alarm.enabled, alarm.state) for alarm in alarms.alarms] == [
        ("next", True, "next"),
        ("later", True, "enabled"),
        ("dismissed", False, "disabled"),
        ("off", False, "disabled"),
    ]


def test_list_alarms_disables_one_off_alarms_when_no_next_alarm_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/users/uid-123/routines":
            return httpx.Response(
                200,
                json={
                    "settings": {
                        "routines": [],
                        "oneOffAlarms": [_one_off_alarm("old", "06:40:00", enabled=True)],
                    },
                    "state": {"status": {}},
                },
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    alarms = _client_with_handler(handler).list_alarms(EmptyRequest())

    assert len(alarms.alarms) == 1
    assert alarms.alarms[0].enabled is False


def test_enable_one_off_alarm_clears_delivery_state() -> None:
    put_body: dict[str, Any] = {}
    current_alarm = _one_off_alarm(
        "alarm-1",
        "07:15:00",
        enabled=False,
        dismissed_until="2026-06-12T11:10:00Z",
        snoozed_until="2026-06-12T11:20:00Z",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal current_alarm
        if request.url.path == "/v2/users/uid-123/routines" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "settings": {"routines": [], "oneOffAlarms": [current_alarm]},
                    "state": {"nextAlarm": {"alarmId": "alarm-1"}},
                },
            )
        if request.url.path == "/v2/users/uid-123/routines" and request.method == "PUT":
            put_body.update(json.loads(request.content.decode()))
            current_alarm = put_body["oneOffAlarms"][0]
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    alarm = _client_with_handler(handler).set_alarm_enabled(
        SetAlarmEnabledRequest(selector="07:15", enabled=True)
    )

    assert current_alarm["enabled"] is True
    assert current_alarm["dismissedUntil"] == "1970-01-01T00:00:00Z"
    assert current_alarm["snoozedUntil"] == "1970-01-01T00:00:00Z"
    assert alarm.enabled is True


def test_alarm_vibration_test_uses_user_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "app-api.8slp.net"
        if request.url.path == "/v1/users/uid-123/vibration-test":
            assert request.method == "POST"
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

    result = client.alarm_vibration_test(EmptyRequest())

    assert result.ok is True


def test_list_alarms_marks_vibration_test_alarm() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/users/uid-123/routines":
            return httpx.Response(
                200,
                json={
                    "settings": {
                        "routines": [],
                        "oneOffAlarms": [
                            {
                                "alarmId": "alarm-test",
                                "time": "18:33:27",
                                "enabled": True,
                                "settings": {
                                    "vibration": {
                                        "enabled": True,
                                        "powerLevel": 100,
                                        "pattern": "TESTDRIVE",
                                    },
                                    "thermal": {"enabled": False, "level": 0},
                                },
                                "dismissedUntil": "1970-01-01T00:00:00Z",
                                "snoozedUntil": "1970-01-01T00:00:00Z",
                            }
                        ],
                    },
                    "state": {"nextAlarm": {"alarmId": "alarm-test"}},
                },
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

    alarms = client.list_alarms(EmptyRequest())

    assert len(alarms.alarms) == 1
    assert alarms.alarms[0].is_vibration_test is True
    assert alarms.alarms[0].vibration_pattern == "TESTDRIVE"
