from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from py_eightctl.eightsleep import (
    Alarm,
    AlarmList,
    CredentialsInput,
    EightSleepError,
    EightSleepService,
    EmptyRequest,
    PodStatus,
    SetAlarmEnabledRequest,
    SetCurrentTemperatureRequest,
    SetPowerRequest,
    SetSmartTemperatureRequest,
    SmartTemperatureStage,
    SmartTemperatureStatus,
    parse_temperature_input,
)

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
alarm_app = typer.Typer(
    no_args_is_help=True,
    help="List alarms and enable or disable them.",
)
smart_temp_app = typer.Typer(
    no_args_is_help=True,
    help="View or update bedtime, night, and dawn temperatures.",
)


class CliState:
    def __init__(self, service: EightSleepService, *, json_output: bool) -> None:
        self.service = service
        self.json_output = json_output


RenderableModel = Alarm | AlarmList | PodStatus | SmartTemperatureStatus


def main() -> None:
    app()


def _state(ctx: typer.Context) -> CliState:
    return ctx.obj


def _print_model(ctx: typer.Context, model: RenderableModel) -> None:
    state = _state(ctx)
    if state.json_output:
        typer.echo(model.model_dump_json(indent=2, by_alias=True))
        return

    if isinstance(model, AlarmList):
        _print_alarm_list(model)
        return

    if isinstance(model, SmartTemperatureStatus):
        smart = model.smart
        typer.echo(f"mode: {model.current_state.type}")
        typer.echo(f"power: {'on' if model.is_on else 'off'}")
        typer.echo(f"current level: {model.current_level}")
        if smart is not None:
            typer.echo(f"bedtime: {smart.bedtime}")
            typer.echo(f"night: {smart.night}")
            typer.echo(f"dawn: {smart.dawn}")
        return

    if isinstance(model, PodStatus):
        typer.echo(f"power: {'on' if model.is_on else 'off'}")
        typer.echo(f"mode: {model.current_state.type}")
        typer.echo(f"current level: {model.current_level}")
        return

    if isinstance(model, Alarm):
        typer.echo(
            f"{model.id} {model.time} enabled={str(model.enabled).lower()} "
            f"state={model.state} next={str(model.next).lower()} "
            f"one_off={str(model.one_off).lower()}"
        )
        return


def _print_alarm_list(alarm_list: AlarmList) -> None:
    if not alarm_list.alarms:
        typer.echo("no alarms")
        return

    typer.echo("state    time      type      selector")
    for alarm in alarm_list.alarms:
        alarm_type = "one-off" if alarm.one_off else "routine"
        selector = "next" if alarm.next else alarm.id
        typer.echo(f"{alarm.state:<8} {alarm.time:<9} {alarm_type:<9} {selector}")


def _handle_error(error: EightSleepError) -> None:
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=1) from error


def _ensure_credentials(service: EightSleepService) -> None:
    config = service.get_config(EmptyRequest())
    if config.has_credentials:
        return

    email = typer.prompt("Eight Sleep email").strip()
    password = typer.prompt("Eight Sleep password", hide_input=True)
    service.save_credentials(CredentialsInput(email=email, password=password))


@app.callback()
def callback(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Render structured JSON output."),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option("--config-path", help="Override the default config file path."),
    ] = None,
) -> None:
    if ctx.resilient_parsing:
        return

    service = EightSleepService(config_path=config_path)
    _ensure_credentials(service)
    ctx.obj = CliState(service=service, json_output=json_output)


@app.command()
def status(ctx: typer.Context) -> None:
    """Show the current pod power state and active level."""
    try:
        _print_model(ctx, _state(ctx).service.get_status(EmptyRequest()))
    except EightSleepError as error:
        _handle_error(error)


@app.command()
def on(ctx: typer.Context) -> None:
    """Turn the pod on."""
    try:
        _print_model(ctx, _state(ctx).service.set_power(SetPowerRequest(on=True)))
    except EightSleepError as error:
        _handle_error(error)


@app.command()
def off(ctx: typer.Context) -> None:
    """Turn the pod off."""
    try:
        _print_model(ctx, _state(ctx).service.set_power(SetPowerRequest(on=False)))
    except EightSleepError as error:
        _handle_error(error)


@app.command()
def temp(
    ctx: typer.Context,
    value: Annotated[str, typer.Argument(help="Target temp level, or a value like 68F / 20C.")],
) -> None:
    """Set the current pod temperature."""
    try:
        parsed = parse_temperature_input(value)
        _print_model(
            ctx,
            _state(ctx).service.set_current_temperature(
                SetCurrentTemperatureRequest(level=parsed.level)
            ),
        )
    except EightSleepError as error:
        _handle_error(error)


@smart_temp_app.command("status")
def smart_temp_status(ctx: typer.Context) -> None:
    """Show bedtime, night, and dawn temperatures."""
    try:
        _print_model(ctx, _state(ctx).service.get_smart_temperature_status(EmptyRequest()))
    except EightSleepError as error:
        _handle_error(error)


@smart_temp_app.command("set")
def smart_temp_set(
    ctx: typer.Context,
    stage: Annotated[SmartTemperatureStage, typer.Argument(help="bedtime, night, or dawn")],
    value: Annotated[str, typer.Argument(help="Target temp level, or a value like 68F / 20C.")],
) -> None:
    """Set one smart temperature stage."""
    try:
        parsed = parse_temperature_input(value)
        _print_model(
            ctx,
            _state(ctx).service.set_smart_temperature(
                SetSmartTemperatureRequest(stage=stage, level=parsed.level)
            ),
        )
    except EightSleepError as error:
        _handle_error(error)


@alarm_app.command("list")
def alarm_list(ctx: typer.Context) -> None:
    """List alarms."""
    try:
        _print_model(ctx, _state(ctx).service.list_alarms(EmptyRequest()))
    except EightSleepError as error:
        _handle_error(error)


@alarm_app.command("enable")
def alarm_enable(
    ctx: typer.Context,
    selector: Annotated[
        str,
        typer.Argument(help="Alarm selector: next, exact HH:MM[:SS], or a full alarm id."),
    ],
) -> None:
    """Enable an alarm."""
    try:
        _print_model(
            ctx,
            _state(ctx).service.set_alarm_enabled(
                SetAlarmEnabledRequest(selector=selector, enabled=True)
            ),
        )
    except EightSleepError as error:
        _handle_error(error)


@alarm_app.command("disable")
def alarm_disable(
    ctx: typer.Context,
    selector: Annotated[
        str,
        typer.Argument(help="Alarm selector: next, exact HH:MM[:SS], or a full alarm id."),
    ],
) -> None:
    """Disable an alarm."""
    try:
        _print_model(
            ctx,
            _state(ctx).service.set_alarm_enabled(
                SetAlarmEnabledRequest(selector=selector, enabled=False)
            ),
        )
    except EightSleepError as error:
        _handle_error(error)


app.add_typer(smart_temp_app, name="smart-temp")
app.add_typer(alarm_app, name="alarm")
