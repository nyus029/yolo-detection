from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO

from app.heatmap import ProjectionConfig, SessionStore

app = FastAPI(title="YOLOv8 Object Detection PoC")
app.mount("/static", StaticFiles(directory="static"), name="static")

model = YOLO("yolov8n.pt")
session_store = SessionStore()


def estimate_projection_from_frame(frame: np.ndarray) -> dict[str, Any]:
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 60, 140)

    search_top = int(height * 0.2)
    search_bottom = int(height * 0.9)
    if search_bottom <= search_top:
        search_top = 0
        search_bottom = height

    density = edges[search_top:search_bottom].sum(axis=1) / 255.0
    threshold = max(12.0, float(np.percentile(density, 65)))
    hit_rows = np.where(density >= threshold)[0]

    if len(hit_rows) > 0:
        top_row = int(search_top + hit_rows[0])
    else:
        top_row = int(height * 0.35)

    band_half = max(6, int(height * 0.015))
    band_top = max(0, top_row - band_half)
    band_bottom = min(height, top_row + band_half)
    band = edges[band_top:band_bottom]
    xs = np.where(band > 0)[1]

    if len(xs) > 80:
        left = int(np.percentile(xs, 10))
        right = int(np.percentile(xs, 90))
        top_width_ratio = float((right - left) / max(1, width))
    else:
        top_width_ratio = 0.38

    floor_top_y_ratio = float(top_row / max(1, height))
    floor_top_y_ratio = float(np.clip(floor_top_y_ratio, 0.15, 0.7))
    top_width_ratio = float(np.clip(top_width_ratio, 0.15, 0.9))

    confidence = 0.45
    if len(hit_rows) > 0:
        confidence += 0.2
    if len(xs) > 80:
        confidence += 0.25
    confidence = float(np.clip(confidence, 0.0, 0.95))

    return {
        "projection": {
            "floor_top_y_ratio": round(floor_top_y_ratio, 3),
            "floor_top_width_ratio": round(top_width_ratio, 3),
            "floor_bottom_width_ratio": 1.0,
        },
        "confidence": round(confidence, 2),
        "frame_width": width,
        "frame_height": height,
        "message": "estimated from current camera frame",
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": "yolov8n.pt"}


@app.post("/estimate-structure")
async def estimate_structure(file: UploadFile = File(...)) -> dict[str, Any]:
    image_bytes = await file.read()
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="invalid image")

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
    image_bytes = await file.read()
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return {"detections": [], "counts": {"person": 0}, "message": "invalid image"}

    result = model.predict(source=frame, verbose=False, conf=0.3, classes=[0])[0]
    detections: list[dict[str, Any]] = []
    counts = {"person": 0}

    if result.boxes is not None:
        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy().astype(int)
        names = result.names

        for i in range(len(boxes)):
            class_id = int(classes[i])
            class_name = str(names.get(class_id, class_id))
            if class_name != "person":
                continue
            counts["person"] += 1
            detections.append(
                {
                    "bbox": [float(v) for v in boxes[i]],
                    "score": float(scores[i]),
                    "class_id": class_id,
                    "class_name": class_name,
                }
            )

    session_status_payload: dict[str, Any] | None = None
    if session_id:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if not session.is_active:
            session = session_store.stop_and_persist(session_id)
        else:
            session.add_frame(frame, detections)
        session_status_payload = session.to_status()

    return {"detections": detections, "counts": counts, "session": session_status_payload}
