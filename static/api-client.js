export async function fetchHeatmapDataUrl(sessionId) {
  if (!sessionId) return null;

  const res = await fetch(`/session/${sessionId}/heatmap.png?t=${Date.now()}`);
  if (!res.ok) return null;

  const blob = await res.blob();
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Failed to read heatmap blob"));
    reader.readAsDataURL(blob);
  });
}

export async function stopSession(sessionId) {
  return fetch(`/session/${sessionId}/stop`, { method: "POST" });
}

export async function detectFrame(blob, sessionId) {
  const form = new FormData();
  form.append("file", blob, "frame.jpg");
  if (sessionId) {
    form.append("session_id", sessionId);
  }

  return fetch("/detect", { method: "POST", body: form });
}

export async function estimateStructure(blob) {
  const form = new FormData();
  form.append("file", blob, "structure.jpg");

  return fetch("/estimate-structure", { method: "POST", body: form });
}

export async function startSession(settings) {
  const form = new FormData();
  form.append("duration_minutes", String(settings.durationMinutes));
  form.append("room_width_units", String(settings.roomWidthUnits));
  form.append("room_height_units", String(settings.roomHeightUnits));
  form.append("floor_top_y_ratio", String(settings.floorTopYRatio));
  form.append("floor_top_width_ratio", String(settings.floorTopWidthRatio));
  form.append("floor_bottom_width_ratio", String(settings.floorBottomWidthRatio));

  return fetch("/session/start", { method: "POST", body: form });
}
