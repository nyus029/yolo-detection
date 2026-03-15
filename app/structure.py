from __future__ import annotations

from typing import Any

import cv2
import numpy as np


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
