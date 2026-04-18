"""
模块名称：controller
功能描述：
    负责串行调度第一阶段主流程。

    改造说明（2026-04-18）：
      - 原有 asyncio.Lock 串行保护方案已移除。
      - 改由 WorkDispatchQueue（dispatch.py）保证业务串行执行：
        Worker 循环从队列逐一取请求、执行业务、将结果写回 Future。
      - MCP 工具函数不再直接调用控制器方法，而是把请求投入队列后做心跳等待。
      - 控制器所有公开工具方法（see/click/...）保持不变，被 Worker 内部调用。

主要组件：
    - WorkflowController: 第一阶段主控制器（业务执行层）。

依赖说明：
    - asyncio: 用于异步等待和长耗时阶段心跳上报。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化第一阶段串行主流程控制器。
    - 2026-04-18 JucieOvo: 去掉 asyncio.Lock，改为 Worker 队列驱动的串行模型；
                           新增 run_worker_loop() 作为 Worker 无限循环入口。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Awaitable, TypeVar

from mcp.server.fastmcp import Context

from ezcomputerctrl.capture import ScreenCaptureService
from ezcomputerctrl.config import AppConfig
from ezcomputerctrl.dispatch import DispatchRequest, WorkDispatchQueue
from ezcomputerctrl.executor import DesktopExecutor
from ezcomputerctrl.models import (
    ActionRequest,
    ActionResult,
    ActionType,
    ExecutionRecord,
    GlobalActionRequest,
    PerceptionResult,
    RawFrame,
    ResultStatus,
    ScreenSnapshot,
    WorkflowState,
)
from ezcomputerctrl.perception import VisualPerceptionService
from ezcomputerctrl.semantic import SemanticNormalizer
from ezcomputerctrl.state_store import InMemoryStateStore
from ezcomputerctrl.watcher import ActionWatcher


ProgressValueT = TypeVar("ProgressValueT")
DEFAULT_PROGRESS_TOTAL = 100.0
HEARTBEAT_INTERVAL_SECONDS = 2.0


class WorkflowController:
    """
    第一阶段串行主控制器（业务执行层）。

    当前控制器职责：
    1. 提供 see / click / scroll / move_to / type_text / hotkey 六个工具方法，
       由 Worker 循环串行调用，不再由 MCP 工具函数直接调用。
    2. 在执行长耗时操作（VLM / executor）期间持续向 MCP 客户端发送心跳。
    3. 维护内部状态机与状态存储，保证状态可追踪。
    4. 提供 run_worker_loop() 作为独立 Worker Task 的入口。

    设计变化（相比旧版）：
    - 去掉 asyncio.Lock，改由调用者（Worker 队列）保证串行。
    - 去掉 _acquire_lock_with_heartbeat，心跳完全由 MCP 层的
      _await_future_with_heartbeat 承担，控制器层只负责汇报阶段进度。
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        """
        初始化主控制器。

        :param config: 应用配置；若为空则从环境变量读取
        """

        self.config = config or AppConfig.from_env()
        self.capture_service = ScreenCaptureService(self.config)
        self.perception_service = VisualPerceptionService(self.config)
        self.semantic_normalizer = SemanticNormalizer()
        self.state_store = InMemoryStateStore()
        self.executor = DesktopExecutor()
        self.watcher = ActionWatcher()
        self.workflow_state = WorkflowState.IDLE

    # ══════════════════════════════════════════════════════════
    # § Worker 循环入口
    # ══════════════════════════════════════════════════════════

    async def run_worker_loop(
        self,
        queue: WorkDispatchQueue,
        ctx_factory: Any = None,
    ) -> None:
        """
        Worker 无限循环：从分发队列取请求、执行业务、将结果写回 Future。

        本方法以 asyncio.create_task() 方式启动，在 MCP 服务生命周期内持续运行。
        业务串行性由队列 FIFO 保证，无需额外锁。

        执行流程：
          1. 从队列取出一个 DispatchRequest。
          2. 根据 tool_name 路由到对应的业务方法。
          3. 将执行结果写入 request.result_future。
          4. 若执行抛出异常，将异常写入 request.result_future。
          5. 通知队列本次任务完成，继续下一轮。

        :param queue: 请求分发队列实例
        :param ctx_factory: 保留参数，当前未使用（Worker 执行时 ctx=None，心跳由 MCP 层承担）
        """

        while True:
            # 等待下一个请求（队列为空时协程挂起，不消耗 CPU）
            request = await queue.get()
            try:
                # Worker 执行时不传 ctx，心跳完全由 MCP 层的 Future 等待侧承担
                result = await self._dispatch(request)
                # 场景 1：业务执行成功，将结果写入 Future
                if not request.result_future.done():
                    request.result_future.set_result(result)
            except Exception as exc:
                # 场景 2：业务执行失败，将异常写入 Future，由 MCP 层处理并向客户端报错
                if not request.result_future.done():
                    request.result_future.set_exception(exc)
            finally:
                # 通知队列本次任务已处理完毕（无论成功失败）
                queue.task_done()

    async def _dispatch(self, request: DispatchRequest) -> Any:
        """
        根据工具名称将请求路由到对应业务方法。

        :param request: 请求容器
        :return: 业务方法的返回值（类型由各工具方法决定）
        :raises ValueError: 当工具名称未注册时抛出
        """

        # 工具名到业务方法的路由表
        # NOTE: Worker 执行时 ctx=None，阶段进度由控制器内部记录，
        #       心跳统一由 MCP 层的 _await_future_with_heartbeat 发出。
        payload = request.payload
        name = request.tool_name

        # 场景 1：读取屏幕
        if name == "see":
            return await self.see(ctx=None)

        # 场景 2：点击
        if name == "click":
            return await self.click(
                object_id=payload["object_id"],
                button=payload.get("button", "left"),
                ctx=None,
            )

        # 场景 3：滚轮
        if name == "scroll":
            return await self.scroll(
                object_id=payload["object_id"],
                direction=payload["direction"],
                lines=payload.get("lines", 3),
                ctx=None,
            )

        # 场景 4：悬停
        if name == "move_to":
            return await self.move_to(
                object_id=payload["object_id"],
                ctx=None,
            )

        # 场景 5：文本输入
        if name == "type_text":
            return await self.type_text(
                text=payload["text"],
                object_id=payload.get("object_id"),
                ctx=None,
            )

        # 场景 6：快捷键
        if name == "hotkey":
            return await self.hotkey(
                keys=payload["keys"],
                ctx=None,
            )

        raise ValueError(f"未知工具名称，无法路由: {name}")

    # ══════════════════════════════════════════════════════════
    # § 公开工具方法（由 Worker 串行调用）
    # ══════════════════════════════════════════════════════════

    async def see(self, ctx: Context | None = None) -> ScreenSnapshot:
        """
        读取当前界面状态。

        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 当前状态快照
        """

        await self._report_stage(ctx, 0, "开始读取当前界面状态")
        snapshot = await self._refresh_snapshot(
            ctx=ctx,
            progress_marks=(10, 25, 45, 85, 100),
            phase_label="当前界面状态读取",
        )
        return snapshot

    async def get_current_state(self, ctx: Context | None = None) -> ScreenSnapshot:
        """
        读取当前界面状态（兼容旧接口名，内部调用 see）。

        :return: 当前状态快照
        """

        return await self.see(ctx=ctx)

    async def list_actionable_objects(self, ctx: Context | None = None):
        """
        返回当前可操作对象列表。

        :return: 当前可操作对象列表
        """

        await self._report_stage(ctx, 0, "开始读取当前可操作对象")
        snapshot = await self._refresh_snapshot(
            ctx=ctx,
            progress_marks=(10, 25, 45, 85, 100),
            phase_label="可操作对象读取",
        )
        return snapshot.actionable_objects

    async def execute_action(
        self,
        request: ActionRequest,
        ctx: Context | None = None,
    ) -> ActionResult:
        """
        执行对象级动作闭环。

        :param request: 动作请求对象
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 完整动作结果
        """

        await self._report_stage(
            ctx, 0, f"开始执行对象级动作：{request.action_type.value}"
        )
        self.state_store.set_last_action_request(request)

        # 对象级动作优先复用调用者最近一次读取到的状态快照，
        # 保证"先看见对象，再指定对象执行"的 MCP 语义不被额外重读打断。
        before_snapshot = self.state_store.last_snapshot
        if before_snapshot is None:
            before_snapshot = await self._refresh_snapshot(
                ctx=ctx,
                progress_marks=(5, 10, 20, 30, 35),
                phase_label="动作前状态读取",
            )
        else:
            await self._report_stage(ctx, 35, "复用最近一次状态快照执行对象动作")

        execution_record = await self._execute_object_action(
            request,
            before_snapshot,
            ctx=ctx,
            execution_progress_marks=(40, 60),
        )
        action_result = ActionResult(
            request_id=request.request_id,
            result_status=ResultStatus.SUCCESS,
            result_summary=f"已成功下发动作指令：{request.action_type.value}（请由于MCP防超时机制，主动调用 see 获取动作后的新屏幕状态）",
            change_events=[],
            updated_screen_summary=before_snapshot.screen_summary,
            updated_actionable_objects=before_snapshot.actionable_objects,
            updated_high_priority_objects=before_snapshot.high_priority_objects,
            warnings=["动作已执行；但为避免 MCP 超时断连，服务端已取消全自动画面重读。请主动调用 see 工具刷新状态。"],
            execution_id=execution_record.execution_id,
        )
        return action_result

    async def execute_global_action(
        self,
        request: GlobalActionRequest,
        ctx: Context | None = None,
    ) -> ActionResult:
        """
        执行全局动作闭环。

        :param request: 全局动作请求对象
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 完整动作结果
        """

        await self._report_stage(
            ctx, 0, f"开始执行全局动作：{request.action_type.value}"
        )
        before_snapshot = self.state_store.last_snapshot
        if before_snapshot is None:
            before_snapshot = await self._refresh_snapshot(
                ctx=ctx,
                progress_marks=(5, 10, 20, 30, 35),
                phase_label="全局动作前状态读取",
            )
        else:
            await self._report_stage(ctx, 35, "复用最近一次状态快照执行全局动作")
        execution_record = await self._execute_global_action(
            request,
            ctx=ctx,
            execution_progress_marks=(40, 60),
        )
        self.state_store.set_last_execution_record(execution_record)
        action_result = ActionResult(
            request_id=request.request_id,
            result_status=ResultStatus.SUCCESS,
            result_summary=f"已成功下发全局动作：{request.action_type.value}（请由于MCP防超时机制，主动调用 see 获取动作后的新屏幕状态）",
            change_events=[],
            updated_screen_summary=before_snapshot.screen_summary,
            updated_actionable_objects=before_snapshot.actionable_objects,
            updated_high_priority_objects=before_snapshot.high_priority_objects,
            warnings=["动作已执行；但为避免 MCP 超时断连，服务端已取消全自动画面重读。请主动调用 see 工具刷新状态。"],
            execution_id=execution_record.execution_id,
        )
        return action_result

    async def click(
        self,
        object_id: str,
        button: str = "left",
        ctx: Context | None = None,
    ) -> ActionResult:
        """
        执行极简接口中的单击动作。

        :param object_id: 目标对象 ID
        :param button: 鼠标按键，只允许 left 或 right
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 动作结果
        :raises ValueError: 当按钮参数非法时抛出
        """

        if button == "left":
            action_type = ActionType.CLICK
        elif button == "right":
            action_type = ActionType.RIGHT_CLICK
        else:
            raise ValueError("button 仅支持 left 或 right")

        request = ActionRequest(
            target_object_id=object_id,
            action_type=action_type,
        )
        return await self.execute_action(request, ctx=ctx)

    async def scroll(
        self,
        object_id: str,
        direction: str,
        lines: int = 3,
        ctx: Context | None = None,
    ) -> ActionResult:
        """
        执行极简接口中的滚轮动作。

        :param object_id: 目标对象 ID
        :param direction: 滚动方向，只允许 up 或 down
        :param lines: 滚动行数
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 动作结果
        """

        request = ActionRequest(
            target_object_id=object_id,
            action_type=ActionType.SCROLL,
            action_params={"direction": direction, "lines": lines},
        )
        return await self.execute_action(request, ctx=ctx)

    async def move_to(
        self,
        object_id: str,
        ctx: Context | None = None,
    ) -> ExecutionRecord:
        """
        执行极简接口中的鼠标悬停动作。

        当前动作只负责把鼠标移动到目标对象，不做动作后重观测。

        :param object_id: 目标对象 ID
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 底层执行记录
        """

        request = ActionRequest(
            target_object_id=object_id,
            action_type=ActionType.MOVE_MOUSE,
        )
        await self._report_stage(ctx, 0, "开始移动鼠标到目标对象")
        self.state_store.set_last_action_request(request)
        snapshot = self.state_store.last_snapshot
        if snapshot is None:
            snapshot = await self._refresh_snapshot(
                ctx=ctx,
                progress_marks=(5, 10, 20, 30, 35),
                phase_label="悬停前状态读取",
            )
        else:
            await self._report_stage(ctx, 35, "复用最近一次状态快照执行悬停动作")

        execution_record = await self._execute_object_action(
            request,
            snapshot,
            ctx=ctx,
            execution_progress_marks=(40, 90),
        )
        self._set_state(WorkflowState.COMPLETED)
        self._set_state(WorkflowState.IDLE)
        await self._report_stage(ctx, 100, "鼠标已移动到目标对象")
        return execution_record

    async def type_text(
        self,
        text: str,
        object_id: str | None = None,
        ctx: Context | None = None,
    ) -> ActionResult:
        """
        执行极简接口中的文本输入动作。

        :param text: 待输入文本
        :param object_id: 目标对象 ID；若为空则向当前焦点位置直接输入
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 动作结果
        """

        if object_id is None:
            request = GlobalActionRequest(
                action_type=ActionType.INPUT_TEXT,
                action_params={"text": text},
            )
            return await self.execute_global_action(request, ctx=ctx)

        request = ActionRequest(
            target_object_id=object_id,
            action_type=ActionType.INPUT_TEXT,
            action_params={"text": text},
        )
        return await self.execute_action(request, ctx=ctx)

    async def hotkey(
        self,
        keys: str | list[str],
        ctx: Context | None = None,
    ) -> ActionResult:
        """
        执行极简接口中的组合快捷键动作。

        :param keys: 快捷键字符串或字符串列表
        :param ctx: FastMCP 请求上下文（Worker 调用时为 None）
        :return: 动作结果
        """

        request = GlobalActionRequest(
            action_type=ActionType.HOTKEY,
            action_params={"keys": keys},
        )
        return await self.execute_global_action(request, ctx=ctx)

    async def get_last_action_result(self) -> ActionResult | None:
        """
        获取最近一次动作结果。

        :return: 最近一次动作结果或 None
        """

        return self.state_store.last_action_result

    async def get_last_change_events(self):
        """
        获取最近一次变化事件列表。

        :return: 最近一次变化事件列表
        """

        return self.state_store.last_change_events

    # ══════════════════════════════════════════════════════════
    # § 内部私有方法
    # ══════════════════════════════════════════════════════════

    async def _refresh_snapshot(
        self,
        ctx: Context | None = None,
        progress_marks: tuple[float, float, float, float, float] = (0, 25, 50, 75, 100),
        phase_label: str = "状态读取",
    ) -> ScreenSnapshot:
        """
        刷新当前状态快照（无锁版本，由 Worker 串行调用保证安全）。

        :param ctx: FastMCP 请求上下文
        :param progress_marks: 当前阶段进度锚点
        :param phase_label: 当前阶段名称
        :return: 当前最新状态快照
        """

        self._set_state(WorkflowState.CAPTURING)
        try:
            await self._report_stage(ctx, progress_marks[0], f"{phase_label}：开始截图")
            raw_frames = self.capture_service.capture_frames()
            await self._report_stage(ctx, progress_marks[1], f"{phase_label}：截图完成")
            self._set_state(WorkflowState.UNDERSTANDING)
            await self._report_stage(
                ctx,
                progress_marks[2],
                f"{phase_label}：开始视觉理解",
            )
            frame_results = await self._await_with_heartbeat(
                self._understand_frames(raw_frames),
                ctx=ctx,
                progress=progress_marks[2],
                message=f"{phase_label}：视觉理解仍在执行",
            )
            await self._report_stage(
                ctx,
                progress_marks[3],
                f"{phase_label}：视觉理解完成",
            )
            snapshot = self.semantic_normalizer.build_snapshot_from_frames(
                frame_results=frame_results,
                previous_snapshot=self.state_store.last_snapshot,
            )
            self.state_store.set_last_snapshot(snapshot)
            self._set_state(WorkflowState.READY)
            self._set_state(WorkflowState.COMPLETED)
            self._set_state(WorkflowState.IDLE)
            await self._report_stage(
                ctx,
                progress_marks[4],
                f"{phase_label}：状态快照已就绪",
            )
            return snapshot
        except Exception as exc:
            await self._report_failure(ctx, f"{phase_label}失败：{exc}")
            self._set_state(WorkflowState.FAILED)
            self._set_state(WorkflowState.IDLE)
            raise

    async def _execute_object_action(
        self,
        request: ActionRequest,
        snapshot: ScreenSnapshot,
        ctx: Context | None = None,
        execution_progress_marks: tuple[float, float] = (0, 100),
    ) -> ExecutionRecord:
        """
        执行对象动作。

        :param request: 动作请求对象
        :param snapshot: 动作前快照
        :param ctx: FastMCP 请求上下文
        :param execution_progress_marks: 执行阶段进度锚点
        :return: 执行记录
        """

        self._set_state(WorkflowState.EXECUTING)
        try:
            await self._report_stage(
                ctx,
                execution_progress_marks[0],
                "开始执行对象级动作",
            )
            execution_record = await self._await_with_heartbeat(
                asyncio.to_thread(
                    self.executor.execute_action,
                    request,
                    snapshot,
                ),
                ctx=ctx,
                progress=execution_progress_marks[0],
                message="对象级动作执行仍在进行",
            )
            await self._report_stage(
                ctx,
                execution_progress_marks[1],
                "对象级动作执行完成",
            )
        except Exception as exc:
            await self._report_failure(ctx, f"对象级动作执行失败：{exc}")
            self._set_state(WorkflowState.FAILED)
            self._set_state(WorkflowState.IDLE)
            raise
        self.state_store.set_last_execution_record(execution_record)
        return execution_record

    async def _execute_global_action(
        self,
        request: GlobalActionRequest,
        ctx: Context | None = None,
        execution_progress_marks: tuple[float, float] = (0, 100),
    ) -> ExecutionRecord:
        """
        执行全局动作。

        :param request: 全局动作请求对象
        :param ctx: FastMCP 请求上下文
        :param execution_progress_marks: 执行阶段进度锚点
        :return: 执行记录
        """

        self._set_state(WorkflowState.EXECUTING)
        try:
            await self._report_stage(
                ctx,
                execution_progress_marks[0],
                "开始执行全局动作",
            )
            execution_record = await self._await_with_heartbeat(
                asyncio.to_thread(
                    self.executor.execute_global_action,
                    request,
                ),
                ctx=ctx,
                progress=execution_progress_marks[0],
                message="全局动作执行仍在进行",
            )
            await self._report_stage(
                ctx,
                execution_progress_marks[1],
                "全局动作执行完成",
            )
        except Exception as exc:
            await self._report_failure(ctx, f"全局动作执行失败：{exc}")
            self._set_state(WorkflowState.FAILED)
            self._set_state(WorkflowState.IDLE)
            raise
        self.state_store.set_last_execution_record(execution_record)
        return execution_record

    async def _watch_after_action(
        self,
        request_id: str,
        execution_record: ExecutionRecord,
        expected_outcome: str | None,
        before_snapshot: ScreenSnapshot,
        action_type: ActionType,
        ctx: Context | None = None,
        progress_marks: tuple[float, float, float, float, float, float, float] = (
            0,
            20,
            30,
            40,
            70,
            90,
            100,
        ),
    ) -> ActionResult:
        """
        执行动作后重观测与结果判定。

        :param request_id: 请求 ID
        :param execution_record: 底层执行记录
        :param expected_outcome: 预期结果
        :param before_snapshot: 动作前快照
        :param action_type: 动作类型，用于选择差异化等待时长
        :param ctx: FastMCP 请求上下文
        :param progress_marks: 观察阶段进度锚点
        :return: 完整动作结果
        """

        # 根据动作类型选择等待时长：
        # - CLICK / RIGHT_CLICK 可能触发弹窗或菜单，给 0.5s
        # - HOTKEY / INPUT_TEXT / SCROLL 屏幕几乎即时响应，0.3s 即可
        # - 其余类型使用全局默认（post_action_delay_seconds）
        delay_map: dict[ActionType, float] = {
            ActionType.CLICK: self.config.post_action_delay_click,
            ActionType.RIGHT_CLICK: self.config.post_action_delay_click,
            ActionType.HOTKEY: self.config.post_action_delay_hotkey,
            ActionType.INPUT_TEXT: self.config.post_action_delay_type_text,
            ActionType.SCROLL: self.config.post_action_delay_scroll,
        }
        delay_seconds = delay_map.get(action_type, self.config.post_action_delay_seconds)

        await self._report_stage(ctx, progress_marks[0], "开始等待界面稳定")
        # NOTE: 用 _await_with_heartbeat 包装 sleep，保证等待期间不断线。
        # Worker 侧的 ctx=None 时，sleep 直接执行，不发心跳（MCP 层自有心跳）。
        await self._await_with_heartbeat(
            asyncio.sleep(delay_seconds),
            ctx=ctx,
            progress=progress_marks[0],
            message="等待界面稳定中",
        )
        await self._report_stage(ctx, progress_marks[1], "界面稳定等待完成")
        self._set_state(WorkflowState.WATCHING)
        try:
            await self._report_stage(ctx, progress_marks[2], "开始执行动作后再次观测")
            after_snapshot = await self._refresh_snapshot_without_state_reset(
                previous_snapshot=before_snapshot,
                ctx=ctx,
                progress_marks=(
                    progress_marks[3],
                    progress_marks[4],
                    progress_marks[5],
                    progress_marks[5],
                    progress_marks[5],
                ),
                phase_label="动作后状态读取",
            )
            await self._report_stage(ctx, progress_marks[5], "开始判定动作结果")
            watch_result = self.watcher.watch(
                request_id=request_id,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                execution_record=execution_record,
                expected_outcome=expected_outcome,
            )
            self.state_store.set_last_snapshot(watch_result.updated_snapshot)
            self.state_store.set_last_change_events(watch_result.evidence_events)
            action_result = ActionResult(
                request_id=request_id,
                result_status=watch_result.result_status,
                result_summary=watch_result.result_summary,
                change_events=watch_result.evidence_events,
                updated_screen_summary=watch_result.updated_snapshot.screen_summary,
                updated_actionable_objects=watch_result.updated_snapshot.actionable_objects,
                updated_high_priority_objects=watch_result.updated_snapshot.high_priority_objects,
                warnings=watch_result.warnings,
                execution_id=execution_record.execution_id,
            )
            self.state_store.set_last_action_result(action_result)
            self._set_state(WorkflowState.COMPLETED)
            self._set_state(WorkflowState.IDLE)
            await self._report_stage(ctx, progress_marks[6], "动作结果判定完成")
            return action_result
        except Exception as exc:
            await self._report_failure(ctx, f"动作后观测失败：{exc}")
            self._set_state(WorkflowState.FAILED)
            self._set_state(WorkflowState.IDLE)
            raise

    async def _refresh_snapshot_without_state_reset(
        self,
        previous_snapshot: ScreenSnapshot,
        ctx: Context | None = None,
        progress_marks: tuple[float, float, float, float, float] = (0, 25, 50, 75, 100),
        phase_label: str = "状态读取",
    ) -> ScreenSnapshot:
        """
        在动作后观察阶段刷新状态，但不提前回到 idle。

        :param previous_snapshot: 动作前快照
        :param ctx: FastMCP 请求上下文
        :param progress_marks: 当前阶段进度锚点
        :param phase_label: 当前阶段名称
        :return: 新的动作后快照
        """

        self._set_state(WorkflowState.CAPTURING)
        await self._report_stage(ctx, progress_marks[0], f"{phase_label}：开始截图")
        raw_frames = self.capture_service.capture_frames()
        await self._report_stage(ctx, progress_marks[1], f"{phase_label}：截图完成")
        self._set_state(WorkflowState.UNDERSTANDING)
        await self._report_stage(ctx, progress_marks[2], f"{phase_label}：开始视觉理解")
        frame_results = await self._await_with_heartbeat(
            self._understand_frames(raw_frames),
            ctx=ctx,
            progress=progress_marks[2],
            message=f"{phase_label}：视觉理解仍在执行",
        )
        await self._report_stage(ctx, progress_marks[3], f"{phase_label}：视觉理解完成")
        snapshot = self.semantic_normalizer.build_snapshot_from_frames(
            frame_results=frame_results,
            previous_snapshot=previous_snapshot,
        )
        self._set_state(WorkflowState.READY)
        await self._report_stage(
            ctx, progress_marks[4], f"{phase_label}：状态快照已就绪"
        )
        return snapshot

    async def _understand_frames(
        self,
        raw_frames: list[RawFrame],
    ) -> list[tuple[RawFrame, PerceptionResult]]:
        """
        对一组屏幕帧逐张执行视觉理解，并返回帧与结果配对列表。

        当前多屏实现按显示器分别调用模型，避免把多块屏幕先合并成一张大图。

        :param raw_frames: 原始帧列表
        :return: 帧与视觉结果配对列表
        """

        if not raw_frames:
            return []

        per_frame_max_objects = max(1, self.config.max_objects // len(raw_frames))
        perceptions = await asyncio.gather(
            *[
                self.perception_service.understand(
                    raw_frame,
                    max_objects=per_frame_max_objects,
                )
                for raw_frame in raw_frames
            ]
        )
        return list(zip(raw_frames, perceptions))

    async def _report_stage(
        self,
        ctx: Context | None,
        progress: float,
        message: str,
    ) -> None:
        """
        向 MCP 客户端同时发送阶段日志与进度。

        Worker 执行时 ctx=None，本方法直接返回，不发送任何消息。
        心跳统一由 MCP 层的 _await_future_with_heartbeat 承担。

        :param ctx: FastMCP 请求上下文
        :param progress: 当前阶段进度值
        :param message: 阶段说明文本
        """

        if ctx is None:
            return
        await ctx.info(message)
        await ctx.report_progress(
            progress=progress,
            total=DEFAULT_PROGRESS_TOTAL,
            message=message,
        )

    async def _report_failure(self, ctx: Context | None, message: str) -> None:
        """
        向 MCP 客户端发送失败日志。

        :param ctx: FastMCP 请求上下文
        :param message: 失败说明文本
        """

        if ctx is None:
            return
        await ctx.error(message)

    async def _await_with_heartbeat(
        self,
        operation: Awaitable[ProgressValueT],
        ctx: Context | None,
        progress: float,
        message: str,
    ) -> ProgressValueT:
        """
        在等待异步操作期间持续向客户端发送心跳。

        Worker 执行时 ctx=None，直接 await 操作，心跳由 MCP 层承担。

        :param operation: 待等待的异步操作
        :param ctx: FastMCP 请求上下文
        :param progress: 当前阶段进度值
        :param message: 心跳消息文本
        :return: 异步操作返回值
        """

        if ctx is None:
            # Worker 侧：直接执行，MCP 层自有心跳
            return await operation

        stop_event = asyncio.Event()

        async def _heartbeat() -> None:
            while not stop_event.is_set():
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                if stop_event.is_set():
                    return
                await ctx.info(message)
                await ctx.report_progress(
                    progress=progress,
                    total=DEFAULT_PROGRESS_TOTAL,
                    message=message,
                )

        heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            return await operation
        finally:
            stop_event.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    def _set_state(self, new_state: WorkflowState) -> None:
        """
        设置当前状态机状态。

        :param new_state: 新状态
        """

        self.workflow_state = new_state
