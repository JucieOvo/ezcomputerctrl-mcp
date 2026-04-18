"""
模块名称：protocol
功能描述：
    固定第一阶段多模态模型的输入协议与输出约束。
    当前模块不负责模型调用本身，只负责生成提示词和解析 JSON 文本。

主要组件：
    - build_perception_system_prompt: 生成视觉理解系统提示词。
    - build_perception_user_prompt: 生成视觉理解用户提示词。
    - parse_json_object: 将模型文本解析为 JSON 对象。

依赖说明：
    - json: 用于解析模型返回的 JSON 文本。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化固定 JSON 协议与解析逻辑。
"""

from __future__ import annotations

import json
import re


# ──────────────────────────────────────────────────────────────
# 系统提示词静态常量
# ──────────────────────────────────────────────────────────────

# NOTE: 提示词采用静态常量形式，避免每次调用时重复进行字符串构建和枚举展开。
# max_objects 通过 .format(max_objects=n) 在运行时注入，其余枚举值已写死，
# 与 models.py 中的 ActionType / GUIObjectType 保持同步。如需修改枚举，
# 同步更新此常量即可。

_PERCEPTION_SYSTEM_PROMPT_TEMPLATE = """\
你是桌面 GUI 视觉提取器。只看截图、输出结构化 JSON，不做动作规划。

规则：
1. 只描述截图中真实可见、真实可操作的 GUI 区域，不猜测、不编造。
2. 输出唯一顶层 JSON 对象，字段固定：scene_label、main_regions、candidate_objects、summary_draft、warnings。
3. candidate_objects 最多 {max_objects} 个，少而精，优先当前前景对象。
4. raw_type 只允许：action_area、tab_header。
   - action_area：可承接 click/right_click/scroll/input_text/move_mouse 的交互区域（含窗口控制按钮）。
   - tab_header：浏览器标签页抬头，用于切换识别。
5. actions 只从白名单取值：click、right_click、scroll、input_text、move_mouse。
6. 所有 bbox 用 0-1000 整数归一化坐标，字段固定：x1、y1、x2、y2。
7. 不确定的对象不输出；不输出整窗外框、大面积 panel、背景装饰。
8. candidate_objects 每项必含：candidate_id、raw_name、raw_type、raw_description、group、location_hint、actions、visible、confidence、bbox。
9. summary_draft：一句话说明当前场景、前景区域、焦点线索。
10. warnings：遮挡、错误提示、确认对话框、识别不确定点。\
"""


def build_perception_system_prompt(max_objects: int) -> str:
    """
    生成视觉理解系统提示词。

    当前实现使用静态字符串模板，通过 .format() 注入 max_objects，
    避免每次调用时重复展开枚举值和拼接字符串。

    :param max_objects: 当前帧允许输出的最多对象数量
    :return: 系统提示词文本
    """

    return _PERCEPTION_SYSTEM_PROMPT_TEMPLATE.format(max_objects=max_objects)


def build_perception_user_prompt(active_window_hint: str | None) -> str:
    """
    生成视觉理解用户提示词。

    :param active_window_hint: 当前活动窗口标题提示
    :return: 用户提示词文本
    """

    # 活动窗口提示缺失时使用占位符，避免模型在上下文字段为空时产生歧义
    window_hint = active_window_hint or "未知活动窗口"
    return (
        f"请读取截图并输出固定 JSON。\n"
        f"活动窗口：{window_hint}。\n"
        f"只保留真实可见、可支撑 GUI 操作的对象；"
        f"优先前景 action_area 和浏览器可见 tab_header；"
        f"右上角窗口控制按钮可见则输出为 action_area；"
        f"不输出 Markdown 或任何 JSON 以外的内容。"
    )


def parse_json_object(text: str) -> dict[str, object]:
    """
    将模型返回文本解析为 JSON 对象。

    当前解析只接受单个 JSON 对象文本。
    如果模型错误地使用了 Markdown 代码块，本函数会先剥离代码块包裹后再解析。

    :param text: 模型返回文本
    :return: JSON 对象
    :raises ValueError: 当文本为空或无法解析为 JSON 对象时抛出
    """

    normalized = text.strip()
    if not normalized:
        raise ValueError("模型未返回任何文本内容")

    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            normalized = "\n".join(lines[1:-1]).strip()
            if normalized.lower().startswith("json"):
                normalized = normalized[4:].strip()

    normalized = _extract_probable_json_object_text(normalized)

    normalized = _repair_json_text(normalized)
    data = json.loads(normalized)
    if not isinstance(data, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return data


def _extract_probable_json_object_text(text: str) -> str:
    """
    从混杂文本中提取最可能的顶层 JSON 对象片段。

    多模态模型在超长或复杂输出场景下，偶尔会在 JSON 前后混入解释文字。
    当前逻辑只做最小提取，不改变 JSON 主体内容。

    :param text: 原始返回文本
    :return: 估计后的 JSON 对象文本
    """

    start_index = text.find("{")
    end_index = text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index <= start_index:
        return text
    return text[start_index : end_index + 1]


def _repair_json_text(text: str) -> str:
    """
    修复模型输出中常见的轻微 JSON 非法格式。

    :param text: 原始 JSON 文本
    :return: 尽量修复后的 JSON 文本
    """

    repaired = text
    for _ in range(3):
        repaired = _escape_control_chars_in_json_strings(repaired)
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", repaired)
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        repaired = re.sub(r":(\s*)([},])", r": null\2", repaired)
        repaired = re.sub(r"\[(\s*),", r"[\1", repaired)
        try:
            json.loads(repaired)
            return repaired
        except json.JSONDecodeError:
            continue
    return repaired


def _escape_control_chars_in_json_strings(text: str) -> str:
    """
    转义 JSON 字符串中的裸控制字符。

    :param text: 原始 JSON 文本
    :return: 转义后的 JSON 文本
    """

    result: list[str] = []
    in_string = False
    escaped = False

    for char in text:
        if in_string:
            if escaped:
                result.append(char)
                escaped = False
                continue
            if char == "\\":
                result.append(char)
                escaped = True
                continue
            if char == '"':
                result.append(char)
                in_string = False
                continue
            if char == "\n":
                result.append("\\n")
                continue
            if char == "\r":
                result.append("\\r")
                continue
            if char == "\t":
                result.append("\\t")
                continue
            if ord(char) < 0x20:
                result.append(f"\\u{ord(char):04x}")
                continue
            result.append(char)
            continue

        result.append(char)
        if char == '"':
            in_string = True

    return "".join(result)
