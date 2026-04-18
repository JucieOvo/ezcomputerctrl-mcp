---
name: install-ezcomputerctrl-mcp
description: Install and configure EZComputerCtrl as a hidden background streamable-http MCP on Windows.
when_to_use: Use when this repository has been cloned locally and the current agent needs to finish runtime configuration, choose a port, write the local env file, start the MCP in the background, and connect the host client to the MCP endpoint.
disable-model-invocation: true
allowed-tools: Read Edit Write Glob Grep Bash(pip install -e .) Bash(cscript *) Bash(powershell *)
---

# Install EZComputerCtrl MCP

This skill is a manual setup playbook for the repository-local EZComputerCtrl MCP.

Run this skill only when the repository already exists on the local Windows machine and the goal is to finish installation and MCP wiring for the current host client.

## Goal

Configure this repository as a hidden background `streamable-http` MCP service on Windows without modifying source defaults.

## Required outcomes

Complete all of the following:

1. Install Python dependencies.
2. Select a local port.
3. Create or update `.runtime/ezcomputerctrl.env.ps1`.
4. Configure a real OpenAI-compatible VLM endpoint.
5. Start the service with `scripts/start_ezcomputerctrl_hidden.vbs`.
6. Confirm `.runtime/ezcomputerctrl.pid` exists.
7. Configure the current host client to use `http://127.0.0.1:<port>/mcp`.
8. Tell the user how to stop the service.

## Rules

1. Do not modify `src/ezcomputerctrl/config.py` to store local machine settings.
2. Store machine-specific runtime values only in `.runtime/ezcomputerctrl.env.ps1`.
3. Do not invent model names, base URLs, ports, or API keys.
4. Do not create startup tasks, scheduled tasks, or system services.
5. Do not split this workflow by client type. Adapt to the current host client in place.

## Step 1: Confirm repository root

The working directory should contain:

1. `pyproject.toml`
2. `src/`
3. `scripts/`
4. `skills/install-ezcomputerctrl-mcp/SKILL.md`

## Step 2: Install dependencies

Run:

```powershell
pip install -e .
```

If installation fails, stop and report the real error.

## Step 3: Select the port

Port rules:

1. If the user explicitly provided a port, use it.
2. Otherwise prefer `8765`.
3. If `8765` is unavailable, choose a free local port.
4. Write the selected port into `.runtime/ezcomputerctrl.env.ps1`.

## Step 4: Write the local runtime env file

Create or update:

`.runtime/ezcomputerctrl.env.ps1`

Use `scripts/ezcomputerctrl.env.example.ps1` as the starting template.

At minimum, set:

```powershell
$env:EZCTRL_TRANSPORT = "streamable-http"
$env:EZCTRL_SERVER_HOST = "127.0.0.1"
$env:EZCTRL_SERVER_PORT = "8765"
$env:EZCTRL_MODEL_NAME = "your-real-model-name"
$env:EZCTRL_MODEL_BASE_URL = "your-real-openai-compatible-base-url"
$env:EZCTRL_MODEL_API_KEY = "your-real-api-key"
```

## Step 5: Configure the VLM

Recommended route: `Qwen3.5/3.6 35B-A3B`

Use the user's real deployment values only:

1. real model name
2. real base URL
3. real API key

If any of these are missing, ask for them instead of guessing.

## Step 6: Start the hidden background service

Run:

```powershell
cscript //nologo scripts\start_ezcomputerctrl_hidden.vbs
```

Then verify:

1. `.runtime/ezcomputerctrl.pid` exists
2. the configured MCP URL is `http://127.0.0.1:<port>/mcp`

## Step 7: Configure the current host client

Adapt to the actual host client instead of assuming one fixed config format.

Target connection settings:

1. transport: `streamable-http`
2. URL: `http://127.0.0.1:<port>/mcp`

```json
{
    "ezcomputerctrl": {
        "type": "remote",
        "url": "http://127.0.0.1:<port>/mcp",
        "enabled": true
    }
}
```

Use the host client's real MCP configuration mechanism and write the equivalent configuration there.

## Step 8: Stop command

The stop command is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_ezcomputerctrl.ps1
```

Include this in the final instructions to the user.

## Final check

Before finishing, confirm all of the following:

1. dependencies installed successfully
2. `.runtime/ezcomputerctrl.env.ps1` exists
3. the selected port is written correctly
4. the VLM values are real and complete
5. the hidden background MCP process is running
6. `.runtime/ezcomputerctrl.pid` exists
7. the current host client points to the correct MCP URL

## Final response format

Report only the concrete setup result:

1. selected port
2. MCP URL
3. whether the background process is running
4. where the local env file was written
5. how to stop the service
