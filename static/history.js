const HISTORY_STORAGE_KEY = "personHeatmapHistory";
const HISTORY_LIMIT = 10;

export function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

export function saveHistory(items) {
  localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items.slice(0, HISTORY_LIMIT)));
}

export function renderHistory(historyList, items) {
  if (items.length === 0) {
    historyList.innerHTML = '<p class="historyEmpty">まだ保存されたヒートマップはありません。</p>';
    return;
  }

  historyList.innerHTML = items
    .map(
      (item) => `
        <article class="historyItem">
          <img class="historyThumb" src="${item.imageDataUrl}" alt="保存済みヒートマップ" />
          <div class="historyMeta">
            <div class="historyTitle">${item.savedAtLabel}</div>
            <div class="historyText">セッションID: ${item.sessionId}</div>
            <div class="historyText">計測時間: ${item.durationMinutes}分 / 処理フレーム: ${item.processedFrames}</div>
            <div class="historyText">累積人物検出: ${item.personDetections} / 平面投影: ${item.projectedPoints}</div>
            <div class="historyText">部屋設定: ${item.roomWidth} x ${item.roomHeight} / floorTop=${item.floorTopY}</div>
            <div class="historyText">サーバ保存PNG: ${item.savedHeatmapPath || "未保存"}</div>
            <div class="historyText">サーバ保存JSON: ${item.savedMetadataPath || "未保存"}</div>
          </div>
        </article>
      `,
    )
    .join("");
}
