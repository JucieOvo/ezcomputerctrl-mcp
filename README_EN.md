# EZComputerCtrl MCP

[简体中文](./README.md)

A vision-first MCP for Windows desktop GUI control that lets agents act on semantic objects instead of fragile screen coordinates.

`EZComputerCtrl` turns the current desktop into structured, actionable GUI facts. Agents choose semantic objects and actions, while the MCP handles localization, execution, and result reporting.

## Current Scope

Currently exposed MCP tools:

1. `see`
2. `click`
3. `scroll`
4. `move_to`
5. `type_text`
6. `hotkey`

Supported transports:

1. `stdio`
2. `streamable-http`
3. `sse`

Default transport: `streamable-http`

## Installation

```powershell
git clone https://github.com/JucieOvo/ezcomputerctrl-mcp.git
cd ezcomputerctrl-mcp
pip install -e .
```

## Bundled Skill

This repository ships with one generic setup skill:

`skills/install-ezcomputerctrl-mcp/SKILL.md`

The skill is designed to help different agent clients complete local setup without assuming one fixed client-specific format.

Typical usage:

1. Open the cloned repository inside the target agent client.
2. Invoke `/install-ezcomputerctrl-mcp`, or instruct the agent to use the bundled skill.
3. Let the agent finish port selection, local env setup, background launch, and MCP client wiring.

## Local Runtime Configuration

Machine-specific runtime values should be stored in:

`.runtime/ezcomputerctrl.env.ps1`

An example file is provided at:

`scripts/ezcomputerctrl.env.example.ps1`

The launch script loads this file automatically before starting the service.

Common environment variables:

1. `EZCTRL_TRANSPORT`
2. `EZCTRL_SERVER_HOST`
3. `EZCTRL_SERVER_PORT`
4. `EZCTRL_MODEL_NAME`
5. `EZCTRL_MODEL_BASE_URL`
6. `EZCTRL_MODEL_API_KEY`

## VLM Configuration

Recommended route: `Qwen3.5/3.6 35B-A3B`

Do not hardcode fictional model IDs. Always use the real deployed values for:

1. `EZCTRL_MODEL_NAME`
2. `EZCTRL_MODEL_BASE_URL`
3. `EZCTRL_MODEL_API_KEY`

An OpenAI-compatible VLM endpoint is expected.

## Start And Stop

Start in hidden background mode:

```powershell
cscript //nologo scripts\start_ezcomputerctrl_hidden.vbs
```

Stop the background service:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_ezcomputerctrl.ps1
```

Run the launch script directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_ezcomputerctrl_http.ps1
```

The launch script starts the MCP service in the background and writes the PID to `.runtime/ezcomputerctrl.pid`.

## MCP Endpoint

With the default host and port, the `streamable-http` endpoint is:

`http://127.0.0.1:8765/mcp`

If the local port changes, update the endpoint accordingly.

## Repository Layout

```text
.
|-- .runtime/
|-- pyproject.toml
|-- README.md
|-- README_EN.md
|-- scripts/
|   |-- ezcomputerctrl.env.example.ps1
|   |-- run_ezcomputerctrl_http.ps1
|   |-- start_ezcomputerctrl_hidden.vbs
|   `-- stop_ezcomputerctrl.ps1
|-- skills/
|   `-- install-ezcomputerctrl-mcp/
|       `-- SKILL.md
`-- src/
    `-- ezcomputerctrl/
```

## Windows Notes

1. Start and stop scripts are written for Windows PowerShell 5.1 first.
2. Scripts stay ASCII-first to reduce encoding problems.
3. Hidden launch uses `VBScript + PowerShell` to avoid exposing a console window.

## Limitations

1. The current implementation targets Windows desktop GUI, not game control.
2. The system depends on a real desktop environment and a real VLM service.
3. This is a vision-driven control layer, not a zero-error automation guarantee.
4. The public tool surface is intentionally small to prioritize stability.
5. If this tool has been running and you plan to launch a game protected by ring-0 anti-cheat systems such as Tencent ACE, there may be a risk of account penalties or bans. Fully close this tool and reboot the computer before starting such games. The author and community provide no guarantee and accept no responsibility for any game account bans, restrictions, or other losses related to the use of this tool.
