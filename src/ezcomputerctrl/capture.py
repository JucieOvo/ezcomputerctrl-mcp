"""
模块名称：capture
功能描述：
    负责从 Windows 桌面真实采集当前屏幕帧。
    当前实现支持整屏采样和活动窗口采样两种模式，并输出统一的 RawFrame 对象。

主要组件：
    - ScreenCaptureService: 屏幕采样服务。

依赖说明：
    - ctypes: 用于调用 Windows 原生窗口接口。
    - Pillow.ImageGrab: 用于执行真实屏幕截图。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化 Windows 屏幕采样实现。
"""

from __future__ import annotations

import ctypes
from contextlib import suppress
from ctypes import wintypes
from io import BytesIO

from PIL import ImageGrab

from ezcomputerctrl.config import AppConfig
from ezcomputerctrl.models import PixelBBox, RawFrame, WindowInfo


class CaptureError(RuntimeError):
    """屏幕采样失败异常。"""


class _RECT(ctypes.Structure):
    """Windows 窗口矩形结构。"""

    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(_RECT),
    wintypes.LPARAM,
)


class ScreenCaptureService:
    """
    屏幕采样服务。

    当前服务只负责真实图像采样，不负责任何视觉理解。
    """

    def __init__(self, config: AppConfig) -> None:
        """
        初始化采样服务。

        :param config: 应用配置对象
        """

        self._config = config
        self._user32 = ctypes.windll.user32
        self._enable_dpi_awareness()

    def capture(self) -> RawFrame:
        """
        执行一次真实采样。

        :return: 统一格式的原始帧对象
        :raises CaptureError: 当采样失败时抛出
        """

        frames = self.capture_frames()
        if not frames:
            raise CaptureError("屏幕采样未得到任何有效帧")
        return frames[0]

    def capture_frames(self) -> list[RawFrame]:
        """
        执行一次真实采样，返回单帧或多屏帧列表。

        在 `full_screen` 模式下，当前实现按显示器分别截图，
        避免把多个物理屏幕合并成单张大图后再交给视觉模型。

        :return: 原始帧列表
        :raises CaptureError: 当采样失败时抛出
        """

        if self._config.capture_scope == "active_window":
            image, active_window_hint, origin_x, origin_y = (
                self._capture_active_window()
            )
            return [
                self._build_raw_frame(
                    image=image,
                    source="active_window",
                    active_window_hint=active_window_hint,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    screen_id="active_window",
                    visible_windows=[],
                )
            ]

        active_window_hint = self._get_active_window_title()
        visible_windows = self._list_visible_windows()
        monitor_rects = self._list_monitor_rects()
        if not monitor_rects:
            raise CaptureError("未枚举到任何显示器")

        frames: list[RawFrame] = []
        for index, rect in enumerate(monitor_rects, start=1):
            image = ImageGrab.grab(
                bbox=(rect.left, rect.top, rect.right, rect.bottom),
                all_screens=True,
            )
            frames.append(
                self._build_raw_frame(
                    image=image,
                    source="full_screen",
                    active_window_hint=active_window_hint,
                    origin_x=rect.left,
                    origin_y=rect.top,
                    screen_id=f"screen_{index}",
                    visible_windows=visible_windows,
                )
            )
        return frames

    def _capture_active_window(self):
        """
        采集当前活动窗口区域。

        :return: 图像对象与窗口标题提示
        :raises CaptureError: 当活动窗口不可用时抛出
        """

        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            raise CaptureError("未获取到活动窗口句柄")

        rect = _RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise CaptureError("读取活动窗口矩形失败")

        if rect.right <= rect.left or rect.bottom <= rect.top:
            raise CaptureError("活动窗口矩形范围非法")

        image = ImageGrab.grab(
            bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
        )
        return image, self._get_window_title(hwnd), rect.left, rect.top

    def _build_raw_frame(
        self,
        image,
        source: str,
        active_window_hint: str | None,
        origin_x: int,
        origin_y: int,
        screen_id: str,
        visible_windows: list[WindowInfo] | None = None,
    ) -> RawFrame:
        """
        将截图图像封装为统一 RawFrame。

        :param image: 截图图像对象
        :param source: 采样来源
        :param active_window_hint: 活动窗口提示文本
        :param origin_x: 当前截图左上角在虚拟桌面中的真实横坐标
        :param origin_y: 当前截图左上角在虚拟桌面中的真实纵坐标
        :param screen_id: 当前帧所属屏幕标识
        :param visible_windows: 当前可见窗口列表
        :return: 原始帧对象
        :raises CaptureError: 当图像为空或尺寸非法时抛出
        """

        if image is None:
            raise CaptureError("屏幕采样返回空图像")

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
        width, height = image.size
        if width <= 0 or height <= 0:
            raise CaptureError("屏幕采样得到的图像尺寸非法")

        return RawFrame(
            image_bytes=image_bytes,
            width=width,
            height=height,
            origin_x=origin_x,
            origin_y=origin_y,
            screen_id=screen_id,
            source=source,
            active_window_hint=active_window_hint,
            visible_windows=visible_windows or [],
        )

    def _list_monitor_rects(self) -> list[_RECT]:
        """
        枚举当前系统中的所有显示器矩形。

        :return: 显示器矩形列表，按屏幕左上角排序
        :raises CaptureError: 当 Windows 显示器枚举失败时抛出
        """

        monitor_rects: list[_RECT] = []

        def _callback(
            _monitor: int,
            _hdc: int,
            rect_ptr: ctypes.POINTER(_RECT),
            _lparam: int,
        ) -> bool:
            rect = rect_ptr.contents
            monitor_rects.append(_RECT(rect.left, rect.top, rect.right, rect.bottom))
            return True

        callback = MONITORENUMPROC(_callback)
        if not self._user32.EnumDisplayMonitors(None, None, callback, 0):
            raise CaptureError("枚举显示器失败")

        monitor_rects.sort(
            key=lambda rect: (rect.left, rect.top, rect.right, rect.bottom)
        )
        return monitor_rects

    def _list_visible_windows(self) -> list[WindowInfo]:
        """
        枚举当前系统中的所有可见窗口（按 Z-Order 从前到后）。

        :return: 可见窗口信息列表
        """

        windows: list[WindowInfo] = []
        foreground_hwnd = self._user32.GetForegroundWindow()

        def _callback(hwnd: int, _lparam: int) -> bool:
            if self._user32.IsWindowVisible(hwnd):
                title = self._get_window_title(hwnd)
                if title:
                    rect = _RECT()
                    self._user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if rect.right > rect.left and rect.bottom > rect.top:
                        windows.append(
                            WindowInfo(
                                title=title,
                                bounds=PixelBBox(x1=rect.left, y1=rect.top, x2=rect.right, y2=rect.bottom),
                                is_foreground=(hwnd == foreground_hwnd),
                            )
                        )
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumWindows(WNDENUMPROC(_callback), 0)
        return windows

    def _enable_dpi_awareness(self) -> None:
        """
        尝试开启当前进程 DPI 感知，减少截图坐标与鼠标坐标不一致问题。

        :return: 无返回值
        """

        with suppress(Exception):
            awareness_context = ctypes.c_void_p(-4)
            if self._user32.SetProcessDpiAwarenessContext(awareness_context):
                return
        with suppress(Exception):
            self._user32.SetProcessDPIAware()

    def _get_active_window_title(self) -> str | None:
        """
        获取当前活动窗口标题。

        :return: 窗口标题，若无法获取则返回 None
        """

        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        return self._get_window_title(hwnd)

    def _get_window_title(self, hwnd: int) -> str | None:
        """
        根据窗口句柄读取标题文本。

        :param hwnd: 窗口句柄
        :return: 窗口标题，若为空则返回 None
        """

        length = self._user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        return title or None
