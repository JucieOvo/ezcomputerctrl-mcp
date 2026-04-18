"""
模块名称：config
功能描述：
    统一管理第一阶段运行配置。
    当前模块只负责读取环境变量并完成基础合法性校验，不承担业务逻辑。

主要组件：
    - AppConfig: 应用运行配置对象。

依赖说明：
    - os: 用于读取系统环境变量。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化配置读取逻辑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final


DEFAULT_APP_NAME: Final[str] = "EZComputerCtrl"
DEFAULT_MODEL_NAME: Final[str] = "doubao-seed-2.0-lite"
DEFAULT_MODEL_BASE_URL: Final[str] = "https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_CAPTURE_SCOPE: Final[str] = "full_screen"
DEFAULT_POST_ACTION_DELAY_SECONDS: Final[float] = 0.8  # 全局默认（向后兼容）

# 差异化动作后等待时长（秒）
# NOTE: 不同动作的屏幕稳定时间差异显著，统一 0.8s 对轻量动作过于保守。
#   - 轻量动作（hotkey/type_text/scroll）：屏幕几乎即时响应，0.3s 已够用
#   - click：可能触发弹窗/菜单展开，给 0.5s 保证稳定
#   下游可通过对应环境变量覆盖，缺省值回退到上述建议值。
DEFAULT_POST_ACTION_DELAY_CLICK: Final[float] = 0.5
DEFAULT_POST_ACTION_DELAY_HOTKEY: Final[float] = 0.3
DEFAULT_POST_ACTION_DELAY_TYPE_TEXT: Final[float] = 0.3
DEFAULT_POST_ACTION_DELAY_SCROLL: Final[float] = 0.3

DEFAULT_MAX_OBJECTS: Final[int] = 25
DEFAULT_MODEL_MAX_IMAGE_SIDE: Final[int] = 1600
DEFAULT_SERVER_HOST: Final[str] = "127.0.0.1"
DEFAULT_SERVER_PORT: Final[int] = 8765
DEFAULT_TRANSPORT: Final[str] = "streamable-http"
NORMALIZED_COORDINATE_SCALE: Final[int] = 1000


@dataclass(slots=True)
class AppConfig:
    """
    应用运行配置。

    当前配置对象负责承接第一阶段实现所需的最小配置集合，重点覆盖：
    1. 屏幕采样范围。
    2. 多模态模型调用参数。
    3. MCP 服务启动参数。
    4. 动作执行后的观察等待时间。
    """

    app_name: str
    capture_scope: str
    model_name: str
    model_base_url: str
    model_api_key: str | None
    model_timeout_seconds: float | None
    # 全局兜底延迟（保留字段，用于配置中未覆盖的动作类型）
    post_action_delay_seconds: float
    # 按动作类型分组的差异化延迟（秒）
    post_action_delay_click: float
    post_action_delay_hotkey: float
    post_action_delay_type_text: float
    post_action_delay_scroll: float
    max_objects: int
    model_max_image_side: int
    server_host: str
    server_port: int
    transport: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        """
        从系统环境变量读取配置。

        :return: 完整配置对象
        :raises ValueError: 当关键配置值不合法时抛出
        """

        config = cls(
            app_name=os.getenv("EZCTRL_APP_NAME", DEFAULT_APP_NAME),
            capture_scope=os.getenv("EZCTRL_CAPTURE_SCOPE", DEFAULT_CAPTURE_SCOPE)
            .strip()
            .lower(),
            model_name=os.getenv("EZCTRL_MODEL_NAME", DEFAULT_MODEL_NAME).strip(),
            model_base_url=os.getenv(
                "EZCTRL_MODEL_BASE_URL", DEFAULT_MODEL_BASE_URL
            ).strip(),
            model_api_key=os.getenv("EZCTRL_MODEL_API_KEY") or os.getenv("ARK_API_KEY"),
            model_timeout_seconds=cls._parse_optional_float_env(
                "EZCTRL_MODEL_TIMEOUT_SECONDS"
            ),
            post_action_delay_seconds=float(
                os.getenv(
                    "EZCTRL_POST_ACTION_DELAY_SECONDS",
                    str(DEFAULT_POST_ACTION_DELAY_SECONDS),
                )
            ),
            # 差异化延迟：各动作类型优先读取自己的环境变量，
            # 缺省则直接使用内置建议值（不继承全局默认值，避免全局改小后快捷键等待过短）
            post_action_delay_click=float(
                os.getenv("EZCTRL_POST_ACTION_DELAY_CLICK", str(DEFAULT_POST_ACTION_DELAY_CLICK))
            ),
            post_action_delay_hotkey=float(
                os.getenv("EZCTRL_POST_ACTION_DELAY_HOTKEY", str(DEFAULT_POST_ACTION_DELAY_HOTKEY))
            ),
            post_action_delay_type_text=float(
                os.getenv("EZCTRL_POST_ACTION_DELAY_TYPE_TEXT", str(DEFAULT_POST_ACTION_DELAY_TYPE_TEXT))
            ),
            post_action_delay_scroll=float(
                os.getenv("EZCTRL_POST_ACTION_DELAY_SCROLL", str(DEFAULT_POST_ACTION_DELAY_SCROLL))
            ),
            max_objects=int(os.getenv("EZCTRL_MAX_OBJECTS", str(DEFAULT_MAX_OBJECTS))),
            model_max_image_side=int(
                os.getenv(
                    "EZCTRL_MODEL_MAX_IMAGE_SIDE", str(DEFAULT_MODEL_MAX_IMAGE_SIDE)
                )
            ),
            server_host=os.getenv("EZCTRL_SERVER_HOST", DEFAULT_SERVER_HOST).strip(),
            server_port=int(os.getenv("EZCTRL_SERVER_PORT", str(DEFAULT_SERVER_PORT))),
            transport=os.getenv("EZCTRL_TRANSPORT", DEFAULT_TRANSPORT).strip().lower(),
        )
        config.validate()
        return config

    @staticmethod
    def _parse_optional_float_env(env_name: str) -> float | None:
        """
        读取可选浮点环境变量。

        :param env_name: 环境变量名称
        :return: 浮点值；若未设置或为空字符串则返回 None
        :raises ValueError: 当环境变量存在但无法解析为浮点数时抛出
        """

        raw_value = os.getenv(env_name)
        if raw_value is None:
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return float(normalized)

    def validate(self) -> None:
        """
        对关键配置执行基础校验。

        :raises ValueError: 当配置值不在允许范围内时抛出
        """

        if self.capture_scope not in {"full_screen", "active_window"}:
            raise ValueError("EZCTRL_CAPTURE_SCOPE 仅支持 full_screen 或 active_window")
        if self.model_timeout_seconds is not None and self.model_timeout_seconds <= 0:
            raise ValueError("EZCTRL_MODEL_TIMEOUT_SECONDS 必须大于 0")
        if self.post_action_delay_seconds < 0:
            raise ValueError("EZCTRL_POST_ACTION_DELAY_SECONDS 不能小于 0")
        if self.max_objects <= 0:
            raise ValueError("EZCTRL_MAX_OBJECTS 必须大于 0")
        if self.model_max_image_side <= 0:
            raise ValueError("EZCTRL_MODEL_MAX_IMAGE_SIDE 必须大于 0")
        if self.server_port <= 0:
            raise ValueError("EZCTRL_SERVER_PORT 必须大于 0")
        if self.transport not in {"stdio", "streamable-http", "sse"}:
            raise ValueError("EZCTRL_TRANSPORT 仅支持 stdio、streamable-http 或 sse")
