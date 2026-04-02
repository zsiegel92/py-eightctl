from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TypeVar, overload
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel

from py_eightctl.eightsleep.errors import ApiError, ConfigurationError, ResponseError
from py_eightctl.eightsleep.models import (
    Alarm,
    AlarmList,
    AlarmMatch,
    AlarmState,
    CredentialsInput,
    EmptyRequest,
    LegacyLoginRequest,
    LegacyLoginResponse,
    PodStatus,
    RoutineAlarmEntry,
    RoutinesPayload,
    SetAlarmEnabledRequest,
    SetCurrentTemperatureRequest,
    SetPowerRequest,
    SetSmartTemperatureRequest,
    SmartTemperatureSettings,
    SmartTemperatureStage,
    SmartTemperatureStatus,
    StoredConfig,
    TokenAuthRequest,
    TokenAuthResponse,
    UserProfileResponse,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
JsonMapping = Mapping[str, object]


class EightSleepClient:
    def __init__(
        self,
        config: StoredConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config.model_copy(deep=True)
        self.http = http_client or httpx.Client(timeout=20.0, follow_redirects=False)

    def export_config(self) -> StoredConfig:
        return self.config

    def get_status(self, _: EmptyRequest) -> PodStatus:
        user_id = self._require_user_id()
        return self._request_model(
            "GET",
            f"/users/{user_id}/temperature",
            response_model=PodStatus,
        )

    def set_power(self, request: SetPowerRequest) -> PodStatus:
        user_id = self._require_user_id()
        state_type = "smart" if request.on else "off"
        self._request(
            "PUT",
            f"/v1/users/{user_id}/temperature",
            body={"currentState": {"type": state_type}},
            use_app_base_url=True,
        )
        return self.get_smart_temperature_status(EmptyRequest())

    def set_current_temperature(self, request: SetCurrentTemperatureRequest) -> PodStatus:
        user_id = self._require_user_id()
        self._request(
            "PUT",
            f"/users/{user_id}/temperature",
            body={"currentLevel": request.level},
        )
        return self.get_status(EmptyRequest())

    def get_smart_temperature_status(self, _: EmptyRequest) -> SmartTemperatureStatus:
        user_id = self._require_user_id()
        return self._request_model(
            "GET",
            f"/v1/users/{user_id}/temperature",
            response_model=SmartTemperatureStatus,
            use_app_base_url=True,
        )

    def set_smart_temperature(self, request: SetSmartTemperatureRequest) -> SmartTemperatureStatus:
        user_id = self._require_user_id()
        status = self.get_smart_temperature_status(EmptyRequest())
        if status.smart is None:
            raise ResponseError("smart temperature settings not present in response")

        if request.stage == SmartTemperatureStage.BEDTIME:
            smart_payload = {
                "bedTimeLevel": request.level,
                "initialSleepLevel": status.smart.night,
                "finalSleepLevel": status.smart.dawn,
            }
        elif request.stage == SmartTemperatureStage.NIGHT:
            smart_payload = {
                "bedTimeLevel": status.smart.bedtime,
                "initialSleepLevel": request.level,
                "finalSleepLevel": status.smart.dawn,
            }
        else:
            smart_payload = {
                "bedTimeLevel": status.smart.bedtime,
                "initialSleepLevel": status.smart.night,
                "finalSleepLevel": request.level,
            }
        smart = SmartTemperatureSettings.model_validate(smart_payload)

        self._request(
            "PUT",
            f"/v1/users/{user_id}/temperature",
            body={"smart": smart.model_dump(mode="json", by_alias=True)},
            use_app_base_url=True,
        )
        return status.model_copy(update={"smart": smart})

    def list_alarms(self, _: EmptyRequest) -> AlarmList:
        payload = self._fetch_routines_payload()
        return AlarmList(alarms=self._alarms_from_payload(payload))

    def set_alarm_enabled(self, request: SetAlarmEnabledRequest) -> Alarm:
        payload = self._fetch_routines_payload()
        match = self._resolve_alarm_selector(payload, request.selector)

        if match.one_off:
            if match.one_off_index is None:
                raise ResponseError("one-off alarm match missing index")
            entry = payload.settings.one_off_alarms[match.one_off_index]
            entry.enabled = request.enabled
            if request.enabled and not entry.enabled_since:
                entry.enabled_since = datetime.now(UTC).isoformat()
            body = {
                "oneOffAlarms": [
                    alarm.model_dump(mode="json", by_alias=True)
                    for alarm in payload.settings.one_off_alarms
                ]
            }
        else:
            if match.routine_index is None or match.routine_alarm_index is None:
                raise ResponseError("routine alarm match missing indices")
            group = payload.settings.routines[match.routine_index]
            alarms = group.override.alarms if match.routine_override else group.alarms
            entry = alarms[match.routine_alarm_index]
            entry.disabled_individually = not request.enabled
            if request.enabled and not entry.enabled_since:
                entry.enabled_since = datetime.now(UTC).isoformat()
            body = {
                "routines": [
                    routine.model_dump(mode="json", by_alias=True)
                    for routine in payload.settings.routines
                ]
            }

        user_id = self._require_user_id()
        self._request(
            "PUT",
            f"/v2/users/{user_id}/routines",
            body=body,
            query={"ignoreDeviceErrors": "false"},
            use_app_base_url=True,
        )

        updated = self.list_alarms(EmptyRequest())
        for alarm in updated.alarms:
            if alarm.id == match.alarm.id:
                return alarm
        raise ResponseError(f"updated alarm {match.alarm.id}, but could not refetch it")

    def _fetch_routines_payload(self) -> RoutinesPayload:
        user_id = self._require_user_id()
        return self._request_model(
            "GET",
            f"/v2/users/{user_id}/routines",
            response_model=RoutinesPayload,
            use_app_base_url=True,
        )

    def _require_user_id(self) -> str:
        if self.config.user_id:
            return self.config.user_id

        profile = self._request_model("GET", "/users/me", response_model=UserProfileResponse)
        self.config.user_id = profile.user.user_id
        return self.config.user_id

    @overload
    def _request_model(
        self,
        method: str,
        path: str,
        *,
        body: JsonMapping | None = None,
        response_model: type[ModelT],
        query: dict[str, str] | None = None,
        use_app_base_url: bool = False,
    ) -> ModelT: ...

    @overload
    def _request_model(
        self,
        method: str,
        path: str,
        *,
        body: JsonMapping | None = None,
        response_model: None = None,
        query: dict[str, str] | None = None,
        use_app_base_url: bool = False,
    ) -> None: ...

    def _request_model(
        self,
        method: str,
        path: str,
        *,
        body: JsonMapping | None = None,
        response_model: type[ModelT] | None = None,
        query: dict[str, str] | None = None,
        use_app_base_url: bool = False,
    ) -> ModelT | None:
        response = self._request(
            method,
            path,
            body=body,
            query=query,
            use_app_base_url=use_app_base_url,
        )
        if response_model is None:
            return None
        return response_model.model_validate(response.json())

    def _ensure_token(self) -> None:
        if self.config.has_valid_token:
            return
        if not self.config.has_credentials:
            raise ConfigurationError("missing stored email/password")

        credentials = CredentialsInput(
            email=self.config.email or "",
            password=self.config.password or "",
        )
        token_request = TokenAuthRequest(
            username=credentials.email,
            password=credentials.password,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
        )

        try:
            response = self._raw_request(
                "POST",
                self.config.auth_url,
                body=token_request.model_dump(mode="json"),
                content_type="application/x-www-form-urlencoded",
                use_form_encoding=True,
                needs_auth=False,
            )
            parsed = TokenAuthResponse.model_validate(response.json())
            self.config.token = parsed.access_token
            self.config.token_expires_at = datetime.now(UTC) + timedelta(
                seconds=max(parsed.expires_in - 60, 0)
            )
            if parsed.user_id and not self.config.user_id:
                self.config.user_id = parsed.user_id
            return
        except ApiError:
            pass

        legacy = LegacyLoginRequest(email=credentials.email, password=credentials.password)
        response = self._raw_request(
            "POST",
            urljoin(self.config.base_url.rstrip("/") + "/", "login"),
            body=legacy.model_dump(mode="json"),
            needs_auth=False,
        )
        parsed = LegacyLoginResponse.model_validate(response.json())
        self.config.token = parsed.session.token
        if parsed.session.expiration_date:
            self.config.token_expires_at = datetime.fromisoformat(
                parsed.session.expiration_date.replace("Z", "+00:00")
            )
        else:
            self.config.token_expires_at = datetime.now(UTC) + timedelta(hours=12)
        if parsed.session.user_id and not self.config.user_id:
            self.config.user_id = parsed.session.user_id

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: JsonMapping | None = None,
        query: dict[str, str] | None = None,
        use_app_base_url: bool = False,
    ) -> httpx.Response:
        base_url = self.config.app_base_url if use_app_base_url else self.config.base_url
        return self._raw_request(
            method,
            urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
            body=body,
            query=query,
            needs_auth=True,
        )

    def _raw_request(
        self,
        method: str,
        url: str,
        *,
        body: JsonMapping | None = None,
        query: dict[str, str] | None = None,
        content_type: str = "application/json; charset=UTF-8",
        use_form_encoding: bool = False,
        needs_auth: bool,
        retries_left: int = 3,
    ) -> httpx.Response:
        if needs_auth:
            self._ensure_token()

        headers = {
            "Accept": "application/json",
            "Connection": "keep-alive",
            "User-Agent": "okhttp/4.9.3",
            "Content-Type": content_type,
        }
        if needs_auth and self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"

        if use_form_encoding:
            response = self.http.request(
                method,
                url,
                params=query,
                headers=headers,
                data=body,
            )
        else:
            response = self.http.request(
                method,
                url,
                params=query,
                headers=headers,
                json=body,
            )
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            if retries_left <= 0:
                raise ApiError(f"rate limited calling {method} {url}")
            time.sleep(2.0)
            return self._raw_request(
                method,
                url,
                body=body,
                query=query,
                content_type=content_type,
                use_form_encoding=use_form_encoding,
                needs_auth=needs_auth,
                retries_left=retries_left - 1,
            )
        if response.status_code == httpx.codes.UNAUTHORIZED and needs_auth:
            if retries_left <= 0:
                raise ApiError(f"unauthorized calling {method} {url}")
            self.config.token = None
            self.config.token_expires_at = None
            return self._raw_request(
                method,
                url,
                body=body,
                query=query,
                content_type=content_type,
                use_form_encoding=use_form_encoding,
                needs_auth=needs_auth,
                retries_left=retries_left - 1,
            )
        if response.status_code >= 300:
            raise ApiError(f"api {method} {url}: {response.text}")
        return response

    def _alarms_from_payload(self, payload: RoutinesPayload) -> list[Alarm]:
        next_alarm_id = payload.state.next_alarm.alarm_id
        alarms: list[Alarm] = []

        for routine in payload.settings.routines:
            for entry in routine.alarms:
                alarms.append(
                    self._build_alarm(
                        entry=entry,
                        days=list(routine.days),
                        next_alarm_id=next_alarm_id,
                        one_off=False,
                    )
                )
            for entry in routine.override.alarms:
                alarms.append(
                    self._build_alarm(
                        entry=entry,
                        days=list(routine.days),
                        next_alarm_id=next_alarm_id,
                        one_off=False,
                    )
                )
        for entry in payload.settings.one_off_alarms:
            alarms.append(
                self._build_alarm(entry=entry, days=[], next_alarm_id=next_alarm_id, one_off=True)
            )

        return sorted(
            alarms,
            key=lambda alarm: (self._alarm_order_weight(alarm), alarm.time, alarm.id),
        )

    def _build_alarm(
        self,
        *,
        entry: RoutineAlarmEntry,
        days: list[int],
        next_alarm_id: str | None,
        one_off: bool,
    ) -> Alarm:
        time_value = entry.time or entry.time_with_offset.time
        enabled = entry.enabled if one_off else not entry.disabled_individually
        dismissed_until = self._normalize_alarm_timestamp(entry.dismissed_until)
        snoozed_until = self._normalize_alarm_timestamp(entry.snoozed_until)
        next_alarm = entry.alarm_id == next_alarm_id

        alarm = Alarm(
            id=entry.alarm_id,
            enabled=enabled,
            time=time_value,
            days_of_week=days,
            vibration=entry.settings.vibration.enabled,
            next=next_alarm,
            state=AlarmState.ENABLED,
            dismissed_until=dismissed_until,
            snoozed_until=snoozed_until,
            one_off=one_off,
            stale=self._is_stale_past_one_off(
                one_off, enabled, next_alarm, dismissed_until, snoozed_until
            ),
        )
        return alarm.model_copy(update={"state": self._alarm_state(alarm)})

    def _resolve_alarm_selector(self, payload: RoutinesPayload, selector: str) -> AlarmMatch:
        candidates = self._build_alarm_matches(payload)
        if selector == "next":
            next_alarm_id = payload.state.next_alarm.alarm_id
            if not next_alarm_id:
                raise ResponseError("no next alarm found")
            for candidate in candidates:
                if candidate.alarm.id == next_alarm_id:
                    return candidate
            raise ResponseError(f"next alarm {next_alarm_id} not found")

        for candidate in candidates:
            if candidate.alarm.id == selector:
                return candidate

        normalized_selector = self._normalize_alarm_time(selector)
        if normalized_selector is None:
            raise ConfigurationError(
                "selector must be 'next', an exact HH:MM[:SS], or a full alarm id"
            )

        matches = [
            candidate
            for candidate in candidates
            if self._normalize_alarm_time(candidate.alarm.time) == normalized_selector
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ResponseError(f"selector {selector!r} matched multiple alarms; use the full id")
        raise ResponseError(f"no alarm matched selector {selector!r}")

    def _build_alarm_matches(self, payload: RoutinesPayload) -> list[AlarmMatch]:
        next_alarm_id = payload.state.next_alarm.alarm_id
        matches: list[AlarmMatch] = []

        for routine_index, routine in enumerate(payload.settings.routines):
            for alarm_index, entry in enumerate(routine.alarms):
                matches.append(
                    AlarmMatch(
                        alarm=self._build_alarm(
                            entry=entry,
                            days=list(routine.days),
                            next_alarm_id=next_alarm_id,
                            one_off=False,
                        ),
                        routine_index=routine_index,
                        routine_alarm_index=alarm_index,
                    )
                )
            for alarm_index, entry in enumerate(routine.override.alarms):
                matches.append(
                    AlarmMatch(
                        alarm=self._build_alarm(
                            entry=entry,
                            days=list(routine.days),
                            next_alarm_id=next_alarm_id,
                            one_off=False,
                        ),
                        routine_index=routine_index,
                        routine_alarm_index=alarm_index,
                        routine_override=True,
                    )
                )
        for one_off_index, entry in enumerate(payload.settings.one_off_alarms):
            matches.append(
                AlarmMatch(
                    alarm=self._build_alarm(
                        entry=entry,
                        days=[],
                        next_alarm_id=next_alarm_id,
                        one_off=True,
                    ),
                    one_off=True,
                    one_off_index=one_off_index,
                )
            )
        return matches

    def _alarm_state(self, alarm: Alarm) -> AlarmState:
        if alarm.next:
            return AlarmState.NEXT
        if not alarm.enabled:
            return AlarmState.DISABLED
        if alarm.snoozed_until:
            return AlarmState.SNOOZED
        if alarm.dismissed_until:
            return AlarmState.DISMISSED
        return AlarmState.ENABLED

    def _normalize_alarm_timestamp(self, timestamp: str) -> str:
        parsed = self._parse_timestamp(timestamp)
        if parsed is None or parsed.year == 1970:
            return ""
        return parsed.isoformat()

    def _parse_timestamp(self, timestamp: str) -> datetime | None:
        if not timestamp:
            return None
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _is_stale_past_one_off(
        self,
        one_off: bool,
        enabled: bool,
        next_alarm: bool,
        dismissed_until: str,
        snoozed_until: str,
    ) -> bool:
        if not one_off or next_alarm or not enabled:
            return False
        now = datetime.now(UTC)
        for timestamp in (dismissed_until, snoozed_until):
            parsed = self._parse_timestamp(timestamp)
            if parsed is not None and parsed <= now:
                return True
        return False

    def _alarm_order_weight(self, alarm: Alarm) -> int:
        if alarm.state == AlarmState.NEXT:
            return 0
        if alarm.state in {AlarmState.ENABLED, AlarmState.SNOOZED}:
            return 1
        if alarm.state == AlarmState.DISABLED:
            return 2
        if alarm.state == AlarmState.DISMISSED:
            return 3
        return 4

    def _normalize_alarm_time(self, value: str) -> str | None:
        trimmed = value.strip()
        if trimmed.count(":") == 1:
            return f"{trimmed}:00"
        if trimmed.count(":") == 2:
            return trimmed
        return None
