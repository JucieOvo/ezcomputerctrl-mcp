"""
模块名称：state_store
功能描述：
    提供第一阶段进程内状态存储。
    当前实现只保存最近一次快照、动作请求、动作结果、变化事件和执行记录，不做持久化。

主要组件：
    - InMemoryStateStore: 进程内状态存储器。

依赖说明：
    - 无额外第三方依赖。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化进程内状态存储。
"""

from __future__ import annotations

from ezcomputerctrl.models import (
    ActionRequest,
    ActionResult,
    ChangeEvent,
    ExecutionRecord,
    ScreenSnapshot,
)


class InMemoryStateStore:
    """
    第一阶段进程内状态存储。

    当前设计只维护最近一次状态，严格对应第一阶段串行闭环需求。
    """

    def __init__(self) -> None:
        """初始化空状态存储。"""

        self.last_snapshot: ScreenSnapshot | None = None
        self.last_action_request: ActionRequest | None = None
        self.last_action_result: ActionResult | None = None
        self.last_change_events: list[ChangeEvent] = []
        self.last_execution_record: ExecutionRecord | None = None

    def set_last_snapshot(self, snapshot: ScreenSnapshot) -> None:
        """
        保存最近一次状态快照。

        :param snapshot: 当前状态快照
        """

        self.last_snapshot = snapshot

    def set_last_action_request(self, request: ActionRequest) -> None:
        """
        保存最近一次动作请求。

        :param request: 动作请求对象
        """

        self.last_action_request = request

    def set_last_action_result(self, result: ActionResult) -> None:
        """
        保存最近一次动作结果。

        :param result: 动作结果对象
        """

        self.last_action_result = result

    def set_last_change_events(self, events: list[ChangeEvent]) -> None:
        """
        保存最近一次变化事件列表。

        :param events: 变化事件列表
        """

        self.last_change_events = events

    def set_last_execution_record(self, record: ExecutionRecord) -> None:
        """
        保存最近一次执行记录。

        :param record: 底层执行记录
        """

        self.last_execution_record = record
