"""
模块名称：ezcomputerctrl
功能描述：
    本包提供第一阶段 GUI 语义执行最小闭环实现。
    当前实现覆盖屏幕采样、视觉理解、语义归一、状态存储、动作执行、结果监看以及 MCP 对外适配。

主要组件：
    - AppConfig: 统一读取运行配置。
    - WorkflowController: 统一调度状态读取与动作闭环。
    - build_mcp_server: 构建 MCP 服务端实例。

依赖说明：
    - pydantic: 用于结构化数据定义与校验。
    - Pillow: 用于屏幕截图与图像编码。
    - openai: 用于调用兼容 OpenAI 协议的多模态模型。
    - mcp: 用于提供 MCP 工具服务端。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化第一阶段代码骨架。
"""

from ezcomputerctrl.config import AppConfig
from ezcomputerctrl.controller import WorkflowController
from ezcomputerctrl.mcp_server import build_mcp_server

__all__ = ["AppConfig", "WorkflowController", "build_mcp_server"]
