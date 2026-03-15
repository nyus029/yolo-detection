import type { HistoryItem } from "./types";

const HISTORY_STORAGE_KEY = "personHeatmapHistory";
const HISTORY_LIMIT = 10;

export function loadHistory(): HistoryItem[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "[]") as HistoryItem[];
  } catch {
    return [];
  }
}

export function saveHistory(items: HistoryItem[]): void {
  localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items.slice(0, HISTORY_LIMIT)));
}
