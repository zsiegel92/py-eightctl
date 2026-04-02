# py-eightctl

Minimal CLI for a few useful Eight Sleep controls.

## Install

```bash
uv sync
```

## Run

```bash
uv run py-eightctl status
```

On first use, it will prompt for your Eight Sleep email and password and store
them in `~/.config/py-eightctl/config.json`.

## Common Commands

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

Add `--json` to print structured output.

## Build One File Executable

```bash
uv run poe build-onefile
```
