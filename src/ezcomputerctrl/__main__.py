"""
模块名称：__main__
功能描述：
    提供第一阶段 MCP 服务的命令行启动入口。
    当前入口支持 stdio、streamable-http 和 sse 三种运行方式。

    改造说明（2026-04-18）：
      - 启动流程调整为：
          1. 创建 WorkDispatchQueue（请求分发队列）
          2. 创建 WorkflowController（业务执行层）
          3. 以 asyncio.create_task 启动 Worker 无限循环
          4. 启动 MCP 服务（心跳层）
      - Worker Task 与 MCP 服务共享同一个 asyncio 事件循环。

主要组件：
    - main: 命令行启动入口。

依赖说明：
    - asyncio: 用于运行异步 MCP 服务和 Worker Task。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化 MCP 启动入口。
    - 2026-04-18 JucieOvo: 新增 Worker Task 启动逻辑，实现 MCP 层与业务层分离。
"""

from __future__ import annotations

import asyncio

from ezcomputerctrl.config import AppConfig
from ezcomputerctrl.controller import WorkflowController
from ezcomputerctrl.dispatch import WorkDispatchQueue
from ezcomputerctrl.mcp_server import build_mcp_server


async def _run_async(config: AppConfig) -> None:
    """
    异步启动入口：创建队列、启动 Worker Task、启动 MCP 服务。

    :param config: 应用配置对象
    :raises ValueError: 当 transport 配置非法时抛出
    """

    # 1. 创建请求分发队列（必须在 asyncio 事件循环内创建）
    queue = WorkDispatchQueue()

    # 2. 创建业务执行控制器
    controller = WorkflowController(config)

    # 3. 以独立 Task 方式启动 Worker 无限循环
    #    Worker 会一直运行，直到事件循环退出
    worker_task = asyncio.create_task(
        controller.run_worker_loop(queue),
        name="ezcomputerctrl-worker",
    )

    # 4. 构建 MCP 服务（传入队列实例，工具函数通过队列路由请求）
    server = build_mcp_server(config=config, queue=queue)

    try:
        # 5. 根据 transport 配置启动 MCP 服务（阻塞直到服务退出）
        if config.transport == "stdio":
            await server.run_stdio_async()
        elif config.transport == "streamable-http":
            await server.run_streamable_http_async()
        elif config.transport == "sse":
            await server.run_sse_async()
        else:
            raise ValueError(f"不支持的 transport: {config.transport}")
    finally:
        # 6. MCP 服务退出后，终止 Worker Task
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    """
    启动 MCP 服务。

    :raises ValueError: 当 transport 配置非法时抛出
    """

    config = AppConfig.from_env()
    print(
        "EZComputerCtrl MCP 启动配置："
        f" transport={config.transport};"
        f" listen={config.server_host}:{config.server_port};"
        f" model={config.model_name};"
        f" capture_scope={config.capture_scope}"
    )
    asyncio.run(_run_async(config))


if __name__ == "__main__":
    main()
