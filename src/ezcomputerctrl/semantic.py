"""
模块名称：semantic
功能描述：
    将视觉理解结果归一化为稳定语义对象与统一状态快照。
    当前实现负责坐标转换、对象稳定 ID 生成、焦点提取以及对外 ScreenSnapshot 组装。

主要组件：
    - SemanticNormalizer: 语义归一服务。

依赖说明：
    - hashlib: 用于生成稳定对象标识。

作者：JucieOvo
创建日期：2026-04-16
修改记录：
    - 2026-04-16 JucieOvo: 初始化语义对象归一逻辑。
"""

from __future__ import annotations

import hashlib

from ezcomputerctrl.config import NORMALIZED_COORDINATE_SCALE
from ezcomputerctrl.models import (
    ActionType,
    CandidateObject,
    GUIObjectState,
    GUIObjectType,
    PerceptionResult,
    PixelBBox,
    RawFrame,
    ScreenSnapshot,
    ScreenSummary,
    SemanticObject,
)


OBJECT_ID_PREFIX = "obj"
IOU_REUSE_THRESHOLD = 0.5
POSITION_BUCKET_SIZE = 50
HIGH_PRIORITY_ACTIONS = {
    ActionType.INPUT_TEXT,
    ActionType.SCROLL,
}


class SemanticNormalizer:
    """
    语义归一服务。

    当前服务负责把模型输出变成程序维护的稳定对象，不依赖模型隐式记忆。
    """

    def build_snapshot(
        self,
        raw_frame: RawFrame,
        perception_result: PerceptionResult,
        previous_snapshot: ScreenSnapshot | None,
    ) -> ScreenSnapshot:
        """
        基于当前帧和视觉理解结果构建状态快照。

        :param raw_frame: 当前原始帧
        :param perception_result: 当前视觉理解结果
        :param previous_snapshot: 上一次状态快照，用于对象稳定化
        :return: 当前状态快照
        """

        return self.build_snapshot_from_frames(
            frame_results=[(raw_frame, perception_result)],
            previous_snapshot=previous_snapshot,
        )

    def build_snapshot_from_frames(
        self,
        frame_results: list[tuple[RawFrame, PerceptionResult]],
        previous_snapshot: ScreenSnapshot | None,
    ) -> ScreenSnapshot:
        """
        基于多帧视觉结果构建统一状态快照。

        当前实现用于多屏场景：每块显示器单独截图、单独识别，
        最终再合并成一个对外快照。

        :param frame_results: 原始帧与对应视觉结果列表
        :param previous_snapshot: 上一次状态快照，用于对象稳定化
        :return: 当前状态快照
        """

        semantic_objects: list[SemanticObject] = []
        scene_names: list[str] = []
        main_regions: list[str] = []
        warnings: list[str] = []
        summary_parts: list[str] = []

        for raw_frame, perception_result in frame_results:
            semantic_objects.extend(
                [
                    self._build_semantic_object(raw_frame, candidate, previous_snapshot)
                    for candidate in perception_result.candidate_objects
                ]
            )
            if perception_result.scene_label not in scene_names:
                scene_names.append(perception_result.scene_label)
            for region in perception_result.main_regions:
                if region not in main_regions:
                    main_regions.append(region)
            for warning in perception_result.warnings:
                if warning not in warnings:
                    warnings.append(warning)
            summary_text = perception_result.summary_draft.strip()
            if summary_text and summary_text not in summary_parts:
                summary_parts.append(summary_text)

        actionable_objects = [
            obj for obj in semantic_objects if obj.visible and len(obj.actions) > 0
        ]
        high_priority_objects = self._build_high_priority_objects(actionable_objects)
        focus_object_id = self._find_focus_object_id(actionable_objects)

        summary = ScreenSummary(
            scene_name=" | ".join(scene_names),
            main_regions=main_regions,
            focus_object_id=focus_object_id,
            overlay_present=False,
            prominent_change=" | ".join(summary_parts),
            warnings=warnings,
        )

        latest_frame = frame_results[-1][0]
        return ScreenSnapshot(
            frame_id=latest_frame.frame_id,
            captured_at=latest_frame.captured_at,
            screen_summary=summary,
            actionable_objects=actionable_objects,
            high_priority_objects=high_priority_objects,
            warnings=warnings,
        )

    def _build_semantic_object(
        self,
        raw_frame: RawFrame,
        candidate: CandidateObject,
        previous_snapshot: ScreenSnapshot | None,
    ) -> SemanticObject:
        """
        将候选对象转换为标准语义对象。

        :param raw_frame: 当前原始帧
        :param candidate: 当前候选对象
        :param previous_snapshot: 上一次快照
        :return: 标准语义对象
        """

        pixel_bbox = self._to_pixel_bbox(raw_frame, candidate)
        object_id = self._resolve_object_id(candidate, pixel_bbox, previous_snapshot)

        window_hint = None
        if raw_frame.visible_windows:
            center_x, center_y = pixel_bbox.center
            for win in raw_frame.visible_windows:
                if win.bounds.x1 <= center_x <= win.bounds.x2 and win.bounds.y1 <= center_y <= win.bounds.y2:
                    status = "前台活跃" if win.is_foreground else "后台"
                    window_hint = f"所属窗口：{win.title} [{status}]"
                    break

        return SemanticObject(
            id=object_id,
            name=candidate.raw_name,
            type=candidate.raw_type,
            description=candidate.raw_description,
            group=candidate.group,
            location_hint=candidate.location_hint,
            window_hint=window_hint,
            state=candidate.state,
            actions=candidate.actions,
            visible=candidate.visible,
            risk=candidate.risk,
            confidence=candidate.confidence,
            internal_bbox=pixel_bbox,
            source_candidate_id=candidate.candidate_id,
        )

    def _to_pixel_bbox(
        self, raw_frame: RawFrame, candidate: CandidateObject
    ) -> PixelBBox:
        """
        将归一化坐标转换为像素坐标。

        :param raw_frame: 当前原始帧
        :param candidate: 当前候选对象
        :return: 像素级边界框
        """

        scale = NORMALIZED_COORDINATE_SCALE
        local_x1 = max(0, round(candidate.bbox.x1 * raw_frame.width / scale))
        local_y1 = max(0, round(candidate.bbox.y1 * raw_frame.height / scale))
        local_x2 = min(
            raw_frame.width, round(candidate.bbox.x2 * raw_frame.width / scale)
        )
        local_y2 = min(
            raw_frame.height, round(candidate.bbox.y2 * raw_frame.height / scale)
        )
        x1 = raw_frame.origin_x + local_x1
        y1 = raw_frame.origin_y + local_y1
        x2 = raw_frame.origin_x + local_x2
        y2 = raw_frame.origin_y + local_y2
        return PixelBBox(x1=x1, y1=y1, x2=x2, y2=y2)

    def _resolve_object_id(
        self,
        candidate: CandidateObject,
        pixel_bbox: PixelBBox,
        previous_snapshot: ScreenSnapshot | None,
    ) -> str:
        """
        为当前对象生成稳定 ID。

        当前实现优先复用上一次快照中的高相似对象；若无法复用，则根据类型、语义文本和位置桶生成稳定哈希。

        :param candidate: 当前候选对象
        :param pixel_bbox: 当前像素边界框
        :param previous_snapshot: 上一次状态快照
        :return: 对象稳定 ID
        """

        if previous_snapshot is not None:
            reusable_id = self._find_reusable_object_id(
                candidate, pixel_bbox, previous_snapshot
            )
            if reusable_id:
                return reusable_id

        center_x, center_y = pixel_bbox.center
        signature = "|".join(
            [
                candidate.raw_type.value,
                self._normalize_text(candidate.raw_name),
                self._normalize_text(candidate.group),
                self._normalize_text(candidate.location_hint),
                str(self._bucketize(center_x)),
                str(self._bucketize(center_y)),
            ]
        )
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
        return f"{OBJECT_ID_PREFIX}_{digest}"

    def _find_reusable_object_id(
        self,
        candidate: CandidateObject,
        pixel_bbox: PixelBBox,
        previous_snapshot: ScreenSnapshot,
    ) -> str | None:
        """
        在上一轮快照中查找可复用对象 ID。

        :param candidate: 当前候选对象
        :param pixel_bbox: 当前对象像素边界框
        :param previous_snapshot: 上一次状态快照
        :return: 可复用对象 ID；若未命中则返回 None
        """

        current_name = self._normalize_text(candidate.raw_name)
        current_group = self._normalize_text(candidate.group)
        for previous_object in previous_snapshot.actionable_objects:
            if previous_object.type != candidate.raw_type:
                continue
            if self._normalize_text(previous_object.name) != current_name:
                continue
            if self._normalize_text(previous_object.group) != current_group:
                continue
            if (
                self._calculate_iou(previous_object.internal_bbox, pixel_bbox)
                >= IOU_REUSE_THRESHOLD
            ):
                return previous_object.id
        return None

    def _find_focus_object_id(
        self, semantic_objects: list[SemanticObject]
    ) -> str | None:
        """
        提取当前焦点对象。

        :param semantic_objects: 当前语义对象列表
        :return: 焦点对象 ID；若不存在则返回 None
        """

        for obj in semantic_objects:
            if GUIObjectState.FOCUSED in obj.state:
                return obj.id
        return None

    def _build_high_priority_objects(
        self, actionable_objects: list[SemanticObject]
    ) -> list[SemanticObject]:
        """
        从当前可操作对象中筛选高优先级对象。

        :param actionable_objects: 当前可操作对象列表
        :return: 高优先级对象列表
        """

        prioritized: list[tuple[int, SemanticObject]] = []
        for obj in actionable_objects:
            score = 0

            # 第一版本只保留极少类型，因此高优对象也用硬规则直接排序，避免旧语义推断残留。
            if GUIObjectState.FOCUSED in obj.state:
                score += 100
            if obj.type == GUIObjectType.TAB_HEADER:
                score += 60
            if any(action in HIGH_PRIORITY_ACTIONS for action in obj.actions):
                score += 10
            if obj.type == GUIObjectType.ACTION_AREA:
                score += 5
            prioritized.append((score, obj))

        prioritized.sort(key=lambda item: (-item[0], -item[1].confidence, item[1].name))
        return [obj for _, obj in prioritized[:8]]

    def _calculate_iou(self, left: PixelBBox, right: PixelBBox) -> float:
        """
        计算两个像素边界框的交并比。

        :param left: 左侧边界框
        :param right: 右侧边界框
        :return: 交并比结果
        """

        inter_x1 = max(left.x1, right.x1)
        inter_y1 = max(left.y1, right.y1)
        inter_x2 = min(left.x2, right.x2)
        inter_y2 = min(left.y2, right.y2)
        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0

        intersection = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        left_area = (left.x2 - left.x1) * (left.y2 - left.y1)
        right_area = (right.x2 - right.x1) * (right.y2 - right.y1)
        union = left_area + right_area - intersection
        if union <= 0:
            return 0.0
        return intersection / union

    def _bucketize(self, value: int) -> int:
        """
        将位置值离散到固定桶中，减小微小像素抖动带来的对象 ID 波动。

        :param value: 原始像素值
        :return: 桶化后的像素值
        """

        return round(value / POSITION_BUCKET_SIZE) * POSITION_BUCKET_SIZE

    def _normalize_text(self, value: str) -> str:
        """
        对文本做最小归一化处理。

        :param value: 原始文本
        :return: 归一化文本
        """

        return " ".join(value.strip().lower().split())
