from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO

app = FastAPI(title="YOLOv8 Motion Detection PoC")
app.mount("/static", StaticFiles(directory="static"), name="static")

model = YOLO("yolov8n-pose.pt")


def detect_actions(keypoints: np.ndarray, conf: np.ndarray) -> list[str]:
    actions: list[str] = []
    # COCO keypoint index: 5/6 shoulder, 9/10 wrist
    left_shoulder = keypoints[5]
    right_shoulder = keypoints[6]
    left_wrist = keypoints[9]
    right_wrist = keypoints[10]

    left_ok = conf[5] > 0.3 and conf[9] > 0.3
    right_ok = conf[6] > 0.3 and conf[10] > 0.3

    if (left_ok and left_wrist[1] < left_shoulder[1]) or (
        right_ok and right_wrist[1] < right_shoulder[1]
    ):
        actions.append("hand_raised")

    return actions


@app.get("/")
def root() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": "yolov8n-pose.pt"}


@app.post("/detect")
async def detect(file: UploadFile = File(...)) -> dict[str, Any]:
    image_bytes = await file.read()
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return {"detections": [], "message": "invalid image"}

    result = model.predict(source=frame, verbose=False, conf=0.3)[0]
    detections: list[dict[str, Any]] = []

    if result.keypoints is not None and result.boxes is not None:
        xy = result.keypoints.xy.cpu().numpy()
        conf = result.keypoints.conf.cpu().numpy()
        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()

        for i in range(min(len(xy), len(boxes))):
            actions = detect_actions(xy[i], conf[i])
            detections.append(
                {
                    "bbox": [float(v) for v in boxes[i]],
                    "score": float(scores[i]),
                    "actions": actions,
                    "keypoints": [[float(x), float(y)] for x, y in xy[i]],
                }
            )

    return {"detections": detections}
