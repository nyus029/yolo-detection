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


def room_layout_metrics(
    width: int,
    height: int,
    projection: ProjectionConfig,
) -> dict[str, Any]:
    outer_padding = max(14, int(min(width, height) * 0.04))
    room_x = outer_padding
    room_y = outer_padding
    room_width = max(120, width - outer_padding * 2)
    room_height = max(120, height - outer_padding * 2)
    wall_thickness = int(clamp(min(room_width, room_height) * 0.035, 8, 18))

    top_width = room_width * clamp(projection.floor_top_width_ratio, 0.08, 1.0)
    bottom_width = room_width * clamp(projection.floor_bottom_width_ratio, 0.08, 1.0)
    top_inset = int(round((room_width - top_width) / 2.0))
    bottom_inset = int(round((room_width - bottom_width) / 2.0))
    top_y = int(round(room_y + room_height * clamp(0.08 + projection.floor_top_y_ratio * 0.42, 0.1, 0.5)))
    bottom_y = int(round(room_y + room_height - wall_thickness * 1.4))
    door_width = int(clamp(room_width * 0.2, 36, 96))
    camera_x = int(round(room_x + room_width / 2.0))
    camera_y = int(round(room_y + room_height + wall_thickness * 2.0))

    visible_zone = np.array(
        [
            [room_x + top_inset, top_y],
            [room_x + room_width - top_inset, top_y],
            [room_x + room_width - bottom_inset, bottom_y],
            [room_x + bottom_inset, bottom_y],
        ],
        dtype=np.int32,
    )

    return {
        "room_x": room_x,
        "room_y": room_y,
        "room_width": room_width,
        "room_height": room_height,
        "wall_thickness": wall_thickness,
        "visible_zone": visible_zone,
        "door_width": door_width,
        "camera_x": camera_x,
        "camera_y": camera_y,
    }


def draw_room_plan(
    canvas: np.ndarray,
    projection: ProjectionConfig,
    heatmap: np.ndarray | None = None,
) -> None:
    layout = room_layout_metrics(canvas.shape[1], canvas.shape[0], projection)
    room_x = layout["room_x"]
    room_y = layout["room_y"]
    room_width = layout["room_width"]
    room_height = layout["room_height"]
    wall_thickness = layout["wall_thickness"]
    room_right = room_x + room_width
    room_bottom = room_y + room_height
    door_half = layout["door_width"] // 2
    visible_zone = layout["visible_zone"]

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
        smoothed = gaussian_filter(normalized, sigma=1.35)
        resized = cv2.resize(smoothed, (room_width, room_height), interpolation=cv2.INTER_CUBIC)
        blurred = cv2.GaussianBlur(resized, (0, 0), sigmaX=12, sigmaY=12)
        colored = cv2.applyColorMap(np.uint8(np.clip(blurred, 0.0, 1.0) * 255), cv2.COLORMAP_INFERNO)
        overlay = canvas[room_y:room_bottom, room_x:room_right].copy()
        canvas[room_y:room_bottom, room_x:room_right] = cv2.addWeighted(overlay, 0.28, colored, 0.72, 0.0)

    visible_fill = np.zeros_like(canvas)
    cv2.fillConvexPoly(visible_fill, visible_zone, (214, 220, 228))
    canvas[:] = cv2.addWeighted(canvas, 1.0, visible_fill, 0.16, 0.0)
    cv2.polylines(canvas, [visible_zone], True, (88, 98, 110), 2, cv2.LINE_AA)

    wall_color = (63, 63, 70)
    cv2.line(canvas, (room_x, room_y), (room_right, room_y), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (room_x, room_y), (room_x, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (room_right, room_y), (room_right, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (room_x, room_bottom), (layout["camera_x"] - door_half, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)
    cv2.line(canvas, (layout["camera_x"] + door_half, room_bottom), (room_right, room_bottom), wall_color, wall_thickness, cv2.LINE_AA)

    cv2.ellipse(
        canvas,
        (layout["camera_x"], room_bottom),
        (door_half, max(8, int(door_half * 0.55))),
        0,
        180,
        360,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.circle(canvas, (layout["camera_x"], layout["camera_y"]), 7, (15, 23, 42), -1, cv2.LINE_AA)
    cv2.line(canvas, (layout["camera_x"], layout["camera_y"] - 5), tuple(visible_zone[2]), (120, 130, 142), 1, cv2.LINE_AA)
    cv2.line(canvas, (layout["camera_x"], layout["camera_y"] - 5), tuple(visible_zone[3]), (120, 130, 142), 1, cv2.LINE_AA)


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
        x_ratio = clamp(foot_x / frame_width, 0.0, 1.0)
        y_ratio = clamp(foot_y / frame_height, 0.0, 1.0)
        top_y = self.projection.floor_top_y_ratio
        if y_ratio < top_y:
            return None

        depth_ratio = (y_ratio - top_y) / max(1e-6, 1.0 - top_y)
        visible_width = self.projection.floor_top_width_ratio + (
            self.projection.floor_bottom_width_ratio - self.projection.floor_top_width_ratio
        ) * depth_ratio
        if visible_width <= 0:
            return None

        plane_x = ((x_ratio - 0.5) / visible_width) + 0.5
        if plane_x < -0.2 or plane_x > 1.2:
            return None

        plane_x = clamp(plane_x, 0.0, 1.0)
        plane_y = clamp(depth_ratio, 0.0, 1.0)
        return plane_x, plane_y

    def add_frame(self, frame: np.ndarray, detections: list[dict[str, Any]]) -> None:
        frame_height, frame_width = frame.shape[:2]
        with self.lock:
            self.frame_width = frame_width
            self.frame_height = frame_height
            self.processed_frames += 1
            self.last_person_count = len(detections)
            self.person_detections += len(detections)

            for detection in detections:
                x1, _, x2, y2 = detection["bbox"]
                foot_x = clamp((x1 + x2) / 2.0, 0.0, float(frame_width - 1))
                foot_y = clamp(y2, 0.0, float(frame_height - 1))
                plane_point = self.project_to_plane(foot_x, foot_y, frame_width, frame_height)
                if plane_point is None:
                    self.ignored_points += 1
                    continue

                plane_x, plane_y = plane_point
                grid_x = min(self.grid_width - 1, int(plane_x * self.grid_width))
                grid_y = min(self.grid_height - 1, int(plane_y * self.grid_height))
                self.heatmap[grid_y, grid_x] += 1.0
                self.projected_points += 1

    def to_status(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        remaining_seconds = max(0, int((self.expires_at - now).total_seconds()))
        ended_at = self.ended_at.isoformat() if self.ended_at else None
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
        }

    def to_heatmap_data(self) -> dict[str, Any]:
        with self.lock:
            heatmap = self.heatmap.copy()
            current_count = self.last_person_count

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
        }

    def render_heatmap_png(self) -> bytes | None:
        with self.lock:
            heatmap = self.heatmap.copy()

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
        draw_room_plan(plane, self.projection, heatmap)
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
        cv2.putText(
            canvas,
            "Far side",
            (margin_left + plane_width - 118, margin_top - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (60, 60, 60),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            "Near camera",
            (margin_left + plane_width - 145, margin_top + plane_height + 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (60, 60, 60),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            "camera",
            (margin_left + plane_width // 2 - 24, margin_top + plane_height + 54),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (71, 85, 105),
            1,
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
