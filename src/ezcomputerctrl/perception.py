"""
模块名称：perception
功能描述：
    负责调用兼容 OpenAI 协议的多模态模型，对当前截图执行视觉事实提取。
    当前实现严格要求模型返回固定 JSON，并使用统一协议完成解析和校验。

主要组件：
    - VisualPerceptionService: 视觉理解服务。

依赖说明：
    - openai: 用于模型调用。
    - pydantic: 用于结果结构校验。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化多模态模型调用封装。
"""

from __future__ import annotations

import base64
from io import BytesIO
import re
from typing import Any

from openai import AsyncOpenAI
from PIL import Image

from ezcomputerctrl.config import AppConfig
from ezcomputerctrl.models import PerceptionResult, RawFrame
from ezcomputerctrl.protocol import (
    build_perception_system_prompt,
    build_perception_user_prompt,
    parse_json_object,
)


MODEL_INPUT_IMAGE_FORMAT = "JPEG"
MODEL_INPUT_JPEG_QUALITY = 85
# 图像缩放算法：GUI 截图主要由纯色块和文字组成，BILINEAR 与 LANCZOS
# 的感知差异可忽略，但编码速度快约 2-3 倍，适合时延敏感场景
MODEL_INPUT_RESAMPLE = Image.Resampling.BILINEAR
ACTION_ALIAS_MAP = {
    "edit": "input_text",
    "input": "input_text",
    "hover": "move_mouse",
    "wheel": "scroll",
    "scroll_up": "scroll",
    "scroll_down": "scroll",
}
OBJECT_TYPE_ALIAS_MAP = {
    "window": "action_area",
    "panel": "action_area",
    "dialog": "action_area",
    "button": "action_area",
    "icon_button": "action_area",
    "input": "action_area",
    "checkbox": "action_area",
    "radio": "action_area",
    "menu_item": "action_area",
    "list_item": "action_area",
    "table_cell": "action_area",
    "dropdown": "action_area",
    "link": "action_area",
    "label": "action_area",
    "address_bar": "action_area",
    "search_box": "action_area",
    "tab": "tab_header",
    "tab_title": "tab_header",
    "browser_tab": "tab_header",
}
SUPPORTED_ACTION_NAMES = {
    "click",
    "right_click",
    "scroll",
    "input_text",
    "move_mouse",
}


class PerceptionError(RuntimeError):
    """视觉理解失败异常。"""


class VisualPerceptionService:
    """
    视觉理解服务。

    当前服务专注于单次截图理解，不维护跨步骤上下文。
    """

    def __init__(self, config: AppConfig) -> None:
        """
        初始化视觉理解服务。

        :param config: 应用配置对象
        """

        self._config = config
        self._client: AsyncOpenAI | None = None

    async def understand(
        self, raw_frame: RawFrame, max_objects: int | None = None
    ) -> PerceptionResult:
        """
        对当前原始帧执行一次真实视觉理解。

        :param raw_frame: 当前采样帧
        :param max_objects: 当前帧允许返回的对象上限；若为空则使用全局配置
        :return: 经过结构校验的视觉理解结果
        :raises PerceptionError: 当模型调用失败或返回结果非法时抛出
        """

        client = self._get_client()
        effective_max_objects = max_objects or self._config.max_objects
        try:
            request_options: dict[str, Any] = {}
            if self._config.model_timeout_seconds is not None:
                request_options["timeout"] = self._config.model_timeout_seconds
            response = await client.chat.completions.create(
                model=self._config.model_name,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": build_perception_system_prompt(
                            effective_max_objects
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": build_perception_user_prompt(
                                    raw_frame.active_window_hint
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": self._build_model_image_data_url(raw_frame),
                                },
                            },
                        ],
                    },
                ],
                **request_options,
            )
        except Exception as exc:
            raise PerceptionError(
                "多模态模型调用失败。请检查当前模型是否支持图像输入、"
                "EZCTRL_MODEL_NAME 是否已切换到可用视觉模型、"
                "以及 EZCTRL_MODEL_BASE_URL 与网络连通性是否正确。"
            ) from exc

        content = self._extract_content(response)
        payload = parse_json_object(content)
        payload["frame_id"] = raw_frame.frame_id
        self._normalize_payload(payload)

        try:
            result = PerceptionResult.model_validate(payload)
        except Exception as exc:
            raise PerceptionError(f"模型输出结构校验失败: {exc}") from exc

        if len(result.candidate_objects) > effective_max_objects:
            raise PerceptionError("模型返回对象数量超过配置上限")

        return result

    def _normalize_payload(self, payload: dict[str, object]) -> None:
        """
        对模型输出做最小兼容性归一。

        当前仅处理那些不改变语义、但会影响结构校验的轻微类型偏差，
        避免因为模型把简单标识字段输出为数字而中断整个主链路。

        :param payload: 原始 JSON 负载对象
        """

        candidate_objects = payload.get("candidate_objects")
        main_regions = payload.get("main_regions")
        warnings = payload.get("warnings")

        if isinstance(main_regions, list):
            normalized_regions: list[str] = []
            for region in main_regions:
                if isinstance(region, str):
                    normalized_regions.append(region)
                    continue
                if isinstance(region, dict):
                    region_name = region.get("name")
                    if isinstance(region_name, str) and region_name.strip():
                        normalized_regions.append(region_name.strip())
                        continue
                normalized_regions.append(str(region))
            payload["main_regions"] = normalized_regions
        elif isinstance(main_regions, str):
            payload["main_regions"] = self._split_list_like_text(main_regions)

        if isinstance(warnings, str):
            payload["warnings"] = self._split_list_like_text(warnings)

        if not isinstance(candidate_objects, list):
            return
        normalized_candidates: list[dict[str, object]] = []
        for candidate in candidate_objects:
            if not isinstance(candidate, dict):
                continue
            candidate_id = candidate.get("candidate_id")
            if candidate_id is not None and not isinstance(candidate_id, str):
                candidate["candidate_id"] = str(candidate_id)

            confidence = candidate.get("confidence")
            if isinstance(confidence, int):
                candidate["confidence"] = (
                    confidence / 100 if confidence > 1 else float(confidence)
                )
            elif isinstance(confidence, float) and confidence > 1:
                candidate["confidence"] = confidence / 100

            raw_type = candidate.get("raw_type")
            if isinstance(raw_type, str):
                normalized_raw_type = raw_type.strip().lower()
                candidate["raw_type"] = OBJECT_TYPE_ALIAS_MAP.get(
                    normalized_raw_type,
                    normalized_raw_type,
                )

            bbox = candidate.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                candidate["bbox"] = {
                    "x1": bbox[0],
                    "y1": bbox[1],
                    "x2": bbox[2],
                    "y2": bbox[3],
                }

            for list_like_field in ("state", "actions", "risk"):
                field_value = candidate.get(list_like_field)
                if field_value is None:
                    candidate[list_like_field] = []
                    continue
                if list_like_field in {"state", "actions", "risk"}:
                    candidate[list_like_field] = self._normalize_enum_like_values(
                        field_value, list_like_field
                    )

            normalized_bbox = candidate.get("bbox")
            if isinstance(normalized_bbox, dict):
                required_bbox_fields = {"x1", "y1", "x2", "y2"}
                if not required_bbox_fields.issubset(normalized_bbox):
                    continue

            normalized_candidates.append(candidate)

        payload["candidate_objects"] = normalized_candidates

    def _normalize_enum_like_values(
        self, field_value: object, field_name: str
    ) -> list[object]:
        """
        归一化状态、动作、风险这三类枚举列表字段。

        :param field_value: 模型返回的原始字段值
        :param field_name: 字段名称
        :return: 归一化后的列表值
        """

        normalized_values: list[object] = []

        if isinstance(field_value, str):
            raw_items: list[object] = [field_value]
        elif isinstance(field_value, list):
            raw_items = field_value
        else:
            return normalized_values

        for item in raw_items:
            if not isinstance(item, str):
                normalized_values.append(item)
                continue
            normalized_values.extend(
                self._split_list_like_text(item, split_on_spaces=True)
            )

        if field_name == "actions":
            normalized_actions = [
                self._normalize_action_alias(value) if isinstance(value, str) else value
                for value in normalized_values
            ]
            return [
                value
                for value in normalized_actions
                if not isinstance(value, str) or value in SUPPORTED_ACTION_NAMES
            ]

        if field_name == "risk":
            return [
                value
                for value in normalized_values
                if not (
                    isinstance(value, str)
                    and value.strip().lower() in {"", "none", "null"}
                )
            ]

        if field_name == "state":
            return [
                value
                for value in normalized_values
                if not (isinstance(value, str) and value.strip() == "")
            ]

        return normalized_values

    def _normalize_action_alias(self, value: str) -> str:
        """
        将模型常见动作别名归一为项目标准动作名。

        :param value: 模型返回的单个动作字符串
        :return: 项目标准动作字符串；若无映射则返回原值
        """

        return ACTION_ALIAS_MAP.get(value, value)

    def _split_list_like_text(
        self, value: str, split_on_spaces: bool = False
    ) -> list[str]:
        """
        拆分模型返回的多值字符串字段。

        当前只处理不改变语义的轻微格式偏差，例如：
        1. editable, focused
        2. click，scroll
        3. right_click；input_text

        :param value: 原始字符串值
        :param split_on_spaces: 是否额外按空白字符拆分
        :return: 拆分并去空白后的字符串列表
        """

        split_pattern = r"[,，、;；\n]+"
        if split_on_spaces:
            split_pattern = r"[,，、;；\n\s]+"
        normalized_parts = [
            part.strip().lower()
            for part in re.split(split_pattern, value)
            if part.strip()
        ]
        return normalized_parts if normalized_parts else [value.strip().lower()]

    def _build_model_image_data_url(self, raw_frame: RawFrame) -> str:
        """
        为模型调用构建受控尺寸的图像 data URL。

        当前实现会在不改变图像内容语义的前提下，将最长边缩放到配置上限以内，
        并统一转为 JPEG 上传，以减少多模态请求体积和超时概率。

        :param raw_frame: 原始帧对象
        :return: 缩放后的图像 data URL
        """

        image = Image.open(BytesIO(raw_frame.image_bytes))
        image.load()
        max_side = max(image.size)
        resized = image
        if max_side > self._config.model_max_image_side:
            resize_ratio = self._config.model_max_image_side / max_side
            resized_size = (
                max(1, round(image.width * resize_ratio)),
                max(1, round(image.height * resize_ratio)),
            )
            # 使用 BILINEAR 重采样：对 GUI 截图（大量纯色块+文字）的感知质量
            # 与 LANCZOS 几乎无差异，但编码速度明显更快
            resized = image.resize(resized_size, MODEL_INPUT_RESAMPLE)

        if resized.mode != "RGB":
            resized = resized.convert("RGB")

        buffer = BytesIO()
        # 去掉 optimize=True：该选项会触发 JPEG 编码器多遍扫描，
        # 产生额外编码延迟，而压缩率提升在当前 quality=85 下收益极小
        resized.save(
            buffer,
            format=MODEL_INPUT_IMAGE_FORMAT,
            quality=MODEL_INPUT_JPEG_QUALITY,
        )
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _get_client(self) -> AsyncOpenAI:
        """
        获取全局复用的模型调用客户端。

        :return: AsyncOpenAI 兼容客户端
        :raises PerceptionError: 当 API Key 缺失时抛出
        """

        if self._client is not None:
            return self._client
        if not self._config.model_api_key:
            raise PerceptionError(
                "未找到 EZCTRL_MODEL_API_KEY 或 ARK_API_KEY，无法执行视觉理解"
            )
        client_options: dict[str, Any] = {
            "api_key": self._config.model_api_key,
            "base_url": self._config.model_base_url,
        }
        if self._config.model_timeout_seconds is not None:
            client_options["timeout"] = self._config.model_timeout_seconds
        self._client = AsyncOpenAI(**client_options)
        return self._client

    def _extract_content(self, response: Any) -> str:
        """
        从模型响应中提取文本内容。

        :param response: 模型响应对象
        :return: 文本内容
        :raises PerceptionError: 当响应中没有有效文本时抛出
        """

        try:
            message = response.choices[0].message
        except Exception as exc:
            raise PerceptionError(f"模型响应缺少 choices[0].message: {exc}") from exc

        content = message.content
        if isinstance(content, str) and content.strip():
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif hasattr(item, "type") and getattr(item, "type") == "text":
                    parts.append(str(getattr(item, "text", "")))
            merged = "".join(parts).strip()
            if merged:
                return merged

        raise PerceptionError("模型响应中不存在可解析的文本内容")
