"""
模块名称：mcp_server
功能描述：
    提供第一阶段 MCP 对外工具接口。

    改造说明（2026-04-18）：
      - MCP 工具函数不再直接执行业务，改为：
          1. 将请求投入 WorkDispatchQueue
          2. 持续发送心跳，直到 Worker 完成
          3. 将 Worker 结果序列化后返回给 MCP 客户端
      - 通过这种分离，MCP 层在任何时候都不会停止心跳，
        彻底消除因业务耗时导致的 MCP 超时断连。

主要组件：
    - build_mcp_server: 构建 MCP 服务实例。
    - _await_future_with_heartbeat: MCP 层专用的 Future 心跳等待函数。

依赖说明：
    - mcp.server.fastmcp: 用于构建 MCP 工具服务端。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化 MCP 工具层。
    - 2026-04-18 JucieOvo: 改造为纯心跳等待模式，业务执行移至 Worker 层。
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ezcomputerctrl.config import AppConfig
from ezcomputerctrl.controller import WorkflowController
from ezcomputerctrl.dispatch import WorkDispatchQueue
from ezcomputerctrl.models import ActionResult, ScreenSnapshot, ScreenSummary, SemanticObject


# MCP 层心跳间隔（秒）：每隔此时间向 MCP 客户端发送一次进度回传
MCP_HEARTBEAT_INTERVAL_SECONDS = 2.0


async def _await_future_with_heartbeat(
    future: asyncio.Future,
    ctx: Context,
    tool_name: str,
) -> Any:
    """
    MCP 层专用的 Future 心跳等待函数。

    职责：
      - 在等待 Worker 执行结果期间，持续以固定间隔向 MCP 客户端发送进度心跳。
      - Future 完成后，立即返回结果（或重新抛出 Worker 中的异常）。

    设计要点：
      - 使用 asyncio.shield(future) 防止 wait_for 超时时取消 Future 本身。
      - TimeoutError 只代表"本轮心跳周期到期，Worker 尚未完成"，继续下一轮。
      - 若 Worker 完成，future.result() 自动重抛 Worker 侧的异常。

    :param future: 与本次请求绑定的 Future，由 WorkDispatchQueue.put() 返回
    :param ctx: FastMCP 请求上下文，用于发送心跳
    :param tool_name: 工具名称，用于心跳消息中显示
    :return: Worker 执行结果
    :raises Exception: 透传 Worker 侧抛出的任意异常
    """

    heartbeat_count = 0
    while not future.done():
        heartbeat_count += 1
        # 向 MCP 客户端发送心跳（进度不确定，固定报 50%，只要不断线即可）
        message = f"{tool_name} 正在执行中（第 {heartbeat_count} 次心跳）"
        await ctx.info(message)
        await ctx.report_progress(
            progress=50.0,
            total=100.0,
            message=message,
        )
        try:
            # 等待 future 完成，超时后继续下一轮心跳
            # asyncio.shield 保证即使 wait_for 超时也不会取消 Worker 侧的 future
            await asyncio.wait_for(
                asyncio.shield(future),
                timeout=MCP_HEARTBEAT_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            # 超时说明 Worker 还未完成，继续发心跳
            continue

    # Future 已完成：调用 result() 拿到结果，或重新抛出 Worker 侧异常
    return future.result()


def _serialize_public_object(obj: SemanticObject) -> dict[str, Any]:
    """
    序列化对外公开的语义对象。

    :param obj: 内部语义对象
    :return: 不含内部定位字段的公开对象字典
    """

    serialized = {
        "id": obj.id,
        "name": obj.name,
        "type": obj.type.value,
        "description": obj.description,
        "location_hint": obj.location_hint,
        "actions": [action.value for action in obj.actions],
    }
    if obj.window_hint:
        serialized["window_hint"] = obj.window_hint
    return serialized


def _build_scene_summary(summary: ScreenSummary) -> str:
    """
    将内部 ScreenSummary 组装为更适合下游理解的自然语言摘要。

    :param summary: 内部界面摘要对象
    :return: 自然语言场景摘要
    """

    summary_parts: list[str] = []
    if summary.scene_name:
        summary_parts.append(summary.scene_name)
    if summary.main_regions:
        summary_parts.append(f"主要区域：{'、'.join(summary.main_regions)}")
    if summary.prominent_change:
        summary_parts.append(f"显著线索：{summary.prominent_change}")
    return "；".join(summary_parts)


def _serialize_public_snapshot(snapshot: ScreenSnapshot) -> dict[str, Any]:
    """
    序列化对外公开的状态快照。

    :param snapshot: 内部状态快照
    :return: 不含内部定位字段的公开快照字典
    """

    return {
        "scene_summary": _build_scene_summary(snapshot.screen_summary),
        "objects": [_serialize_public_object(obj) for obj in snapshot.actionable_objects],
        "warnings": list(snapshot.warnings),
    }


def _serialize_public_action_result(result: ActionResult) -> dict[str, Any]:
    """
    序列化对外公开的动作结果。

    精简原则：只保留 Agent 决策所需的最小信息集：
    - ok:      布尔值，成功=True，失败/不确定=False，Agent 无需理解枚举
    - summary: 一句话执行摘要，有警告时追加到末尾
    - scene:   动作后的场景摘要（原 scene_summary）
    - objects: 新的可操作对象列表

    已移除字段：
    - change_events: 内部审计字段，继续在 state_store 中存档，不对外暴露
    - execution_id:  纯内部追踪 ID，Agent 不使用
    - warnings:      合并进 summary，减少顶层字段数

    :param result: 内部动作结果对象
    :return: 精简后的公开动作结果字典
    """

    # 场景 1：成功状态直接标记 ok=True
    # 场景 2：失败或不确定状态标记 ok=False
    ok_flag = result.result_status.value == "success"

    # 有警告时拼接到摘要末尾，保留信息但不增加顶层字段
    summary = result.result_summary
    if result.warnings:
        warnings_text = "；".join(result.warnings)
        summary = f"{summary}（注意：{warnings_text}）"

    return {
        "ok": ok_flag,
        "summary": summary,
        "scene": _build_scene_summary(result.updated_screen_summary),
        "objects": [_serialize_public_object(obj) for obj in result.updated_actionable_objects],
    }


def _serialize_move_result(object_id: str, notes: list[str]) -> dict[str, Any]:
    """
    序列化悬停动作返回值。

    move_to 不触发 VLM 重观测，无新的 objects 列表，
    只返回操作结果和目标对象 ID。

    :param object_id: 目标对象 ID
    :param notes: 执行记录备注
    :return: 公开返回结果
    """

    # 有备注则取最后一条作为摘要，否则生成通用说明
    summary = notes[-1] if notes else f"已移动鼠标到目标对象 {object_id}"
    return {
        "ok": True,
        "summary": summary,
        "object_id": object_id,
    }


def build_mcp_server(
    config: AppConfig | None = None,
    queue: WorkDispatchQueue | None = None,
) -> FastMCP:
    """
    构建第一阶段 MCP 服务实例。

    :param config: 应用配置；若为空则从环境变量读取
    :param queue: 请求分发队列；若为空则在内部创建（通常由 __main__ 传入）
    :return: FastMCP 服务实例
    """

    resolved_config = config or AppConfig.from_env()
    # NOTE: queue 必须在 asyncio 事件循环启动后创建，此处若为 None 则延迟到首次使用时创建。
    # 实际生产中 __main__.py 会先启动事件循环再创建 queue，然后传入此处。
    resolved_queue = queue or WorkDispatchQueue()

    server = FastMCP(
        name=resolved_config.app_name,
        instructions=(
            "本服务提供桌面 GUI 的视觉读取与手部执行能力。\n"
            "你可以用 see 读取屏幕，用 click、scroll、move_to、type_text、hotkey 执行动作。\n"
            "【注意】执行动作指令（如 click, hotkey 等）后，服务端不再进行费时的画面重确认以避免超时，\n"
            "你将在下发动作指令后立即收到成功响应。如需确认界面变化，请主动调用 see 获取最新屏幕状态。"
        ),
        host=resolved_config.server_host,
        port=resolved_config.server_port,
    )

    @server.tool()
    async def see(ctx: Context) -> dict[str, Any]:
        """截图并识别当前屏幕上的可操作控件。"""

        # 投入队列，立即获得 Future
        future = resolved_queue.put("see", {})
        # 心跳等待 Worker 执行完成
        snapshot: ScreenSnapshot = await _await_future_with_heartbeat(future, ctx, "see")
        return _serialize_public_snapshot(snapshot)

    @server.tool()
    async def click(
        object_id: str,
        button: str = "left",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """单击指定控件，支持 left 和 right 两种按键。"""

        future = resolved_queue.put("click", {"object_id": object_id, "button": button})
        result: ActionResult = await _await_future_with_heartbeat(future, ctx, "click")
        return _serialize_public_action_result(result)

    @server.tool()
    async def scroll(
        object_id: str,
        direction: str,
        lines: int = 3,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """在指定控件处滚动鼠标滚轮。"""

        future = resolved_queue.put(
            "scroll",
            {"object_id": object_id, "direction": direction, "lines": lines},
        )
        result: ActionResult = await _await_future_with_heartbeat(future, ctx, "scroll")
        return _serialize_public_action_result(result)

    @server.tool()
    async def move_to(
        object_id: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """移动鼠标到指定控件中心点，用于悬停触发。"""

        from ezcomputerctrl.models import ExecutionRecord

        future = resolved_queue.put("move_to", {"object_id": object_id})
        execution_record: ExecutionRecord = await _await_future_with_heartbeat(
            future, ctx, "move_to"
        )
        return _serialize_move_result(
            object_id=object_id,
            notes=execution_record.notes,
        )

    @server.tool()
    async def type_text(
        text: str,
        object_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """输入文本；若提供 object_id，则自动先点击再输入。"""

        future = resolved_queue.put(
            "type_text",
            {"text": text, "object_id": object_id},
        )
        result: ActionResult = await _await_future_with_heartbeat(future, ctx, "type_text")
        return _serialize_public_action_result(result)

    @server.tool()
    async def hotkey(
        keys: str | list[str],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """发送组合快捷键，支持 ctrl+c 或 ["ctrl", "c"]。"""

        future = resolved_queue.put("hotkey", {"keys": keys})
        result: ActionResult = await _await_future_with_heartbeat(future, ctx, "hotkey")
        return _serialize_public_action_result(result)

    return server
