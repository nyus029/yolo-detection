from __future__ import annotations

from typing import Any

import numpy as np
from ultralytics import YOLO


class YOLOPersonDetector:
    PERSON_CLASS_ID = 0
    TARGET_CLASS_IDS = [0, 56, 57, 58, 59, 60, 62]
    FURNITURE_LABELS = {
        "chair": "chair",
        "couch": "sofa",
        "potted plant": "plant",
        "bed": "bed",
        "dining table": "table",
        "tv": "tv",
    }

    def __init__(self, model_name: str = "yolov8n.pt") -> None:
        self.model_name = model_name
        self.model = YOLO(model_name)

    def detect_scene(self, frame: np.ndarray) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        result = self.model.predict(source=frame, verbose=False, conf=0.28, classes=self.TARGET_CLASS_IDS)[0]
        person_detections: list[dict[str, Any]] = []
        furniture_detections: list[dict[str, Any]] = []
        counts = {"person": 0, "furniture": 0}

        if result.boxes is None:
            return person_detections, furniture_detections, counts

        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy().astype(int)
        names = result.names

        for i in range(len(boxes)):
            class_id = int(classes[i])
            class_name = str(names.get(class_id, class_id))
            detection = {
                "bbox": [float(v) for v in boxes[i]],
                "score": float(scores[i]),
                "class_id": class_id,
                "class_name": class_name,
            }

            if class_id == self.PERSON_CLASS_ID:
                counts["person"] += 1
                person_detections.append(detection)
                continue

            furniture_type = self.FURNITURE_LABELS.get(class_name)
            if furniture_type is None:
                continue

            counts["furniture"] += 1
            detection["furniture_type"] = furniture_type
            furniture_detections.append(detection)

        return person_detections, furniture_detections, counts

    def detect_people(self, frame: np.ndarray) -> tuple[list[dict[str, Any]], dict[str, int]]:
        detections, _, counts = self.detect_scene(frame)
        return detections, {"person": counts["person"]}
