"""
模块名称：watcher
功能描述：
    负责在动作执行后比较前后状态，生成变化事件并判定最终结果状态。
    当前实现显式区分底层执行完成与业务结果达成，不把动作发出视为成功。

主要组件：
    - ActionWatcher: 动作结果监看器。

依赖说明：
    - 无额外第三方依赖。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化第一阶段结果监看逻辑。
"""

from __future__ import annotations

from ezcomputerctrl.models import (
    ChangeEvent,
    ChangeEventType,
    ExecutionRecord,
    ExecutionStatus,
    GUIObjectState,
    ImportanceLevel,
    ResultStatus,
    RiskTag,
    ScreenSnapshot,
    SemanticObject,
    WatchResult,
)


ERROR_KEYWORDS = {"error", "failed", "invalid", "错误", "失败", "异常", "不可用"}
SUCCESS_KEYWORDS = {"success", "saved", "completed", "成功", "完成", "已保存", "已提交"}
CONFIRMATION_KEYWORDS = {"确认", "删除", "提交", "发送", "覆盖", "退出", "付款"}


class ActionWatcher:
    """
    动作结果监看器。

    当前监看器只依据前后状态快照与执行记录给出结构化结论，不依赖模型历史记忆。
    """

    def watch(
        self,
        request_id: str,
        before_snapshot: ScreenSnapshot,
        after_snapshot: ScreenSnapshot,
        execution_record: ExecutionRecord,
        expected_outcome: str | None,
    ) -> WatchResult:
        """
        对动作结果执行监看和判定。

        :param request_id: 当前动作请求 ID
        :param before_snapshot: 动作前快照
        :param after_snapshot: 动作后快照
        :param execution_record: 底层执行记录
        :param expected_outcome: 预期结果描述
        :return: 结构化监看结果
        """

        change_events = self._build_change_events(before_snapshot, after_snapshot)
        updated_snapshot = after_snapshot.model_copy(
            update={"change_events": change_events}
        )
        result_status, result_summary, warnings = self._decide_result(
            updated_snapshot,
            change_events,
            execution_record,
            expected_outcome,
        )
        return WatchResult(
            request_id=request_id,
            result_status=result_status,
            result_summary=result_summary,
            evidence_events=change_events,
            updated_snapshot=updated_snapshot,
            warnings=warnings,
        )

    def _build_change_events(
        self,
        before_snapshot: ScreenSnapshot,
        after_snapshot: ScreenSnapshot,
    ) -> list[ChangeEvent]:
        """
        比较动作前后快照并生成变化事件。

        :param before_snapshot: 动作前快照
        :param after_snapshot: 动作后快照
        :return: 变化事件列表
        """

        events: list[ChangeEvent] = []
        before_map = {obj.id: obj for obj in before_snapshot.actionable_objects}
        after_map = {obj.id: obj for obj in after_snapshot.actionable_objects}

        for object_id, after_object in after_map.items():
            if object_id not in before_map:
                events.append(
                    ChangeEvent(
                        event_type=ChangeEventType.OBJECT_APPEARED,
                        target_object_id=object_id,
                        group=after_object.group,
                        description=f"对象出现：{after_object.name}",
                        importance=ImportanceLevel.MEDIUM,
                        confidence=after_object.confidence,
                    )
                )
                if self._is_error_object(after_object):
                    events.append(
                        ChangeEvent(
                            event_type=ChangeEventType.ERROR_APPEARED,
                            target_object_id=object_id,
                            group=after_object.group,
                            description=f"错误提示出现：{after_object.name}",
                            importance=ImportanceLevel.HIGH,
                            confidence=after_object.confidence,
                        )
                    )
                if self._is_success_object(after_object):
                    events.append(
                        ChangeEvent(
                            event_type=ChangeEventType.SUCCESS_FEEDBACK_APPEARED,
                            target_object_id=object_id,
                            group=after_object.group,
                            description=f"成功反馈出现：{after_object.name}",
                            importance=ImportanceLevel.MEDIUM,
                            confidence=after_object.confidence,
                        )
                    )

        for object_id, before_object in before_map.items():
            if object_id not in after_map:
                events.append(
                    ChangeEvent(
                        event_type=ChangeEventType.OBJECT_DISAPPEARED,
                        target_object_id=object_id,
                        group=before_object.group,
                        description=f"对象消失：{before_object.name}",
                        importance=ImportanceLevel.MEDIUM,
                        confidence=before_object.confidence,
                    )
                )

        for object_id, after_object in after_map.items():
            before_object = before_map.get(object_id)
            if before_object is None:
                continue
            if before_object.state != after_object.state:
                events.append(
                    ChangeEvent(
                        event_type=ChangeEventType.OBJECT_STATE_CHANGED,
                        target_object_id=object_id,
                        group=after_object.group,
                        description=(
                            f"对象状态变化：{after_object.name}，"
                            f"{self._format_state(before_object.state)} -> {self._format_state(after_object.state)}"
                        ),
                        importance=ImportanceLevel.MEDIUM,
                        confidence=min(
                            before_object.confidence, after_object.confidence
                        ),
                    )
                )

        before_focus = before_snapshot.screen_summary.focus_object_id
        after_focus = after_snapshot.screen_summary.focus_object_id
        if before_focus != after_focus and after_focus is not None:
            focus_object = after_map.get(after_focus)
            focus_group = focus_object.group if focus_object else "unknown"
            focus_name = focus_object.name if focus_object else after_focus
            events.append(
                ChangeEvent(
                    event_type=ChangeEventType.FOCUS_CHANGED,
                    target_object_id=after_focus,
                    group=focus_group,
                    description=f"焦点切换到：{focus_name}",
                    importance=ImportanceLevel.LOW,
                    confidence=focus_object.confidence if focus_object else 0.6,
                )
            )

        return events

    def _decide_result(
        self,
        updated_snapshot: ScreenSnapshot,
        change_events: list[ChangeEvent],
        execution_record: ExecutionRecord,
        expected_outcome: str | None,
    ) -> tuple[ResultStatus, str, list[str]]:
        """
        根据执行记录和变化事件决定最终结果。

        :param updated_snapshot: 更新后的动作后快照
        :param change_events: 变化事件列表
        :param execution_record: 底层执行记录
        :param expected_outcome: 预期结果描述
        :return: 结果状态、结果摘要和警告列表
        """

        warnings = list(updated_snapshot.warnings)
        if execution_record.execution_status == ExecutionStatus.FAILED:
            return ResultStatus.FAILURE, "底层动作执行失败", warnings

        if any(
            event.event_type == ChangeEventType.ERROR_APPEARED
            for event in change_events
        ):
            return ResultStatus.FAILURE, "动作后出现错误提示，判定执行失败", warnings

        if self._requires_confirmation(change_events, updated_snapshot):
            warnings.append("检测到高风险确认态，需要上层进一步确认")
            return (
                ResultStatus.NEED_CONFIRMATION,
                "动作后出现高风险确认态，需要确认",
                warnings,
            )

        if expected_outcome:
            if self._matches_expected_outcome(
                expected_outcome, updated_snapshot, change_events
            ):
                return ResultStatus.SUCCESS, "动作结果与预期结果匹配", warnings
            if change_events:
                return (
                    ResultStatus.UNCERTAIN,
                    "界面已发生变化，但尚不足以证明已达到预期结果",
                    warnings,
                )
            return ResultStatus.FAILURE, "动作后未观察到满足预期的界面证据", warnings

        if any(
            event.event_type == ChangeEventType.SUCCESS_FEEDBACK_APPEARED
            for event in change_events
        ):
            return ResultStatus.SUCCESS, "动作后出现明确成功反馈", warnings

        if change_events:
            return ResultStatus.SUCCESS, "动作后观察到有效界面变化", warnings

        return (
            ResultStatus.UNCERTAIN,
            "底层动作已执行，但当前未观察到足够界面变化",
            warnings,
        )

    def _requires_confirmation(self, change_events: list[ChangeEvent], snapshot: ScreenSnapshot) -> bool:
        """
        判断当前快照是否进入需要确认的高风险状态。

        :param change_events: 变化事件列表
        :param snapshot: 动作后快照
        :return: 是否需要确认
        """

        new_object_ids = {
            event.target_object_id
            for event in change_events
            if event.event_type == ChangeEventType.OBJECT_APPEARED and event.target_object_id
        }

        for obj in snapshot.actionable_objects:
            if obj.id in new_object_ids:
                if any(
                    risk in obj.risk
                    for risk in {
                        RiskTag.DESTRUCTIVE,
                        RiskTag.SUBMIT,
                        RiskTag.OVERWRITE,
                        RiskTag.PAYMENT_RELATED,
                        RiskTag.EXTERNAL_SEND,
                    }
                ):
                    return True
                combined_text = self._object_text(obj)
                if any(keyword in combined_text for keyword in CONFIRMATION_KEYWORDS):
                    return True
        return False

    def _matches_expected_outcome(
        self,
        expected_outcome: str,
        snapshot: ScreenSnapshot,
        change_events: list[ChangeEvent],
    ) -> bool:
        """
        用最小可解释规则匹配预期结果。

        :param expected_outcome: 预期结果文本
        :param snapshot: 动作后快照
        :param change_events: 变化事件列表
        :return: 是否匹配成功
        """

        normalized_expected = self._normalize_text(expected_outcome)
        if not normalized_expected:
            return False

        prominent_change = snapshot.screen_summary.prominent_change or ""
        if normalized_expected in self._normalize_text(prominent_change):
            return True
        if normalized_expected in self._normalize_text(
            snapshot.screen_summary.scene_name
        ):
            return True
        for event in change_events:
            if normalized_expected in self._normalize_text(event.description):
                return True
        for obj in snapshot.actionable_objects:
            if normalized_expected in self._object_text(obj):
                return True
        return False

    def _is_error_object(self, obj: SemanticObject) -> bool:
        """
        判断对象是否属于错误反馈对象。

        :param obj: 语义对象
        :return: 是否属于错误反馈
        """

        return any(keyword in self._object_text(obj) for keyword in ERROR_KEYWORDS)

    def _is_success_object(self, obj: SemanticObject) -> bool:
        """
        判断对象是否属于成功反馈对象。

        :param obj: 语义对象
        :return: 是否属于成功反馈
        """

        return any(keyword in self._object_text(obj) for keyword in SUCCESS_KEYWORDS)

    def _object_text(self, obj: SemanticObject) -> str:
        """
        组装对象相关文本并做归一化。

        :param obj: 语义对象
        :return: 归一化文本
        """

        return self._normalize_text(
            " ".join([obj.name, obj.description, obj.group, obj.location_hint])
        )

    def _normalize_text(self, value: str) -> str:
        """
        对文本执行最小归一化。

        :param value: 原始文本
        :return: 归一化文本
        """

        return " ".join(value.strip().lower().split())

    def _format_state(self, states: list[GUIObjectState]) -> str:
        """
        格式化对象状态列表。

        :param states: 对象状态列表
        :return: 逗号拼接后的状态文本
        """

        return ",".join(state.value for state in states) or "none"
