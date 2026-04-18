# EZComputerCtrl MCP

A vision-first MCP for Windows desktop GUI control that lets agents act on semantic objects instead of fragile screen coordinates.

`EZComputerCtrl` turns the current desktop into structured, actionable GUI facts. Agents choose semantic objects and actions; the MCP handles screen reading, object localization, execution, and result reporting.

## Repository Scope

This repository is the publication-ready release of `EZComputerCtrl MCP`.

## Current Scope

Current MCP tools:

1. `see`
2. `click`
3. `scroll`
4. `move_to`
5. `type_text`
6. `hotkey`

Current transports:

1. `stdio`
2. `streamable-http`
3. `sse`

Default transport: `streamable-http`

## Install

```powershell
git clone <repository-url>
cd <repository-name>
pip install -e .
```

## Bundled Project Skill

This repository ships with one setup skill:

`skills/install-ezcomputerctrl-mcp/SKILL.md`

The skill is intended to be invoked manually and used as the single setup playbook for agent-driven configuration.

Typical usage:

1. Open the cloned repository in the target agent client.
2. Invoke `/install-ezcomputerctrl-mcp` or instruct the agent to use the bundled setup skill.
3. Let the agent complete port selection, local runtime configuration, hidden background launch, and MCP client wiring.

## Runtime Configuration

Local machine-specific runtime values should be stored in:

`.runtime/ezcomputerctrl.env.ps1`

An example file is included at:

`scripts/ezcomputerctrl.env.example.ps1`

The launch script loads this file automatically before starting the MCP process.

Key variables:

1. `EZCTRL_TRANSPORT`
2. `EZCTRL_SERVER_HOST`
3. `EZCTRL_SERVER_PORT`
4. `EZCTRL_MODEL_NAME`
5. `EZCTRL_MODEL_BASE_URL`
6. `EZCTRL_MODEL_API_KEY`

## VLM

Recommended deployment route: `Qwen3.5/3.6 35B-A3B`

Do not hardcode fictional model IDs. Always use the real deployed values for:

1. `EZCTRL_MODEL_NAME`
2. `EZCTRL_MODEL_BASE_URL`
3. `EZCTRL_MODEL_API_KEY`

An OpenAI-compatible VLM endpoint is expected.

## Start And Stop

Hidden background launch:

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

The launch script starts the MCP server in the background and writes the PID to `.runtime/ezcomputerctrl.pid`.

## MCP Endpoint

With the default host and port, the streamable HTTP endpoint is:

`http://127.0.0.1:8765/mcp`

If the configured port changes, the endpoint changes accordingly.

## Repository Layout

```text
.
|-- .runtime/
|-- pyproject.toml
|-- README.md
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

1. Scripts are written for Windows PowerShell 5.1 compatibility first.
2. Script contents are kept ASCII-first to reduce encoding issues.
3. Hidden launch uses `VBScript + PowerShell` to avoid an exposed console window.

## Limitations

1. The current implementation targets Windows desktop GUI, not game control.
2. The system depends on a real desktop environment and a real VLM endpoint.
3. This is a vision-driven control layer, not a zero-error automation guarantee.
4. The public tool surface is intentionally small to prioritize stability.
