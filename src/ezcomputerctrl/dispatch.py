"""
模块名称：dispatch
功能描述：
    MCP 层与 Worker 层之间的请求分发机制。

    核心设计：
      - MCP 工具函数将请求投入队列后立即返回 Future，不等待业务执行。
      - Worker 协程从队列串行取请求、执行业务、将结果写入 Future。
      - MCP 工具函数持续心跳，直到 Future 完成后才向客户端返回结果。

    通过这种分离，MCP 层在任何时候都不会因为业务耗时而停止心跳，
    彻底消除 MCP 客户端因长时间无回传而触发的超时断连。

主要组件：
    - DispatchRequest: 单次请求的数据容器，携带参数与结果 Future。
    - WorkDispatchQueue: 请求分发队列，提供投递与消费接口。

依赖说明：
    - asyncio: 用于 Queue 和 Future 的异步原语。

作者：JucieOvo
创建日期：2026-04-18
修改记录：
    - 2026-04-18 JucieOvo: 初始化分发队列模块。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DispatchRequest:
    """
    单次工具调用的请求容器。

    MCP 工具函数创建此对象并投入队列；
    Worker 从队列取出后执行业务，将结果写入 result_future。

    属性：
        tool_name     (str): 工具名称，仅用于日志和错误追踪。
        payload       (Any): 业务参数，由各工具函数定义其具体类型。
        result_future (asyncio.Future): Worker 执行完成后写入结果或异常的 Future。
    """

    # 工具名称（日志用，不影响业务逻辑）
    tool_name: str

    # 业务参数（各工具函数自定义字典格式）
    payload: Any

    # 结果 Future：Worker 成功时调用 set_result()，失败时调用 set_exception()
    result_future: asyncio.Future = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )


class WorkDispatchQueue:
    """
    请求分发队列。

    职责：
        1. 对 MCP 工具函数暴露 put() 接口，将请求投入内部 asyncio.Queue。
        2. 对 Worker 协程暴露 get() 接口，从队列串行取出下一个请求。

    设计约束：
        - 队列无界（maxsize=0），MCP 工具函数永远不会在投递时阻塞。
        - get() 是 await 调用，Worker 在队列为空时自然挂起，不消耗 CPU。
        - 必须在 asyncio 事件循环启动后再创建本类实例，否则 Future 工厂无法工作。
    """

    def __init__(self) -> None:
        """初始化内部请求队列。"""

        # 内部异步队列，无界设计，保证 put() 永不阻塞
        self._queue: asyncio.Queue[DispatchRequest] = asyncio.Queue()

    def put(self, tool_name: str, payload: Any) -> asyncio.Future:
        """
        将一次工具调用请求投入队列。

        此方法是同步的（非 async），MCP 工具函数只需普通调用，
        无需 await，投完立刻拿到 Future 然后去做心跳等待。

        :param tool_name: 工具名称，用于日志
        :param payload: 业务参数字典
        :return: 与本次请求绑定的 Future，Worker 完成后结果写入此 Future
        """

        # 为每次请求创建独立 Future，与请求容器绑定
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        request = DispatchRequest(
            tool_name=tool_name,
            payload=payload,
            result_future=future,
        )
        # put_nowait 利用无界队列保证不阻塞
        self._queue.put_nowait(request)
        return future

    async def get(self) -> DispatchRequest:
        """
        从队列取出下一个待执行请求（队列为空时协程挂起等待）。

        仅由 Worker 协程调用，业务串行执行的顺序由此保证。

        :return: 下一个待执行的请求容器
        """

        return await self._queue.get()

    def task_done(self) -> None:
        """
        通知队列当前任务已处理完毕。

        Worker 在每次处理完一个请求后调用，与 asyncio.Queue 语义一致。
        """

        self._queue.task_done()
