"""
模块名称：models
功能描述：
    定义第一阶段实现中的核心数据结构。
    当前模块统一维护内部状态对象、执行对象以及对外返回对象，确保各模块字段语义一致。

主要组件：
    - RawFrame: 屏幕采样结果。
    - PerceptionResult: 视觉理解结果。
    - SemanticObject: 语义对象。
    - ScreenSnapshot: 当前界面状态快照。
    - ActionRequest / ActionResult: 动作请求与动作结果。

依赖说明：
    - pydantic: 用于数据模型定义、类型校验和 JSON 序列化。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化第一阶段数据模型。
    - 2026-04-18 JucieOvo: 收敛 ActionType：删除 double_click/long_press/drag，新增 scroll；INPUT_TEXT 保留在全局白名单，用于无焦点对象时直接向当前焦点输入文本。
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from ezcomputerctrl.config import NORMALIZED_COORDINATE_SCALE


def _new_id(prefix: str) -> str:
    """
    生成结构化 ID。

    :param prefix: ID 前缀
    :return: 结构化唯一标识
    """

    return f"{prefix}_{uuid4().hex}"


def _utc_now() -> datetime:
    """
    生成统一的 UTC 时间戳。

    :return: 带时区的当前 UTC 时间
    """

    return datetime.now(timezone.utc)


class GUIObjectType(str, Enum):
    """第一阶段允许的对象类型枚举。"""

    ACTION_AREA = "action_area"
    TAB_HEADER = "tab_header"


class GUIObjectState(str, Enum):
    """第一阶段允许的对象状态枚举。"""

    ENABLED = "enabled"
    DISABLED = "disabled"
    SELECTED = "selected"
    UNSELECTED = "unselected"
    FOCUSED = "focused"
    EXPANDED = "expanded"
    COLLAPSED = "collapsed"
    LOADING = "loading"
    EDITABLE = "editable"
    READONLY = "readonly"
    VISIBLE = "visible"
    HIDDEN = "hidden"


class RiskTag(str, Enum):
    """第一阶段允许的风险标签枚举。"""

    DESTRUCTIVE = "destructive"
    SUBMIT = "submit"
    EXTERNAL_SEND = "external_send"
    OVERWRITE = "overwrite"
    PAYMENT_RELATED = "payment_related"
    LOGOUT = "logout"
    INSTALL_OR_UNINSTALL = "install_or_uninstall"


class ActionType(str, Enum):
    """第一阶段允许的动作类型枚举。"""

    CLICK = "click"
    RIGHT_CLICK = "right_click"
    SCROLL = "scroll"
    INPUT_TEXT = "input_text"
    MOVE_MOUSE = "move_mouse"
    HOTKEY = "hotkey"


OBJECT_ACTION_TYPES = {
    ActionType.CLICK,
    ActionType.RIGHT_CLICK,
    ActionType.SCROLL,
    ActionType.INPUT_TEXT,
    ActionType.MOVE_MOUSE,
}
GLOBAL_ACTION_TYPES = {ActionType.INPUT_TEXT, ActionType.HOTKEY}


class ChangeEventType(str, Enum):
    """第一阶段允许的变化事件类型枚举。"""

    OBJECT_APPEARED = "object_appeared"
    OBJECT_DISAPPEARED = "object_disappeared"
    OBJECT_STATE_CHANGED = "object_state_changed"
    FOCUS_CHANGED = "focus_changed"
    DIALOG_OPENED = "dialog_opened"
    DIALOG_CLOSED = "dialog_closed"
    PAGE_SWITCHED = "page_switched"
    LOADING_STARTED = "loading_started"
    LOADING_FINISHED = "loading_finished"
    ERROR_APPEARED = "error_appeared"
    WARNING_APPEARED = "warning_appeared"
    SUCCESS_FEEDBACK_APPEARED = "success_feedback_appeared"


class ResultStatus(str, Enum):
    """动作结果状态枚举。"""

    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"
    NEED_CONFIRMATION = "need_confirmation"


class ExecutionStatus(str, Enum):
    """底层执行状态枚举。"""

    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowState(str, Enum):
    """第一阶段显式状态机枚举。"""

    IDLE = "idle"
    CAPTURING = "capturing"
    UNDERSTANDING = "understanding"
    READY = "ready"
    EXECUTING = "executing"
    WATCHING = "watching"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportanceLevel(str, Enum):
    """变化事件的重要级别枚举。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NormalizedBBox(BaseModel):
    """
    归一化边界框。

    当前实现要求视觉模型输出的坐标统一采用 0 到 1000 的整数比例尺，避免直接依赖具体屏幕分辨率。
    """

    x1: int = Field(..., ge=0, le=NORMALIZED_COORDINATE_SCALE)
    y1: int = Field(..., ge=0, le=NORMALIZED_COORDINATE_SCALE)
    x2: int = Field(..., ge=0, le=NORMALIZED_COORDINATE_SCALE)
    y2: int = Field(..., ge=0, le=NORMALIZED_COORDINATE_SCALE)

    @model_validator(mode="after")
    def validate_bbox_order(self) -> "NormalizedBBox":
        """
        校验边界框顺序。

        :return: 当前对象自身
        :raises ValueError: 当边界框坐标顺序非法时抛出
        """

        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("归一化边界框要求 x2 > x1 且 y2 > y1")
        return self


class PixelBBox(BaseModel):
    """像素级边界框。"""

    x1: int
    y1: int
    x2: int
    y2: int

    @model_validator(mode="after")
    def validate_bbox_order(self) -> "PixelBBox":
        """
        校验像素边界框顺序。

        :return: 当前对象自身
        :raises ValueError: 当边界框坐标顺序非法时抛出
        """

        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("像素边界框要求 x2 > x1 且 y2 > y1")
        return self

    @property
    def center(self) -> tuple[int, int]:
        """
        计算边界框中心点。

        :return: 边界框中心点坐标
        """

        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


class WindowInfo(BaseModel):
    """从操作系统获取的窗口信息层级。"""

    title: str
    bounds: PixelBBox
    is_foreground: bool


class RawFrame(BaseModel):
    """一次真实屏幕采样结果。"""

    frame_id: str = Field(default_factory=lambda: _new_id("frame"))
    captured_at: datetime = Field(default_factory=_utc_now)
    image_bytes: bytes
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    origin_x: int = 0
    origin_y: int = 0
    screen_id: str = "screen_0"
    source: str
    image_format: str = "PNG"
    active_window_hint: str | None = None
    visible_windows: list[WindowInfo] = Field(default_factory=list)

    def to_data_url(self) -> str:
        """
        将图像内容转换为 data URL，供多模态模型调用使用。

        :return: PNG data URL 字符串
        """

        encoded = base64.b64encode(self.image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"


class CandidateObject(BaseModel):
    """视觉模型输出的原始候选对象。"""

    candidate_id: str
    raw_name: str
    raw_type: GUIObjectType
    raw_description: str
    group: str
    location_hint: str
    state: list[GUIObjectState] = Field(default_factory=list)
    actions: list[ActionType] = Field(default_factory=list)
    visible: bool = True
    risk: list[RiskTag] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: NormalizedBBox
    text: str | None = None

    @field_validator("raw_name", "raw_description", "group", "location_hint")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        """
        校验核心文本字段不能为空。

        :param value: 待校验文本
        :return: 去除首尾空白后的文本
        :raises ValueError: 当文本为空时抛出
        """

        normalized = value.strip()
        if not normalized:
            raise ValueError("候选对象核心文本字段不能为空")
        return normalized


class PerceptionResult(BaseModel):
    """一次视觉理解的完整结果。"""

    frame_id: str
    scene_label: str
    main_regions: list[str] = Field(default_factory=list)
    candidate_objects: list[CandidateObject] = Field(default_factory=list)
    summary_draft: str
    warnings: list[str] = Field(default_factory=list)


class SemanticObject(BaseModel):
    """对外可引用的标准语义对象。"""

    id: str
    name: str
    type: GUIObjectType
    description: str
    group: str
    location_hint: str
    window_hint: str | None = None
    state: list[GUIObjectState] = Field(default_factory=list)
    actions: list[ActionType] = Field(default_factory=list)
    visible: bool = True
    risk: list[RiskTag] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    internal_bbox: PixelBBox
    source_candidate_id: str | None = None


class ScreenSummary(BaseModel):
    """当前界面的高价值摘要。"""

    scene_name: str
    main_regions: list[str] = Field(default_factory=list)
    focus_object_id: str | None = None
    overlay_present: bool = False
    prominent_change: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ChangeEvent(BaseModel):
    """动作前后或状态前后的语义变化事件。"""

    event_id: str = Field(default_factory=lambda: _new_id("event"))
    event_type: ChangeEventType
    target_object_id: str | None = None
    group: str
    description: str
    importance: ImportanceLevel
    confidence: float = Field(..., ge=0.0, le=1.0)


class ScreenSnapshot(BaseModel):
    """某一时刻对外可消费的完整状态快照。"""

    snapshot_id: str = Field(default_factory=lambda: _new_id("snapshot"))
    captured_at: datetime = Field(default_factory=_utc_now)
    frame_id: str
    screen_summary: ScreenSummary
    actionable_objects: list[SemanticObject] = Field(default_factory=list)
    high_priority_objects: list[SemanticObject] = Field(default_factory=list)
    change_events: list[ChangeEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ActionRequest(BaseModel):
    """来自上层的标准动作请求。"""

    request_id: str = Field(default_factory=lambda: _new_id("request"))
    target_object_id: str | None = None
    action_type: ActionType
    action_params: dict[str, object] = Field(default_factory=dict)
    expected_outcome: str | None = None
    requested_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_object_action_request(self) -> "ActionRequest":
        """
        校验对象级动作请求是否合法。

        :return: 当前请求对象
        :raises ValueError: 当动作类型不属于对象级白名单或目标对象缺失时抛出
        """

        if self.action_type not in OBJECT_ACTION_TYPES:
            raise ValueError(
                f"对象级动作仅支持: {', '.join(action.value for action in OBJECT_ACTION_TYPES)}"
            )
        if not self.target_object_id:
            raise ValueError("对象级动作必须提供 target_object_id")
        return self


class GlobalActionRequest(BaseModel):
    """不依赖单一语义对象的全局动作请求。"""

    request_id: str = Field(default_factory=lambda: _new_id("global_request"))
    action_type: ActionType
    action_params: dict[str, object] = Field(default_factory=dict)
    expected_outcome: str | None = None
    requested_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_global_action_request(self) -> "GlobalActionRequest":
        """
        校验全局动作请求是否合法。

        :return: 当前请求对象
        :raises ValueError: 当动作类型不属于全局白名单时抛出
        """

        if self.action_type not in GLOBAL_ACTION_TYPES:
            raise ValueError(
                f"全局动作仅支持: {', '.join(action.value for action in GLOBAL_ACTION_TYPES)}"
            )
        return self


class ExecutionRecord(BaseModel):
    """底层执行器的真实执行记录。"""

    execution_id: str = Field(default_factory=lambda: _new_id("execution"))
    request_id: str
    target_object_id: str | None = None
    action_type: ActionType
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
    execution_status: ExecutionStatus
    notes: list[str] = Field(default_factory=list)


class WatchResult(BaseModel):
    """结果监看器对动作后界面的解释结果。"""

    watch_id: str = Field(default_factory=lambda: _new_id("watch"))
    request_id: str
    result_status: ResultStatus
    result_summary: str
    evidence_events: list[ChangeEvent] = Field(default_factory=list)
    updated_snapshot: ScreenSnapshot
    warnings: list[str] = Field(default_factory=list)


class ActionResult(BaseModel):
    """最终返回给上层的动作结果。"""

    request_id: str
    result_status: ResultStatus
    result_summary: str
    change_events: list[ChangeEvent] = Field(default_factory=list)
    updated_screen_summary: ScreenSummary
    updated_actionable_objects: list[SemanticObject] = Field(default_factory=list)
    updated_high_priority_objects: list[SemanticObject] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_id: str | None = None
