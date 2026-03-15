from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.detection import YOLOPersonDetector
from app.heatmap import ProjectionConfig, SessionStore
from app.structure import estimate_projection_from_frame


def register_routes(app: FastAPI, detector: YOLOPersonDetector, session_store: SessionStore) -> None:
    @app.get("/")
    def root() -> FileResponse:
        return FileResponse("static/index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model": detector.model_name}

    @app.post("/estimate-structure")
    async def estimate_structure(file: UploadFile = File(...)) -> dict[str, Any]:
        frame = await decode_upload(file)
        return estimate_projection_from_frame(frame)

    @app.post("/session/start")
    def start_session(
        duration_minutes: int = Form(default=60),
        room_width_units: float = Form(default=10.0),
        room_height_units: float = Form(default=10.0),
        floor_top_y_ratio: float = Form(default=0.35),
        floor_top_width_ratio: float = Form(default=0.38),
        floor_bottom_width_ratio: float = Form(default=1.0),
    ) -> dict[str, Any]:
        if duration_minutes <= 0 or duration_minutes > 24 * 60:
            raise HTTPException(status_code=400, detail="duration_minutes must be between 1 and 1440")

        session = session_store.create(
            duration_minutes=duration_minutes,
            projection=ProjectionConfig(
                room_width_units=room_width_units,
                room_height_units=room_height_units,
                floor_top_y_ratio=floor_top_y_ratio,
                floor_top_width_ratio=floor_top_width_ratio,
                floor_bottom_width_ratio=floor_bottom_width_ratio,
            ),
        )
        return session.to_status()

    @app.post("/session/{session_id}/stop")
    def stop_session(session_id: str) -> dict[str, Any]:
        session = session_store.stop_and_persist(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session.to_status()

    @app.get("/session/{session_id}/status")
    def session_status(session_id: str) -> dict[str, Any]:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

        if not session.is_active and session.ended_at is None:
            session_store.stop_and_persist(session_id)

        return session.to_status()

    @app.get("/session/{session_id}/heatmap.png")
    def session_heatmap(session_id: str) -> Response:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

        image_bytes = session.render_heatmap_png()
        if image_bytes is None:
            raise HTTPException(status_code=409, detail="heatmap not ready")

        return Response(content=image_bytes, media_type="image/png")

    @app.post("/detect")
    async def detect(
        file: UploadFile = File(...),
        session_id: str | None = Form(default=None),
    ) -> dict[str, Any]:
        frame = await decode_upload(file, allow_invalid=True)
        if frame is None:
            return {"detections": [], "counts": {"person": 0}, "message": "invalid image"}

        detections, counts = detector.detect_people(frame)
        session_status_payload = update_session(session_store, session_id, frame, detections)
        return {"detections": detections, "counts": counts, "session": session_status_payload}


async def decode_upload(file: UploadFile, allow_invalid: bool = False) -> np.ndarray | None:
    image_bytes = await file.read()
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if frame is None and not allow_invalid:
        raise HTTPException(status_code=400, detail="invalid image")

    return frame


def update_session(
    session_store: SessionStore,
    session_id: str | None,
    frame: np.ndarray,
    detections: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not session_id:
        return None

    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if not session.is_active:
        session = session_store.stop_and_persist(session_id)
    else:
        session.add_frame(frame, detections)

    return session.to_status()
