from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import register_routes
from app.detection import YOLOPersonDetector
from app.heatmap import SessionStore

app = FastAPI(title="YOLOv8 Object Detection PoC")
app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

detector = YOLOPersonDetector()
session_store = SessionStore()

register_routes(app, detector, session_store)
