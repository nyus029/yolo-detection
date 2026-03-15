import { writable } from "svelte/store";

import { fetchHeatmapData } from "./api-client";
import type { HeatmapData } from "./types";

export const heatmapData = writable<HeatmapData | null>(null);

let intervalId: number | null = null;
let currentSessionId: string | null = null;

async function pollOnce(sessionId: string): Promise<void> {
  try {
    const data = await fetchHeatmapData(sessionId);
    if (currentSessionId === sessionId) {
      heatmapData.set(data);
    }
  } catch {
    if (currentSessionId === sessionId) {
      heatmapData.set(null);
    }
  }
}

export function startPolling(sessionId: string, intervalMs = 2000): void {
  stopPolling();
  currentSessionId = sessionId;
  void pollOnce(sessionId);
  intervalId = window.setInterval(() => {
    void pollOnce(sessionId);
  }, intervalMs);
}

export function stopPolling(): void {
  if (intervalId !== null) {
    window.clearInterval(intervalId);
    intervalId = null;
  }
  currentSessionId = null;
}

export function setHeatmapData(data: HeatmapData | null): void {
  heatmapData.set(data);
}
