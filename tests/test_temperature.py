from py_eightctl.eightsleep.errors import ConfigurationError
from py_eightctl.eightsleep.temperature import parse_temperature_input


def test_parse_raw_temperature_level() -> None:
    parsed = parse_temperature_input("-20")
    assert parsed.level == -20


def test_parse_fahrenheit_temperature() -> None:
    parsed = parse_temperature_input("68F")
    assert parsed.level == -42


def test_parse_invalid_temperature() -> None:
    try:
        parse_temperature_input("warm")
    except ConfigurationError:
        pass
    else:
        raise AssertionError("expected invalid temperature to fail")
