"""
模块名称：executor
功能描述：
    负责将 MCP 动作请求映射为 Windows 桌面的真实鼠标键盘输入。
    当前版本严格实现“手”层能力：只按目标对象 bbox 中心点执行动作，不做任何语义推断。

主要组件：
    - DesktopExecutor: 底层执行器。

依赖说明：
    - ctypes: 用于调用 Windows 输入控制接口。
    - time: 用于控制输入之间的最小间隔。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化第一阶段真实动作执行器。
    - 2026-04-17 JucieOvo: 收敛为纯 bbox 中心点手部执行器。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Any

from ezcomputerctrl.models import (
    ActionRequest,
    ActionType,
    ExecutionRecord,
    ExecutionStatus,
    GlobalActionRequest,
    ScreenSnapshot,
    SemanticObject,
)


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
DEFAULT_INPUT_INTERVAL_SECONDS = 0.05
FUNCTION_KEY_BASE = 0x70
ULONG_PTR = ctypes.c_size_t
WHEEL_DELTA = 120


class ExecutionError(RuntimeError):
    """底层动作执行失败异常。"""


class _KEYBDINPUT(ctypes.Structure):
    """Windows 键盘输入结构。"""

    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    """Windows 鼠标输入结构。"""

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    """Windows 硬件输入结构。"""

    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    """Windows 输入联合结构。"""

    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    """Windows 输入结构。"""

    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


class DesktopExecutor:
    """
    Windows 桌面输入执行器。

    当前执行器只负责真实动作执行，不负责动作成败判断。
    所有对象级鼠标类动作都严格基于目标对象 bbox 中心点执行。
    """

    def __init__(self) -> None:
        """初始化底层输入执行器。"""

        self._user32 = ctypes.windll.user32

    def execute_action(
        self,
        request: ActionRequest,
        snapshot: ScreenSnapshot,
    ) -> ExecutionRecord:
        """
        执行对象级动作请求。

        :param request: 动作请求对象
        :param snapshot: 当前状态快照
        :return: 底层执行记录
        :raises ExecutionError: 当动作执行失败时抛出
        """

        record = ExecutionRecord(
            request_id=request.request_id,
            target_object_id=request.target_object_id,
            action_type=request.action_type,
            execution_status=ExecutionStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
        )
        try:
            self._dispatch_object_action(request, snapshot, record)
        except Exception as exc:
            record.execution_status = ExecutionStatus.FAILED
            record.finished_at = datetime.now(timezone.utc)
            record.notes.append(str(exc))
            raise ExecutionError(str(exc)) from exc

        record.finished_at = datetime.now(timezone.utc)
        return record

    def execute_global_action(self, request: GlobalActionRequest) -> ExecutionRecord:
        """
        执行全局动作请求。

        :param request: 全局动作请求对象
        :return: 底层执行记录
        :raises ExecutionError: 当动作执行失败时抛出
        """

        record = ExecutionRecord(
            request_id=request.request_id,
            action_type=request.action_type,
            execution_status=ExecutionStatus.COMPLETED,
            started_at=datetime.now(timezone.utc),
        )
        try:
            if request.action_type == ActionType.HOTKEY:
                self._send_hotkey(self._extract_hotkey_keys(request.action_params))
                record.notes.append("已执行全局快捷键动作")
            elif request.action_type == ActionType.INPUT_TEXT:
                self._send_text(self._extract_text(request.action_params))
                record.notes.append("已向当前焦点位置输入文本")
            else:
                raise ExecutionError(
                    f"当前全局动作尚未实现: {request.action_type.value}"
                )
        except Exception as exc:
            record.execution_status = ExecutionStatus.FAILED
            record.finished_at = datetime.now(timezone.utc)
            record.notes.append(str(exc))
            raise ExecutionError(str(exc)) from exc

        record.finished_at = datetime.now(timezone.utc)
        return record

    def _dispatch_object_action(
        self,
        request: ActionRequest,
        snapshot: ScreenSnapshot,
        record: ExecutionRecord,
    ) -> None:
        """
        路由对象级动作。

        :param request: 动作请求对象
        :param snapshot: 当前快照
        :param record: 底层执行记录
        :raises ExecutionError: 当动作不支持或目标对象不存在时抛出
        """

        target = self._resolve_target_object(request.target_object_id, snapshot)
        center_x, center_y = target.internal_bbox.center

        if request.action_type == ActionType.CLICK:
            self._left_click_point(center_x, center_y)
            record.notes.append(f"已单击目标对象中心点 {target.id}")
            return

        if request.action_type == ActionType.RIGHT_CLICK:
            self._right_click_point(center_x, center_y)
            record.notes.append(f"已右击目标对象中心点 {target.id}")
            return

        if request.action_type == ActionType.SCROLL:
            direction, lines = self._extract_scroll_params(request.action_params)
            self._scroll_at_point(center_x, center_y, direction, lines)
            record.notes.append(
                f"已在目标对象中心点滚动 {target.id}，方向 {direction}，行数 {lines}"
            )
            return

        if request.action_type == ActionType.INPUT_TEXT:
            text = self._extract_text(request.action_params)
            
            # 焦点兜底：强制将目标坐标所属顶层窗口激活为前台
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            pt = POINT(int(center_x), int(center_y))
            hwnd = self._user32.WindowFromPoint(pt)
            if hwnd:
                root_hwnd = self._user32.GetAncestor(hwnd, 2) # GA_ROOT = 2
                if root_hwnd:
                    self._user32.SetForegroundWindow(root_hwnd)
                    
            self._left_click_point(center_x, center_y)
            time.sleep(0.3) # 给足焦点获取时间
            if text:
                self._send_text(text)
            record.notes.append(f"已向目标对象中心点输入文本 {target.id}")
            return

        if request.action_type == ActionType.MOVE_MOUSE:
            self._move_cursor(center_x, center_y)
            record.notes.append(f"已移动鼠标到目标对象中心点 {target.id}")
            return

        raise ExecutionError(f"当前动作尚未实现: {request.action_type.value}")

    def _resolve_target_object(
        self,
        target_object_id: str | None,
        snapshot: ScreenSnapshot,
    ) -> SemanticObject:
        """
        根据对象 ID 解析当前目标对象。

        第一版本不允许使用上一轮快照兜底，也不允许改点别的对象。

        :param target_object_id: 目标对象 ID
        :param snapshot: 当前快照
        :return: 命中的语义对象
        :raises ExecutionError: 当对象不存在时抛出
        """

        if not target_object_id:
            raise ExecutionError("对象级动作缺少 target_object_id")
        for obj in snapshot.actionable_objects:
            if obj.id == target_object_id:
                return obj
        raise ExecutionError(f"未在当前快照中找到目标对象: {target_object_id}")

    def _extract_text(self, action_params: dict[str, Any]) -> str:
        """
        提取文本输入参数。

        :param action_params: 动作参数
        :return: 待输入文本
        :raises ExecutionError: 当参数缺失或非法时抛出
        """

        text = action_params.get("text")
        if not isinstance(text, str):
            raise ExecutionError("input_text 动作必须提供字符串类型的 text 参数")
        return text

    def _extract_scroll_params(self, action_params: dict[str, Any]) -> tuple[str, int]:
        """
        提取滚轮方向与行数参数。

        :param action_params: 动作参数
        :return: 滚动方向与滚动行数
        :raises ExecutionError: 当参数缺失或非法时抛出
        """

        direction = action_params.get("direction")
        lines = action_params.get("lines")
        if direction not in {"up", "down"}:
            raise ExecutionError("scroll 动作必须提供 direction，且值只能为 up 或 down")
        if not isinstance(lines, int) or lines <= 0:
            raise ExecutionError("scroll 动作必须提供正整数 lines 参数")
        return direction, lines

    def _left_click_point(self, x: int, y: int) -> None:
        """
        在指定点执行左键单击。

        :param x: 横坐标
        :param y: 纵坐标
        """

        self._move_cursor(x, y)
        self._mouse_left_down()
        self._mouse_left_up()

    def _right_click_point(self, x: int, y: int) -> None:
        """
        在指定点执行右键单击。

        :param x: 横坐标
        :param y: 纵坐标
        """

        self._move_cursor(x, y)
        self._user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        self._user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    def _scroll_at_point(self, x: int, y: int, direction: str, lines: int) -> None:
        """
        在指定点执行滚轮滚动。

        :param x: 横坐标
        :param y: 纵坐标
        :param direction: 滚动方向
        :param lines: 滚动行数
        """

        delta = WHEEL_DELTA * lines
        if direction == "down":
            delta = -delta
        self._move_cursor(x, y)
        self._user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        time.sleep(DEFAULT_INPUT_INTERVAL_SECONDS)

    def _mouse_left_down(self) -> None:
        """发送左键按下事件。"""

        self._user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def _mouse_left_up(self) -> None:
        """发送左键释放事件。"""

        self._user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def _move_cursor(self, x: int, y: int) -> None:
        """
        移动鼠标光标。

        :param x: 目标横坐标
        :param y: 目标纵坐标
        :raises ExecutionError: 当光标移动失败时抛出
        """

        if not self._user32.SetCursorPos(int(x), int(y)):
            raise ExecutionError(f"鼠标移动失败: ({x}, {y})")
        time.sleep(DEFAULT_INPUT_INTERVAL_SECONDS)

    def _send_text(self, text: str) -> None:
        """
        以 Unicode 键盘输入方式发送文本。

        :param text: 待输入文本
        :raises ExecutionError: 当底层输入调用失败时抛出
        """

        for char in text:
            down = _INPUT(
                type=INPUT_KEYBOARD,
                ki=_KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE, 0, 0),
            )
            up = _INPUT(
                type=INPUT_KEYBOARD,
                ki=_KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0),
            )
            self._send_inputs([down, up])
            time.sleep(DEFAULT_INPUT_INTERVAL_SECONDS)

    def _send_hotkey(self, keys: list[str]) -> None:
        """
        发送组合快捷键。

        :param keys: 快捷键键位列表，顺序为按下顺序
        :raises ExecutionError: 当键位不支持时抛出
        """

        virtual_keys = [self._to_virtual_key(key) for key in keys]
        for virtual_key in virtual_keys:
            self._key_down(virtual_key)
            time.sleep(DEFAULT_INPUT_INTERVAL_SECONDS)
        for virtual_key in reversed(virtual_keys):
            self._key_up(virtual_key)
            time.sleep(DEFAULT_INPUT_INTERVAL_SECONDS)

    def _extract_hotkey_keys(self, action_params: dict[str, Any]) -> list[str]:
        """
        从动作参数中提取快捷键键位列表。

        :param action_params: 动作参数
        :return: 标准化键位列表
        :raises ExecutionError: 当参数非法时抛出
        """

        keys = action_params.get("keys")
        if isinstance(keys, str):
            normalized = [
                part.strip().lower() for part in keys.split("+") if part.strip()
            ]
            if normalized:
                return normalized
        if isinstance(keys, list) and all(
            isinstance(item, str) and item.strip() for item in keys
        ):
            return [item.strip().lower() for item in keys]
        raise ExecutionError("hotkey 动作必须提供 keys，格式为字符串或字符串列表")

    def _to_virtual_key(self, key: str) -> int:
        """
        将键位名称转换为 Windows 虚拟键码。

        :param key: 键位名称
        :return: 虚拟键码
        :raises ExecutionError: 当键位不支持时抛出
        """

        key_map = {
            "ctrl": 0x11,
            "control": 0x11,
            "alt": 0x12,
            "shift": 0x10,
            "enter": 0x0D,
            "esc": 0x1B,
            "escape": 0x1B,
            "tab": 0x09,
            "space": 0x20,
            "backspace": 0x08,
            "delete": 0x2E,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
            "win": 0x5B,
        }
        if key in key_map:
            return key_map[key]
        if len(key) == 1 and key.isalpha():
            return ord(key.upper())
        if len(key) == 1 and key.isdigit():
            return ord(key)
        if key.startswith("f") and key[1:].isdigit():
            number = int(key[1:])
            if 1 <= number <= 12:
                return FUNCTION_KEY_BASE + number - 1
        raise ExecutionError(f"不支持的快捷键键位: {key}")

    def _key_down(self, virtual_key: int) -> None:
        """
        发送按键按下事件。

        :param virtual_key: 虚拟键码
        """

        self._user32.keybd_event(virtual_key, 0, 0, 0)

    def _key_up(self, virtual_key: int) -> None:
        """
        发送按键释放事件。

        :param virtual_key: 虚拟键码
        """

        self._user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)

    def _send_inputs(self, inputs: list[_INPUT]) -> None:
        """
        批量发送输入事件。

        :param inputs: 输入事件列表
        :raises ExecutionError: 当底层 SendInput 调用失败时抛出
        """

        input_array = (_INPUT * len(inputs))(*inputs)
        result = self._user32.SendInput(
            len(inputs), ctypes.byref(input_array), ctypes.sizeof(_INPUT)
        )
        if result != len(inputs):
            raise ExecutionError("SendInput 调用未完整发送全部输入事件")
