# py-eightctl

Small Python CLI and reusable client module for the core Eight Sleep controls:

- pod on/off status
- turn pod on/off
- set current pod temperature
- list alarms and enable/disable them
- set bedtime / night / dawn temperatures

The Eight Sleep API is undocumented. This project follows the working endpoint
patterns from the sibling `../eightctl` fork instead of upstream assumptions.

## First Run

The CLI stores config in `~/.config/py-eightctl/config.json`.

On first use it will prompt for:

- email
- password

It also caches the resolved `user_id` plus the current auth token expiry so it
does not need to log in on every command.

## Commands

```bash
uv run py-eightctl status
uv run py-eightctl on
uv run py-eightctl off
uv run py-eightctl temp 68F
uv run py-eightctl temp -- -20
uv run py-eightctl smart-temp status
uv run py-eightctl smart-temp set bedtime -- -30
uv run py-eightctl alarm list
uv run py-eightctl alarm enable next
uv run py-eightctl alarm disable 07:15
```

Add `--json` to any command to print structured output.

## Dev Commands

```bash
uv run poe typecheck
uv run poe lint
uv run poe format-check
uv run poe format
uv run poe test
uv run poe build-onefile
```
