from __future__ import annotations

from py_eightctl.eightsleep.errors import ConfigurationError
from py_eightctl.eightsleep.models import Model


class ParsedTemperature(Model):
    level: int


def parse_temperature_input(value: str) -> ParsedTemperature:
    normalized = value.strip().upper()
    if not normalized:
        raise ConfigurationError("temperature is required")

    if normalized.endswith("F"):
        return ParsedTemperature(level=_map_fahrenheit_to_level(float(normalized[:-1])))
    if normalized.endswith("C"):
        return ParsedTemperature(level=_map_celsius_to_level(float(normalized[:-1])))

    try:
        return ParsedTemperature(level=int(normalized))
    except ValueError as error:
        raise ConfigurationError("temperature must be a raw level or end with F/C") from error


def _map_fahrenheit_to_level(value: float) -> int:
    scaled = (value - 55.0) / (100.0 - 55.0) * 200.0 - 100.0
    return int(max(-100.0, min(100.0, scaled)))


def _map_celsius_to_level(value: float) -> int:
    scaled = (value - 13.0) / (38.0 - 13.0) * 200.0 - 100.0
    return int(max(-100.0, min(100.0, scaled)))
