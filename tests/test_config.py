from pathlib import Path

import httpx

from py_eightctl.eightsleep.config import (
    CONFIG_PATH_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    EMAIL_ENV_VAR,
    PASSWORD_ENV_VAR,
    USERNAME_ENV_VAR,
    ConfigStore,
    resolve_config_path,
)
from py_eightctl.eightsleep.models import EmptyRequest
from py_eightctl.eightsleep.service import EightSleepService


def test_resolve_config_path_prefers_explicit_path(monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, "/tmp/from-env.json")

    resolved = resolve_config_path(Path("/tmp/from-arg.json"))

    assert resolved == Path("/tmp/from-arg.json")


def test_resolve_config_path_uses_env_var_when_non_blank(monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, "~/tmp/py-eightctl.json")

    resolved = resolve_config_path()

    assert resolved == Path("~/tmp/py-eightctl.json").expanduser()


def test_resolve_config_path_ignores_blank_env_var(monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, "   ")

    resolved = resolve_config_path()

    assert resolved == DEFAULT_CONFIG_PATH


def test_load_uses_email_and_password_env_vars(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(EMAIL_ENV_VAR, "env@example.com")
    monkeypatch.setenv(PASSWORD_ENV_VAR, "env-password")

    store = ConfigStore(config_path=tmp_path / "config.json")
    config = store.load(EmptyRequest())

    assert config.email == "env@example.com"
    assert config.password == "env-password"


def test_load_uses_username_env_var_as_email(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(EMAIL_ENV_VAR, raising=False)
    monkeypatch.setenv(USERNAME_ENV_VAR, "username@example.com")

    store = ConfigStore(config_path=tmp_path / "config.json")
    config = store.load(EmptyRequest())

    assert config.email == "username@example.com"


def test_env_creds_override_stored_creds(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """{
  "email": "stored@example.com",
  "password": "stored-password"
}
"""
    )
    monkeypatch.setenv(EMAIL_ENV_VAR, "env@example.com")
    monkeypatch.setenv(PASSWORD_ENV_VAR, "env-password")

    store = ConfigStore(config_path=config_path)
    config = store.load(EmptyRequest())

    assert config.email == "env@example.com"
    assert config.password == "env-password"


def test_post_token_refresh_hook_runs_after_token_is_persisted(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """{
  "email": "user@example.com",
  "password": "secret"
}
"""
    )
    hook_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tokens":
            return httpx.Response(
                200,
                json={
                    "access_token": "fresh-token",
                    "expires_in": 3600,
                    "userId": "uid-123",
                },
            )
        if request.url.path == "/v1/users/me":
            return httpx.Response(
                200,
                json={"user": {"userId": "uid-123"}},
            )
        if request.url.path == "/v1/users/uid-123/temperature":
            return httpx.Response(
                200,
                json={"currentLevel": 5, "currentState": {"type": "on"}},
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def hook() -> None:
        persisted = config_path.read_text()
        assert "fresh-token" in persisted
        hook_calls.append("called")

    service = EightSleepService(
        config_path=config_path,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        post_token_refresh_hook=hook,
    )

    service.get_status(EmptyRequest())

    assert hook_calls == ["called"]


def test_post_token_refresh_hook_does_not_run_when_token_is_reused(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """{
  "email": "user@example.com",
  "password": "secret",
  "user_id": "uid-123",
  "token": "existing-token",
  "token_expires_at": "2099-01-01T00:00:00+00:00"
}
"""
    )
    hook_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/users/uid-123/temperature":
            return httpx.Response(
                200,
                json={"currentLevel": 5, "currentState": {"type": "on"}},
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    service = EightSleepService(
        config_path=config_path,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        post_token_refresh_hook=lambda: hook_calls.append("called"),
    )

    service.get_status(EmptyRequest())

    assert hook_calls == []
