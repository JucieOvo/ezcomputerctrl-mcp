# EZComputerCtrl MCP

[English](./README_EN.md)

一个面向 Windows 桌面 GUI 控制、视觉优先的 MCP，让智能体能够操作语义对象，而不是脆弱的屏幕坐标。

`EZComputerCtrl` 会先把当前桌面整理为结构化、可执行的界面事实，再由上层智能体选择对象和动作，最后由 MCP 内部完成定位、执行和结果返回。

## 当前能力

当前已公开的 MCP 工具：

1. `see`
2. `click`
3. `scroll`
4. `move_to`
5. `type_text`
6. `hotkey`

当前支持的传输方式：

1. `stdio`
2. `streamable-http`
3. `sse`

默认传输方式：`streamable-http`

## 安装

```powershell
git clone https://github.com/JucieOvo/ezcomputerctrl-mcp.git
cd ezcomputerctrl-mcp
pip install -e .
```

## 配套 Skill

仓库内置一个通用装配 skill：

`skills/install-ezcomputerctrl-mcp/SKILL.md`

这个 skill 用于让不同 Agent 客户端在各自环境中快速完成本地配置，而不是绑定某一种固定客户端格式。

典型使用方式：

1. 在 Agent 客户端中打开已克隆的仓库。
2. 调用 `/install-ezcomputerctrl-mcp`，或让 Agent 使用该 skill。
3. 让 Agent 完成端口选择、本地环境写入、后台启动与 MCP 接入配置。

## 本地运行配置

机器相关的本地运行配置应写入：

`.runtime/ezcomputerctrl.env.ps1`

示例文件位于：

`scripts/ezcomputerctrl.env.example.ps1`

启动脚本会在拉起服务前自动加载该文件。

常用环境变量：

1. `EZCTRL_TRANSPORT`
2. `EZCTRL_SERVER_HOST`
3. `EZCTRL_SERVER_PORT`
4. `EZCTRL_MODEL_NAME`
5. `EZCTRL_MODEL_BASE_URL`
6. `EZCTRL_MODEL_API_KEY`

## VLM 配置

推荐路线：`Qwen3.5/3.6 35B-A3B`

这里不要写死虚构模型名。请始终使用真实部署出来的：

1. `EZCTRL_MODEL_NAME`
2. `EZCTRL_MODEL_BASE_URL`
3. `EZCTRL_MODEL_API_KEY`

当前默认预期为兼容 OpenAI 协议的 VLM 接口。

## 启动与停止

隐藏后台启动：

```powershell
cscript //nologo scripts\start_ezcomputerctrl_hidden.vbs
```

停止后台服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_ezcomputerctrl.ps1
```

直接执行启动脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_ezcomputerctrl_http.ps1
```

启动脚本会在后台拉起 MCP 服务，并将进程 PID 写入 `.runtime/ezcomputerctrl.pid`。

## MCP 地址

在默认主机和端口下，`streamable-http` 地址为：

`http://127.0.0.1:8765/mcp`

如果本地改了端口，请按实际端口替换该地址。

## 目录结构

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

## Windows 说明

1. 启停脚本优先兼容 Windows PowerShell 5.1。
2. 脚本内容尽量保持 ASCII 优先，降低编码问题。
3. 隐藏启动使用 `VBScript + PowerShell`，避免暴露命令行窗口后被误关。

## 当前限制

1. 当前实现聚焦 Windows 桌面 GUI，不面向游戏控制场景。
2. 当前能力依赖真实桌面环境和真实 VLM 服务。
3. 这是视觉驱动控制层，不承诺复杂界面下零误差识别。
4. 当前对外工具面保持收敛，优先保证稳定性与可控性。
