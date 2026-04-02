class EightSleepError(Exception):
    """Base error for the Eight Sleep integration module."""


class ConfigurationError(EightSleepError):
    """Raised when required local configuration is missing or invalid."""


class ApiError(EightSleepError):
    """Raised when an Eight Sleep API call fails."""


class ResponseError(EightSleepError):
    """Raised when an API response is missing required data."""
