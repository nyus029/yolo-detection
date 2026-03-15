from __future__ import annotations

from typing import Any

import numpy as np
from ultralytics import YOLO


class YOLOPersonDetector:
    def __init__(self, model_name: str = "yolov8n.pt") -> None:
        self.model_name = model_name
        self.model = YOLO(model_name)

    def detect_people(self, frame: np.ndarray) -> tuple[list[dict[str, Any]], dict[str, int]]:
        result = self.model.predict(source=frame, verbose=False, conf=0.3, classes=[0])[0]
        detections: list[dict[str, Any]] = []
        counts = {"person": 0}

        if result.boxes is None:
            return detections, counts

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

        return detections, counts
