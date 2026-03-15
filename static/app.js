import {
  detectFrame,
  estimateStructure as requestStructureEstimate,
  fetchHeatmapDataUrl,
  startSession,
  stopSession,
} from "./api-client.js";
import { createCameraController } from "./camera.js";
import { loadHistory, renderHistory, saveHistory } from "./history.js";

const video = document.getElementById("video");
const overlay = document.getElementById("overlay");
const statusEl = document.getElementById("status");
const cameraBtn = document.getElementById("cameraBtn");
const estimateBtn = document.getElementById("estimateBtn");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const durationInput = document.getElementById("durationInput");
const intervalInput = document.getElementById("intervalInput");
const roomWidthInput = document.getElementById("roomWidthInput");
const roomHeightInput = document.getElementById("roomHeightInput");
const floorTopInput = document.getElementById("floorTopInput");
const topWidthInput = document.getElementById("topWidthInput");
const bottomWidthInput = document.getElementById("bottomWidthInput");
const stateBadge = document.getElementById("stateBadge");
const elapsedValue = document.getElementById("elapsedValue");
const remainingValue = document.getElementById("remainingValue");
const framesValue = document.getElementById("framesValue");
const peopleValue = document.getElementById("peopleValue");
const heatmapImage = document.getElementById("heatmapImage");
const historyList = document.getElementById("historyList");
const ctx = overlay.getContext("2d");
const camera = createCameraController(video);

let running = false;
let sessionId = null;
let sessionStartedAt = null;
let wakeLock = null;
let structureEstimated = false;

async function persistLocalHistory(session) {
  if (!session) return;
  const imageDataUrl = await fetchHeatmapDataUrl(sessionId);
  if (!imageDataUrl) return;

  const items = loadHistory();
  items.unshift({
    sessionId: session.session_id,
    savedAt: session.ended_at || new Date().toISOString(),
    savedAtLabel: new Date(session.ended_at || Date.now()).toLocaleString(),
    durationMinutes: session.duration_minutes || 0,
    processedFrames: session.processed_frames || 0,
    personDetections: session.person_detections || 0,
    projectedPoints: session.projected_points || 0,
    roomWidth: session.projection?.room_width_units || "",
    roomHeight: session.projection?.room_height_units || "",
    floorTopY: session.projection?.floor_top_y_ratio || "",
    savedHeatmapPath: session.saved_heatmap_path || "",
    savedMetadataPath: session.saved_metadata_path || "",
    imageDataUrl,
  });
  saveHistory(items);
  renderHistory(historyList, items);
}

function formatSeconds(totalSeconds) {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) return "--:--";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function setStateBadge(active) {
  stateBadge.className = active ? "badge badge-success" : "badge badge-neutral";
  stateBadge.innerHTML = active
    ? '<span class="badge-dot"></span> 計測中'
    : '<span class="badge-dot"></span> 待機中';
}

function drawDetections(detections, width, height) {
  overlay.width = width;
  overlay.height = height;
  ctx.clearRect(0, 0, width, height);
  ctx.lineWidth = 3;
  ctx.font = '16px "Geist Mono", monospace';

  detections.forEach((detection) => {
    const [x1, y1, x2, y2] = detection.bbox;
    const boxWidth = x2 - x1;
    const boxHeight = y2 - y1;
    const footX = (x1 + x2) / 2;
    const footY = y2;

    ctx.strokeStyle = "#22c55e";
    ctx.strokeRect(x1, y1, boxWidth, boxHeight);
    ctx.beginPath();
    ctx.arc(footX, footY, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#eab308";
    ctx.fill();
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(x1, Math.max(0, y1 - 24), 110, 22);
    ctx.fillStyle = "#fff";
    ctx.fillText(`person ${Math.round((detection.score || 0) * 100)}%`, x1 + 6, Math.max(16, y1 - 8));
  });
}

function applySessionStatus(session) {
  if (!session) return;
  sessionStartedAt = session.started_at;
  setStateBadge(!!session.is_active);
  framesValue.textContent = String(session.processed_frames || 0);
  peopleValue.textContent = String(session.last_person_count || 0);
  remainingValue.textContent = formatSeconds(session.remaining_seconds);
  if (sessionStartedAt) {
    const elapsed = Math.max(
      0,
      Math.floor((Date.now() - new Date(sessionStartedAt).getTime()) / 1000),
    );
    elapsedValue.textContent = formatSeconds(elapsed);
  }
}

async function refreshHeatmap() {
  if (!sessionId) return;
  heatmapImage.src = `/session/${sessionId}/heatmap.png?t=${Date.now()}`;
}

async function stopMeasurement(reason = "計測停止") {
  if (!running) return;
  running = false;
  setStateBadge(false);
  estimateBtn.disabled = !camera.hasStream();
  startBtn.disabled = !camera.hasStream() || !structureEstimated;
  stopBtn.disabled = true;

  if (sessionId) {
    try {
      const res = await stopSession(sessionId);
      if (res.ok) {
        const session = await res.json();
        applySessionStatus(session);
        await persistLocalHistory(session);
      }
    } catch (error) {
      statusEl.textContent = `停止APIエラー: ${error}`;
    }
  }

  await refreshHeatmap();

  if (wakeLock) {
    try {
      await wakeLock.release();
    } catch {}
    wakeLock = null;
  }

  statusEl.textContent = reason;
}

async function sendFrameLoop() {
  while (running) {
    const { width, height } = camera.getVideoSize();
    if (width === 0 || height === 0) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      continue;
    }

    try {
      const blob = await camera.captureFrameBlob(0.7);
      const res = await detectFrame(blob, sessionId);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      drawDetections(data.detections || [], width, height);
      const counts = data.counts || {};
      peopleValue.textContent = String(counts.person || 0);
      if (data.session) {
        applySessionStatus(data.session);
        if (!data.session.is_active) {
          await stopMeasurement("計測時間が終了しました");
          return;
        }
      }
      statusEl.textContent =
        `人物検出中: ${counts.person || 0}人 / 平面投影: ${data.session?.projected_points || 0}`;
    } catch (error) {
      statusEl.textContent = `通信エラー: ${error}`;
    }

    await new Promise((resolve) =>
      setTimeout(resolve, Math.max(200, Number(intervalInput.value) || 1000)),
    );
  }
}

async function startCamera() {
  await camera.ensureCamera();
  cameraBtn.disabled = true;
  estimateBtn.disabled = false;
  structureEstimated = false;
  startBtn.disabled = true;
  statusEl.textContent = "カメラ起動済み。次に部屋の構造推定を実行してください。";
}

async function estimateStructure() {
  if (!camera.hasStream()) {
    throw new Error("先にカメラ起動を押してください");
  }

  const blob = await camera.captureFrameBlob(0.85);
  const res = await requestStructureEstimate(blob);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const data = await res.json();
  const projection = data.projection || {};
  floorTopInput.value = String(projection.floor_top_y_ratio ?? floorTopInput.value);
  topWidthInput.value = String(projection.floor_top_width_ratio ?? topWidthInput.value);
  bottomWidthInput.value = String(projection.floor_bottom_width_ratio ?? bottomWidthInput.value);
  structureEstimated = true;
  startBtn.disabled = false;
  statusEl.textContent = `構造推定完了 (confidence=${data.confidence ?? "n/a"})。計測開始できます。`;
}

async function startMeasurement() {
  if (!camera.hasStream()) {
    throw new Error("先にカメラ起動を押してください");
  }
  if (!structureEstimated) {
    throw new Error("先に部屋の構造推定を実行してください");
  }
  const res = await startSession({
    durationMinutes: Math.max(1, Number(durationInput.value) || 60),
    roomWidthUnits: Math.max(1, Number(roomWidthInput.value) || 10),
    roomHeightUnits: Math.max(1, Number(roomHeightInput.value) || 10),
    floorTopYRatio: Number(floorTopInput.value) || 0.35,
    floorTopWidthRatio: Number(topWidthInput.value) || 0.38,
    floorBottomWidthRatio: Number(bottomWidthInput.value) || 1.0,
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  const session = await res.json();
  sessionId = session.session_id;
  running = true;
  setStateBadge(true);
  cameraBtn.disabled = true;
  estimateBtn.disabled = true;
  startBtn.disabled = true;
  stopBtn.disabled = false;
  applySessionStatus(session);
  statusEl.textContent = "部屋平面ヒートマップ計測を開始しました";

  if ("wakeLock" in navigator) {
    try {
      wakeLock = await navigator.wakeLock.request("screen");
    } catch {
      wakeLock = null;
    }
  }

  sendFrameLoop();
}

cameraBtn.addEventListener("click", async () => {
  if (camera.hasStream()) return;
  try {
    await startCamera();
  } catch (error) {
    statusEl.textContent = `カメラ起動失敗: ${error}`;
  }
});

estimateBtn.addEventListener("click", async () => {
  if (running) return;
  try {
    await estimateStructure();
  } catch (error) {
    statusEl.textContent = `構造推定失敗: ${error}`;
  }
});

startBtn.addEventListener("click", async () => {
  if (running) return;
  try {
    await startMeasurement();
  } catch (error) {
    statusEl.textContent = `開始失敗: ${error}`;
  }
});

stopBtn.addEventListener("click", async () => {
  await stopMeasurement("ユーザーが計測を停止しました");
});

renderHistory(historyList, loadHistory());
