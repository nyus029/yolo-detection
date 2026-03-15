from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter

UTC = timezone.utc


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def blend_color(start: tuple[int, int, int], end: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    alpha = clamp(amount, 0.0, 1.0)
    return tuple(int(round(start[i] * (1.0 - alpha) + end[i] * alpha)) for i in range(3))


def heat_color(value: float) -> tuple[int, int, int]:
    stops = [
        (0.0, (255, 255, 255)),
        (0.12, (219, 234, 254)),
        (0.32, (125, 211, 252)),
        (0.55, (74, 222, 128)),
        (0.78, (250, 204, 21)),
        (1.0, (249, 115, 22)),
    ]
    clamped = clamp(value, 0.0, 1.0)
    for index in range(1, len(stops)):
        prev_at, prev_color = stops[index - 1]
        next_at, next_color = stops[index]
        if clamped <= next_at:
            amount = (clamped - prev_at) / max(1e-6, next_at - prev_at)
            return blend_color(prev_color, next_color, amount)
    return stops[-1][1]


@dataclass
class ProjectionConfig:
    room_width_units: float = 10.0
    room_height_units: float = 10.0
    floor_top_y_ratio: float = 0.35
    floor_top_width_ratio: float = 0.38
    floor_bottom_width_ratio: float = 1.0

    def normalized(self) -> ProjectionConfig:
        return ProjectionConfig(
            room_width_units=max(1.0, float(self.room_width_units)),
            room_height_units=max(1.0, float(self.room_height_units)),
            floor_top_y_ratio=clamp(float(self.floor_top_y_ratio), 0.05, 0.95),
            floor_top_width_ratio=clamp(float(self.floor_top_width_ratio), 0.05, 1.0),
            floor_bottom_width_ratio=clamp(float(self.floor_bottom_width_ratio), 0.05, 1.0),
        )


@dataclass
class FurnitureItem:
    kind: str
    x: float
    y: float
    width: float
    height: float
    confidence: float
    support: int = 1

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "confidence": round(self.confidence, 4),
            "support": self.support,
        }


def finalize_furniture_items(items: list[dict[str, Any]], min_support: int = 2) -> list[FurnitureItem]:
    merged_tables: list[dict[str, Any]] = []
    finalized: list[FurnitureItem] = []

    for item in items:
        support = int(item["support"])
        if support < min_support:
            continue

        if str(item["kind"]) != "table":
            finalized.append(
                FurnitureItem(
                    kind=str(item["kind"]),
                    x=float(item["x"]),
                    y=float(item["y"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                    confidence=float(item["confidence"]),
                    support=support,
                )
            )
            continue

        merged = False
        current_x = float(item["x"])
        current_y = float(item["y"])
        current_width = float(item["width"])
        current_height = float(item["height"])
        current_confidence = float(item["confidence"])

        for cluster in merged_tables:
            x_gap = abs(float(cluster["x"]) - current_x)
            y_gap = abs(float(cluster["y"]) - current_y)
            avg_width = (float(cluster["width"]) + current_width) * 0.5
            vertical_span = (float(cluster["height"]) + current_height) * 0.5
            if x_gap > max(0.08, avg_width * 0.75):
                continue
            if y_gap > max(0.22, vertical_span * 1.9):
                continue

            top = min(float(cluster["y"]) - float(cluster["height"]) * 0.5, current_y - current_height * 0.5)
            bottom = max(float(cluster["y"]) + float(cluster["height"]) * 0.5, current_y + current_height * 0.5)
            cluster_support = int(cluster["support"]) + support
            alpha = support / max(1, cluster_support)
            cluster["x"] = float(float(cluster["x"]) * (1.0 - alpha) + current_x * alpha)
            cluster["y"] = float((top + bottom) * 0.5)
            cluster["width"] = float(clamp(max(float(cluster["width"]), current_width, avg_width * 0.95), 0.1, 0.34))
            cluster["height"] = float(clamp(bottom - top, 0.1, 0.55))
            cluster["confidence"] = max(float(cluster["confidence"]), current_confidence)
            cluster["support"] = cluster_support
            merged = True
            break

        if not merged:
            merged_tables.append(
                {
                    "kind": "table",
                    "x": current_x,
                    "y": current_y,
                    "width": current_width,
                    "height": current_height,
                    "confidence": current_confidence,
                    "support": support,
                }
            )

    finalized.extend(
        FurnitureItem(
            kind="table",
            x=float(item["x"]),
            y=float(item["y"]),
            width=float(item["width"]),
            height=float(item["height"]),
            confidence=float(item["confidence"]),
            support=int(item["support"]),
        )
        for item in merged_tables
    )
    return finalized


def room_layout_metrics(
    width: int,
    height: int,
    projection: ProjectionConfig,
) -> dict[str, Any]:
    outer_padding = max(14, int(min(width, height) * 0.04))
    available_width = max(120, width - outer_padding * 2)
    available_height = max(120, height - outer_padding * 2)
    room_ratio = projection.room_width_units / max(1.0, projection.room_height_units)
    if available_width / max(1.0, available_height) > room_ratio:
        room_height = available_height
        room_width = max(120, int(round(room_height * room_ratio)))
    else:
        room_width = available_width
        room_height = max(120, int(round(room_width / max(1e-6, room_ratio))))
    room_x = outer_padding + max(0, (available_width - room_width) // 2)
    room_y = outer_padding + max(0, (available_height - room_height) // 2)
    wall_thickness = int(clamp(min(room_width, room_height) * 0.035, 8, 18))

    return {
        "room_x": room_x,
        "room_y": room_y,
        "room_width": room_width,
        "room_height": room_height,
        "wall_thickness": wall_thickness,
    }


def draw_room_plan(
    canvas: np.ndarray,
    projection: ProjectionConfig,
    heatmap: np.ndarray | None = None,
    furniture_items: list[FurnitureItem] | None = None,
) -> None:
    layout = room_layout_metrics(canvas.shape[1], canvas.shape[0], projection)
    room_x = layout["room_x"]
    room_y = layout["room_y"]
    room_width = layout["room_width"]
    room_height = layout["room_height"]
    wall_thickness = layout["wall_thickness"]
    room_right = room_x + room_width
    room_bottom = room_y + room_height

    cv2.rectangle(
        canvas,
        (room_x - wall_thickness, room_y - wall_thickness),
        (room_right + wall_thickness, room_bottom + wall_thickness),
        (226, 221, 210),
        -1,
    )

    floor_top = np.array([255, 253, 248], dtype=np.float32)
    floor_bottom = np.array([243, 239, 230], dtype=np.float32)
    gradient = np.linspace(0.0, 1.0, room_height, dtype=np.float32)[:, None, None]
    floor = np.repeat((floor_top * (1.0 - gradient) + floor_bottom * gradient).astype(np.uint8), room_width, axis=1)
    canvas[room_y:room_bottom, room_x:room_right] = floor

    if heatmap is not None and float(heatmap.max()) > 0:
        normalized = heatmap / float(heatmap.max())
        smoothed = gaussian_filter(normalized, sigma=1.2)
        resized = cv2.resize(smoothed, (room_width, room_height), interpolation=cv2.INTER_CUBIC)
        blurred = cv2.GaussianBlur(resized, (0, 0), sigmaX=9, sigmaY=9)
        colored = np.zeros((room_height, room_width, 3), dtype=np.uint8)
        for row in range(room_height):
            for col in range(room_width):
                bgr = heat_color(float(blurred[row, col]))
                colored[row, col] = (bgr[2], bgr[1], bgr[0])
        overlay = canvas[room_y:room_bottom, room_x:room_right].copy()
        canvas[room_y:room_bottom, room_x:room_right] = cv2.addWeighted(overlay, 0.5, colored, 0.5, 0.0)

    wall_color = (63, 63, 70)
    cv2.line(canvas, (room_x, room_y), (room_right, room_y), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (room_x, room_y), (room_x, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (room_right, room_y), (room_right, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (room_x, room_bottom), (room_right, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)

    if furniture_items:
        draw_furniture_plan(canvas, projection, furniture_items)


def draw_furniture_plan(
    canvas: np.ndarray,
    projection: ProjectionConfig,
    furniture_items: list[FurnitureItem],
) -> None:
    layout = room_layout_metrics(canvas.shape[1], canvas.shape[0], projection)
    room_x = layout["room_x"]
    room_y = layout["room_y"]
    room_width = layout["room_width"]
    room_height = layout["room_height"]
    wall_thickness = layout["wall_thickness"]

    for item in furniture_items:
        center_x = int(round(room_x + item.x * room_width))
        center_y = int(round(room_y + item.y * room_height))
        draw_width = max(12, int(round(item.width * room_width)))
        draw_height = max(12, int(round(item.height * room_height)))

        if item.kind == "table":
            top_left = (center_x - draw_width // 2, center_y - draw_height // 2)
            bottom_right = (center_x + draw_width // 2, center_y + draw_height // 2)
            cv2.rectangle(canvas, top_left, bottom_right, (173, 127, 81), -1, cv2.LINE_AA)
            cv2.rectangle(canvas, top_left, bottom_right, (111, 78, 55), 2, cv2.LINE_AA)
        elif item.kind == "chair":
            radius = max(8, min(draw_width, draw_height) // 2)
            cv2.circle(canvas, (center_x, center_y), radius, (94, 129, 172), -1, cv2.LINE_AA)
            cv2.circle(canvas, (center_x, center_y), radius, (52, 83, 122), 2, cv2.LINE_AA)
        elif item.kind == "sofa":
            top_left = (center_x - draw_width // 2, center_y - draw_height // 2)
            bottom_right = (center_x + draw_width // 2, center_y + draw_height // 2)
            cv2.rectangle(canvas, top_left, bottom_right, (130, 155, 126), -1, cv2.LINE_AA)
            cv2.rectangle(canvas, top_left, bottom_right, (86, 108, 82), 2, cv2.LINE_AA)
            inset = max(4, min(draw_width, draw_height) // 5)
            cv2.rectangle(
                canvas,
                (top_left[0] + inset, top_left[1] + inset),
                (bottom_right[0] - inset, bottom_right[1] - inset),
                (178, 198, 171),
                2,
                cv2.LINE_AA,
            )
        elif item.kind == "tv":
            top_left = (center_x - draw_width // 2, center_y - draw_height // 2)
            bottom_right = (center_x + draw_width // 2, center_y + draw_height // 2)
            cv2.rectangle(canvas, top_left, bottom_right, (58, 69, 84), -1, cv2.LINE_AA)
            cv2.rectangle(canvas, top_left, bottom_right, (26, 32, 44), 2, cv2.LINE_AA)
        elif item.kind == "plant":
            pot_w = max(10, draw_width // 2)
            pot_h = max(8, draw_height // 3)
            cv2.ellipse(canvas, (center_x, center_y - pot_h // 2), (draw_width // 3, draw_height // 2), 0, 0, 360, (76, 145, 94), -1, cv2.LINE_AA)
            cv2.rectangle(
                canvas,
                (center_x - pot_w // 2, center_y + pot_h // 4),
                (center_x + pot_w // 2, center_y + pot_h),
                (162, 104, 66),
                -1,
                cv2.LINE_AA,
            )
        elif item.kind == "bed":
            top_left = (center_x - draw_width // 2, center_y - draw_height // 2)
            bottom_right = (center_x + draw_width // 2, center_y + draw_height // 2)
            cv2.rectangle(canvas, top_left, bottom_right, (223, 227, 235), -1, cv2.LINE_AA)
            cv2.rectangle(canvas, top_left, bottom_right, (148, 163, 184), 2, cv2.LINE_AA)
            pillow_h = max(8, draw_height // 4)
            cv2.rectangle(
                canvas,
                (top_left[0] + wall_thickness, top_left[1] + wall_thickness),
                (bottom_right[0] - wall_thickness, top_left[1] + wall_thickness + pillow_h),
                (248, 250, 252),
                -1,
                cv2.LINE_AA,
            )


def clamp_bbox(value: float, maximum: int) -> float:
    return clamp(value, 0.0, float(maximum - 1))


def project_point_to_plane(
    projection: ProjectionConfig,
    x_ratio: float,
    y_ratio: float,
) -> tuple[float, float] | None:
    clamped_x = clamp(x_ratio, 0.0, 1.0)
    clamped_y = clamp(y_ratio, 0.0, 1.0)
    top_y = projection.floor_top_y_ratio
    if clamped_y < top_y:
        return None

    depth_ratio = (clamped_y - top_y) / max(1e-6, 1.0 - top_y)
    visible_width = projection.floor_top_width_ratio + (
        projection.floor_bottom_width_ratio - projection.floor_top_width_ratio
    ) * depth_ratio
    if visible_width <= 0:
        return None

    plane_x = ((clamped_x - 0.5) / visible_width) + 0.5
    if plane_x < -0.2 or plane_x > 1.2:
        return None

    return clamp(plane_x, 0.0, 1.0), clamp(depth_ratio, 0.0, 1.0)


def snap_furniture_to_room(kind: str, plane_x: float, plane_y: float) -> tuple[float, float]:
    if kind == "tv":
        return plane_x, 0.08
    if kind == "bed":
        return plane_x, clamp(plane_y, 0.18, 0.42)
    if kind == "plant":
        return clamp(plane_x, 0.1, 0.9), clamp(plane_y, 0.12, 0.88)
    return plane_x, plane_y


def estimate_furniture_footprint(
    projection: ProjectionConfig,
    kind: str,
    bbox: list[float] | tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    projected_width: float,
    bbox_width_ratio: float,
    bbox_height_ratio: float,
) -> tuple[float, float]:
    width_ratio = clamp(projected_width * 1.05, 0.05, 0.35)
    height_ratio = clamp(bbox_height_ratio * 0.85, 0.05, 0.3)

    if kind in {"tv", "plant"}:
        return width_ratio, height_ratio * 0.8

    if kind == "chair":
        return (
            clamp(width_ratio * 0.72, 0.04, 0.16),
            clamp(height_ratio * 0.72, 0.04, 0.16),
        )

    if kind == "table":
        x1, y1, x2, y2 = bbox
        plane_bottom_left = project_point_to_plane(projection, x1 / max(1.0, frame_width), y2 / max(1.0, frame_height))
        plane_bottom_right = project_point_to_plane(projection, x2 / max(1.0, frame_width), y2 / max(1.0, frame_height))
        sampled_top_y = max(float(y1), projection.floor_top_y_ratio * frame_height)
        plane_top_center = project_point_to_plane(
            projection,
            ((x1 + x2) * 0.5) / max(1.0, frame_width),
            sampled_top_y / max(1.0, frame_height),
        )
        plane_bottom_center = project_point_to_plane(
            projection,
            ((x1 + x2) * 0.5) / max(1.0, frame_width),
            y2 / max(1.0, frame_height),
        )

        plane_span_x = width_ratio
        plane_span_y = height_ratio
        if plane_bottom_left and plane_bottom_right:
            plane_span_x = clamp(abs(plane_bottom_right[0] - plane_bottom_left[0]), 0.05, 0.35)
        if plane_top_center and plane_bottom_center:
            plane_span_y = clamp(abs(plane_bottom_center[1] - plane_top_center[1]), 0.05, 0.35)

        base_width = clamp(max(width_ratio * 1.05, plane_span_x * 1.15), 0.09, 0.3)
        base_height = clamp(max(height_ratio * 0.8, plane_span_y * 1.1), 0.07, 0.3)
        plane_aspect_ratio = plane_span_x / max(1e-6, plane_span_y)

        if plane_aspect_ratio >= 1.18:
            long_side = clamp(max(base_width, base_height * 1.35), 0.11, 0.32)
            short_side = clamp(min(base_height, long_side * 0.74), 0.07, 0.18)
            return long_side, short_side

        if plane_aspect_ratio <= 0.85:
            long_side = clamp(max(base_height, base_width * 1.35), 0.11, 0.32)
            short_side = clamp(min(base_width, long_side * 0.74), 0.07, 0.18)
            return short_side, long_side

        square_side = clamp((base_width + base_height) * 0.5, 0.08, 0.22)
        return square_side, square_side

    return width_ratio, height_ratio


def project_furniture_detections(
    projection: ProjectionConfig,
    furniture_detections: list[dict[str, Any]],
    frame_width: int,
    frame_height: int,
) -> list[FurnitureItem]:
    temp_session = HeatmapSession(
        duration_minutes=1,
        grid_width=4,
        grid_height=4,
        projection=projection,
    )
    for detection in furniture_detections:
        x1, y1, x2, y2 = detection["bbox"]
        projected = project_detection_to_plane(projection, detection["bbox"], frame_width, frame_height)
        if projected is None:
            continue

        plane_x, plane_y = snap_furniture_to_room(
            str(detection.get("furniture_type") or detection.get("class_name") or "object"),
            projected["x"],
            projected["y"],
        )
        kind = str(detection.get("furniture_type") or detection.get("class_name") or "object")
        bbox_width_ratio = (x2 - x1) / max(1.0, frame_width)
        bbox_height_ratio = (y2 - y1) / max(1.0, frame_height)
        width_ratio, height_ratio = estimate_furniture_footprint(
            projection,
            kind,
            detection["bbox"],
            frame_width,
            frame_height,
            projected["width"],
            bbox_width_ratio,
            bbox_height_ratio,
        )

        temp_session.merge_furniture_detection(kind, plane_x, plane_y, width_ratio, height_ratio, float(detection.get("score", 0.0)))

    return [
        item
        for item in finalize_furniture_items(temp_session.furniture_observations, min_support=1)
    ]


def project_detection_to_plane(
    projection: ProjectionConfig,
    bbox: list[float] | tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
) -> dict[str, float] | None:
    x1, y1, x2, y2 = bbox
    plane_center = project_point_to_plane(projection, ((x1 + x2) * 0.5) / max(1.0, frame_width), y2 / max(1.0, frame_height))
    plane_left = project_point_to_plane(projection, x1 / max(1.0, frame_width), y2 / max(1.0, frame_height))
    plane_right = project_point_to_plane(projection, x2 / max(1.0, frame_width), y2 / max(1.0, frame_height))

    if plane_center is None or plane_left is None or plane_right is None:
        return None

    return {
        "x": plane_center[0],
        "y": plane_center[1],
        "width": clamp(abs(plane_right[0] - plane_left[0]), 0.02, 0.9),
    }


@dataclass
class HeatmapSession:
    duration_minutes: int
    grid_width: int
    grid_height: int
    projection: ProjectionConfig
    id: str = field(default_factory=lambda: uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    processed_frames: int = 0
    person_detections: int = 0
    last_person_count: int = 0
    projected_points: int = 0
    ignored_points: int = 0
    saved_heatmap_path: str | None = None
    saved_metadata_path: str | None = None
    heatmap: np.ndarray = field(init=False)
    furniture_items: list[FurnitureItem] = field(default_factory=list)
    furniture_observations: list[dict[str, Any]] = field(default_factory=list, repr=False)
    lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        self.projection = self.projection.normalized()
        self.heatmap = np.zeros((self.grid_height, self.grid_width), dtype=np.float32)

    @property
    def expires_at(self) -> datetime:
        return self.started_at + timedelta(minutes=self.duration_minutes)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None and datetime.now(UTC) < self.expires_at

    def stop(self) -> None:
        if self.ended_at is None:
            self.ended_at = datetime.now(UTC)

    def project_to_plane(
        self,
        foot_x: float,
        foot_y: float,
        frame_width: int,
        frame_height: int,
    ) -> tuple[float, float] | None:
        return project_point_to_plane(
            self.projection,
            foot_x / max(1.0, frame_width),
            foot_y / max(1.0, frame_height),
        )

    def merge_furniture_detection(
        self,
        kind: str,
        plane_x: float,
        plane_y: float,
        width_ratio: float,
        height_ratio: float,
        score: float,
    ) -> None:
        match_index: int | None = None
        best_distance = 1e9

        for index, existing in enumerate(self.furniture_observations):
            if existing["kind"] != kind:
                continue
            distance = abs(existing["x"] - plane_x) + abs(existing["y"] - plane_y)
            if distance < 0.18 and distance < best_distance:
                best_distance = distance
                match_index = index

        if match_index is None:
            self.furniture_observations.append(
                {
                    "kind": kind,
                    "x": plane_x,
                    "y": plane_y,
                    "width": width_ratio,
                    "height": height_ratio,
                    "confidence": score,
                    "support": 1,
                }
            )
        else:
            existing = self.furniture_observations[match_index]
            support = int(existing["support"]) + 1
            alpha = 1.0 / support
            existing["x"] = float(existing["x"] * (1.0 - alpha) + plane_x * alpha)
            existing["y"] = float(existing["y"] * (1.0 - alpha) + plane_y * alpha)
            existing["width"] = float(existing["width"] * (1.0 - alpha) + width_ratio * alpha)
            existing["height"] = float(existing["height"] * (1.0 - alpha) + height_ratio * alpha)
            existing["confidence"] = max(float(existing["confidence"]), score)
            existing["support"] = support

        self.furniture_items = finalize_furniture_items(self.furniture_observations, min_support=2)

    def add_frame(
        self,
        frame: np.ndarray,
        detections: list[dict[str, Any]],
        furniture_detections: list[dict[str, Any]] | None = None,
    ) -> None:
        frame_height, frame_width = frame.shape[:2]
        with self.lock:
            self.frame_width = frame_width
            self.frame_height = frame_height
            self.processed_frames += 1
            self.last_person_count = len(detections)
            self.person_detections += len(detections)

            for detection in detections:
                projected = project_detection_to_plane(self.projection, detection["bbox"], frame_width, frame_height)
                if projected is None:
                    self.ignored_points += 1
                    continue

                plane_x = projected["x"]
                plane_y = projected["y"]
                grid_x = min(self.grid_width - 1, int(plane_x * self.grid_width))
                grid_y = min(self.grid_height - 1, int(plane_y * self.grid_height))
                self.heatmap[grid_y, grid_x] += 1.0
                self.projected_points += 1

            for detection in furniture_detections or []:
                x1, y1, x2, y2 = detection["bbox"]
                projected = project_detection_to_plane(self.projection, detection["bbox"], frame_width, frame_height)
                if projected is None:
                    continue

                kind = str(detection.get("furniture_type") or detection.get("class_name") or "object")
                plane_x, plane_y = snap_furniture_to_room(kind, projected["x"], projected["y"])
                bbox_width_ratio = (x2 - x1) / max(1.0, frame_width)
                bbox_height_ratio = (y2 - y1) / max(1.0, frame_height)
                width_ratio, height_ratio = estimate_furniture_footprint(
                    self.projection,
                    kind,
                    detection["bbox"],
                    frame_width,
                    frame_height,
                    projected["width"],
                    bbox_width_ratio,
                    bbox_height_ratio,
                )

                self.merge_furniture_detection(kind, plane_x, plane_y, width_ratio, height_ratio, float(detection.get("score", 0.0)))

    def to_status(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        remaining_seconds = max(0, int((self.expires_at - now).total_seconds()))
        ended_at = self.ended_at.isoformat() if self.ended_at else None
        with self.lock:
            furniture_items = [item.to_payload() for item in self.furniture_items]
        return {
            "session_id": self.id,
            "started_at": self.started_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "ended_at": ended_at,
            "is_active": self.is_active,
            "duration_minutes": self.duration_minutes,
            "processed_frames": self.processed_frames,
            "person_detections": self.person_detections,
            "last_person_count": self.last_person_count,
            "projected_points": self.projected_points,
            "ignored_points": self.ignored_points,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "remaining_seconds": remaining_seconds,
            "saved_heatmap_path": self.saved_heatmap_path,
            "saved_metadata_path": self.saved_metadata_path,
            "projection": asdict(self.projection),
            "furniture_items": furniture_items,
        }

    def to_heatmap_data(self) -> dict[str, Any]:
        with self.lock:
            heatmap = self.heatmap.copy()
            current_count = self.last_person_count
            furniture_items = [item.to_payload() for item in self.furniture_items]

        elapsed_seconds = max(0, int((datetime.now(UTC) - self.started_at).total_seconds()))
        return {
            "grid": heatmap.tolist(),
            "max_value": float(heatmap.max()) if heatmap.size else 0.0,
            "grid_width": self.grid_width,
            "grid_height": self.grid_height,
            "current_count": current_count,
            "elapsed_seconds": elapsed_seconds,
            "room_width_units": self.projection.room_width_units,
            "room_height_units": self.projection.room_height_units,
            "is_active": self.is_active,
            "projection": asdict(self.projection),
            "furniture_items": furniture_items,
        }

    def render_heatmap_png(self) -> bytes | None:
        with self.lock:
            heatmap = self.heatmap.copy()
            furniture_items = list(self.furniture_items)

        canvas_width = 960
        canvas_height = 720
        margin_left = 100
        margin_right = 80
        margin_top = 80
        margin_bottom = 100
        plane_width = canvas_width - margin_left - margin_right
        plane_height = canvas_height - margin_top - margin_bottom
        canvas = np.full((canvas_height, canvas_width, 3), 250, dtype=np.uint8)
        plane = np.full((plane_height, plane_width, 3), 248, dtype=np.uint8)
        draw_room_plan(plane, self.projection, heatmap, furniture_items)
        canvas[margin_top : margin_top + plane_height, margin_left : margin_left + plane_width] = plane

        cv2.putText(
            canvas,
            "Room Layout Heatmap",
            (margin_left, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )
        subtitle = (
            f"Simple floor plan from structure estimate  |  room={self.projection.room_width_units:.1f} x "
            f"{self.projection.room_height_units:.1f} units  |  projected={self.projected_points}"
        )
        cv2.putText(
            canvas,
            subtitle,
            (margin_left, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (80, 80, 80),
            1,
            cv2.LINE_AA,
        )

        cv2.putText(
            canvas,
            f"Width ({self.projection.room_width_units:.1f})",
            (margin_left + plane_width // 2 - 90, canvas_height - 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (40, 40, 40),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            f"Depth ({self.projection.room_height_units:.1f})",
            (16, margin_top + plane_height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (40, 40, 40),
            2,
            cv2.LINE_AA,
        )
        legend_x = canvas_width - 48
        legend_top = margin_top
        legend_bottom = margin_top + plane_height
        for i in range(legend_bottom - legend_top):
            ratio = 1.0 - (i / max(1, legend_bottom - legend_top - 1))
            color = cv2.applyColorMap(np.uint8([[ratio * 255]]), cv2.COLORMAP_INFERNO)[0, 0]
            cv2.line(canvas, (legend_x, legend_top + i), (legend_x + 18, legend_top + i), color.tolist(), 1)
        cv2.rectangle(canvas, (legend_x, legend_top), (legend_x + 18, legend_bottom), (70, 70, 70), 1)
        cv2.putText(canvas, "High", (legend_x - 6, legend_top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 50, 50), 1)
        cv2.putText(canvas, "Low", (legend_x - 2, legend_bottom + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 50, 50), 1)

        ok, encoded = cv2.imencode(".png", canvas)
        if not ok:
            return None
        return encoded.tobytes()

    def persist_artifacts(self, output_dir: Path) -> dict[str, str] | None:
        image_bytes = self.render_heatmap_png()
        if image_bytes is None:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self.started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        base_name = f"heatmap_{timestamp}_{self.id}"
        image_path = output_dir / f"{base_name}.png"
        metadata_path = output_dir / f"{base_name}.json"

        image_path.write_bytes(image_bytes)
        self.saved_heatmap_path = str(image_path)
        self.saved_metadata_path = str(metadata_path)

        metadata = self.to_status() | {
            "grid_width": self.grid_width,
            "grid_height": self.grid_height,
            "saved_at": datetime.now(UTC).isoformat(),
            "heatmap_values": self.heatmap.tolist(),
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "saved_heatmap_path": self.saved_heatmap_path,
            "saved_metadata_path": self.saved_metadata_path,
        }


class SessionStore:
    def __init__(
        self,
        grid_width: int = 48,
        grid_height: int = 32,
        output_dir: str = "artifacts/heatmaps",
    ) -> None:
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.output_dir = Path(output_dir)
        self.sessions: dict[str, HeatmapSession] = {}
        self.lock = Lock()

    def create(
        self,
        duration_minutes: int,
        projection: ProjectionConfig | None = None,
    ) -> HeatmapSession:
        session = HeatmapSession(
            duration_minutes=duration_minutes,
            grid_width=self.grid_width,
            grid_height=self.grid_height,
            projection=projection or ProjectionConfig(),
        )
        with self.lock:
            self.sessions[session.id] = session
        return session

    def get(self, session_id: str) -> HeatmapSession | None:
        with self.lock:
            return self.sessions.get(session_id)

    def stop_and_persist(self, session_id: str) -> HeatmapSession | None:
        session = self.get(session_id)
        if session is None:
            return None
        session.stop()
        if session.saved_heatmap_path is None:
            session.persist_artifacts(self.output_dir)
        return session
