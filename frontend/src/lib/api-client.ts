import type { DetectResponse, EstimateStructureResponse, HeatmapData, SessionStatus, StartSessionInput } from "./types";

export async function fetchHeatmapDataUrl(sessionId: string | null): Promise<string | null> {
  if (!sessionId) return null;

  const res = await fetch(`/session/${sessionId}/heatmap.png?t=${Date.now()}`);
  if (!res.ok) return null;

  const blob = await res.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Failed to read heatmap blob"));
    reader.readAsDataURL(blob);
  });
}

export async function stopSession(sessionId: string): Promise<Response> {
  return fetch(`/session/${sessionId}/stop`, { method: "POST" });
}

export async function fetchHeatmapData(sessionId: string): Promise<HeatmapData> {
  const res = await fetch(`/session/${sessionId}/heatmap-data?t=${Date.now()}`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  return res.json() as Promise<HeatmapData>;
}

export async function detectFrame(blob: Blob, sessionId: string | null): Promise<DetectResponse> {
  const form = new FormData();
  form.append("file", blob, "frame.jpg");
  if (sessionId) {
    form.append("session_id", sessionId);
  }

  const res = await fetch("/detect", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  return res.json() as Promise<DetectResponse>;
}

export async function estimateStructure(blob: Blob): Promise<EstimateStructureResponse> {
  const form = new FormData();
  form.append("file", blob, "structure.jpg");

  const res = await fetch("/estimate-structure", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  return res.json() as Promise<EstimateStructureResponse>;
}

export async function startSession(settings: StartSessionInput): Promise<SessionStatus> {
  const form = new FormData();
  form.append("duration_minutes", String(settings.durationMinutes));
  form.append("room_width_units", String(settings.roomWidthUnits));
  form.append("room_height_units", String(settings.roomHeightUnits));
  form.append("floor_top_y_ratio", String(settings.floorTopYRatio));
  form.append("floor_top_width_ratio", String(settings.floorTopWidthRatio));
  form.append("floor_bottom_width_ratio", String(settings.floorBottomWidthRatio));

  const res = await fetch("/session/start", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }

  return res.json() as Promise<SessionStatus>;
}
