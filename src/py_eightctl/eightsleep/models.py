from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

DEFAULT_BASE_URL = "https://client-api.8slp.net/v1"
AUTH_URL = "https://auth-api.8slp.net/v1/tokens"
APP_BASE_URL = "https://app-api.8slp.net"
DEFAULT_CLIENT_ID = "0894c7f33bb94800a03f1f4df13a4f38"
DEFAULT_CLIENT_SECRET = "f0954a3ed5763ba3d06834c73731a32f15f168f47d4f164751275def86db0c76"


class Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", use_enum_values=True)


class EmptyRequest(Model):
    pass


class CredentialsInput(Model):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("email is required")
        return trimmed

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value:
            raise ValueError("password is required")
        return value


class StoredConfig(Model):
    email: str | None = None
    password: str | None = None
    user_id: str | None = None
    token: str | None = None
    token_expires_at: datetime | None = None

    @computed_field
    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password)

    @computed_field
    @property
    def has_valid_token(self) -> bool:
        return bool(
            self.token and self.token_expires_at and datetime.now(UTC) < self.token_expires_at
        )


class TokenAuthRequest(Model):
    grant_type: str = "password"
    username: str
    password: str
    client_id: str
    client_secret: str


class TokenAuthResponse(Model):
    access_token: str = Field(alias="access_token")
    expires_in: int = Field(default=3600, alias="expires_in")
    user_id: str | None = Field(default=None, alias="userId")


class UserProfile(Model):
    user_id: str = Field(alias="userId")


class UserProfileResponse(Model):
    user: UserProfile


class CurrentState(Model):
    type: str


class PodStatus(Model):
    current_level: int = Field(alias="currentLevel")
    current_state: CurrentState = Field(alias="currentState")

    @computed_field
    @property
    def is_on(self) -> bool:
        return self.current_state.type != "off"


class SetPowerRequest(Model):
    on: bool


class SetCurrentTemperatureRequest(Model):
    level: int

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: int) -> int:
        if value < -100 or value > 100:
            raise ValueError("level must be between -100 and 100")
        return value


class SmartTemperatureStage(StrEnum):
    BEDTIME = "bedtime"
    NIGHT = "night"
    DAWN = "dawn"


class SmartTemperatureSettings(Model):
    bedtime: int = Field(alias="bedTimeLevel")
    night: int = Field(alias="initialSleepLevel")
    dawn: int = Field(alias="finalSleepLevel")


class SmartTemperatureStatus(PodStatus):
    smart: SmartTemperatureSettings | None = None


class SetSmartTemperatureRequest(SetCurrentTemperatureRequest):
    stage: SmartTemperatureStage


class AlarmState(StrEnum):
    NEXT = "next"
    ENABLED = "enabled"
    DISABLED = "disabled"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"


class Alarm(Model):
    id: str
    enabled: bool
    time: str
    days_of_week: list[int] = Field(default_factory=list)
    vibration: bool
    thermal_enabled: bool = False
    thermal_level: int | None = None
    next: bool = False
    state: AlarmState
    dismissed_until: str = ""
    snoozed_until: str = ""
    one_off: bool = False
    stale: bool = False

    @computed_field
    @property
    def fingerprint(self) -> str:
        material = json.dumps(
            {
                "days_of_week": self.days_of_week,
                "one_off": self.one_off,
                "thermal_enabled": self.thermal_enabled,
                "thermal_level": self.thermal_level,
                "time": self.time,
                "vibration": self.vibration,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.blake2s(material.encode("utf-8"), digest_size=8).hexdigest()


class AlarmList(Model):
    alarms: list[Alarm] = Field(default_factory=list)


class SetAlarmEnabledRequest(Model):
    selector: str
    enabled: bool

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("selector is required")
        return trimmed


class AlarmVibrationSettings(Model):
    enabled: bool = False


class AlarmThermalSettings(Model):
    enabled: bool = False
    level: int | None = None


class AlarmSettings(Model):
    vibration: AlarmVibrationSettings = Field(default_factory=AlarmVibrationSettings)
    thermal: AlarmThermalSettings = Field(default_factory=AlarmThermalSettings)


class TimeWithOffset(Model):
    time: str = ""


class RoutineAlarmEntry(Model):
    alarm_id: str = Field(alias="alarmId")
    enabled_since: str | None = Field(default=None, alias="enabledSince")
    enabled: bool = False
    disabled_individually: bool = Field(default=False, alias="disabledIndividually")
    time: str = ""
    dismissed_until: str = Field(default="", alias="dismissedUntil")
    snoozed_until: str = Field(default="", alias="snoozedUntil")
    time_with_offset: TimeWithOffset = Field(default_factory=TimeWithOffset, alias="timeWithOffset")
    settings: AlarmSettings = Field(default_factory=AlarmSettings)


class RoutineOverride(Model):
    alarms: list[RoutineAlarmEntry] = Field(default_factory=list)


class RoutineAlarmGroup(Model):
    id: str
    days: list[int] = Field(default_factory=list)
    alarms: list[RoutineAlarmEntry] = Field(default_factory=list)
    override: RoutineOverride = Field(default_factory=RoutineOverride)


class RoutineSettings(Model):
    routines: list[RoutineAlarmGroup] = Field(default_factory=list)
    one_off_alarms: list[RoutineAlarmEntry] = Field(default_factory=list, alias="oneOffAlarms")


class NextAlarm(Model):
    alarm_id: str | None = Field(default=None, alias="alarmId")


class RoutineState(Model):
    next_alarm: NextAlarm = Field(default_factory=NextAlarm, alias="nextAlarm")


class RoutinesPayload(Model):
    settings: RoutineSettings
    state: RoutineState = Field(default_factory=RoutineState)


class AlarmMatch(Model):
    alarm: Alarm
    one_off: bool = False
    one_off_index: int | None = None
    routine_index: int | None = None
    routine_alarm_index: int | None = None
    routine_override: bool = False
