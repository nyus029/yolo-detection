<script lang="ts">
  import { onMount } from "svelte";
  import { detectFrame, estimateStructure, fetchHeatmapDataUrl, startSession, stopSession } from "./lib/api-client";
  import { createCameraController, type CameraController } from "./lib/camera";
  import { loadHistory, saveHistory } from "./lib/history";
  import type { Detection, HistoryItem, SessionStatus } from "./lib/types";

  let videoEl: HTMLVideoElement;
  let overlayEl: HTMLCanvasElement;
  let overlayCtx: CanvasRenderingContext2D | null = null;
  let camera: CameraController | null = null;

  let durationMinutes = 60;
  let intervalMs = 1000;
  let roomWidthUnits = 10;
  let roomHeightUnits = 10;
  let floorTopYRatio = 0.35;
  let floorTopWidthRatio = 0.38;
  let floorBottomWidthRatio = 1.0;

  let running = false;
  let sessionId: string | null = null;
  let sessionStartedAt: string | null = null;
  let wakeLock: { release: () => Promise<void> } | null = null;
  let cameraActive = false;
  let structureEstimated = false;
  let statusText = "未開始";
  let stateActive = false;
  let elapsedLabel = "00:00";
  let remainingLabel = "--:--";
  let framesCount = 0;
  let peopleCount = 0;
  let heatmapSrc = "";
  let historyItems: HistoryItem[] = [];

  function formatSeconds(totalSeconds: number | null | undefined): string {
    if (totalSeconds == null || Number.isNaN(totalSeconds)) return "--:--";
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function drawDetections(detections: Detection[], width: number, height: number): void {
    if (!overlayCtx) return;

    overlayEl.width = width;
    overlayEl.height = height;
    overlayCtx.clearRect(0, 0, width, height);
    overlayCtx.lineWidth = 3;
    overlayCtx.font = '16px "Geist Mono", monospace';

    detections.forEach((detection) => {
      const [x1, y1, x2, y2] = detection.bbox;
      const boxWidth = x2 - x1;
      const boxHeight = y2 - y1;
      const footX = (x1 + x2) / 2;
      const footY = y2;

      overlayCtx!.strokeStyle = "#22c55e";
      overlayCtx!.strokeRect(x1, y1, boxWidth, boxHeight);
      overlayCtx!.beginPath();
      overlayCtx!.arc(footX, footY, 6, 0, Math.PI * 2);
      overlayCtx!.fillStyle = "#eab308";
      overlayCtx!.fill();
      overlayCtx!.fillStyle = "rgba(0,0,0,0.6)";
      overlayCtx!.fillRect(x1, Math.max(0, y1 - 24), 110, 22);
      overlayCtx!.fillStyle = "#fff";
      overlayCtx!.fillText(`person ${Math.round((detection.score || 0) * 100)}%`, x1 + 6, Math.max(16, y1 - 8));
    });
  }

  function applySessionStatus(session: SessionStatus): void {
    sessionStartedAt = session.started_at;
    stateActive = session.is_active;
    framesCount = session.processed_frames || 0;
    peopleCount = session.last_person_count || 0;
    remainingLabel = formatSeconds(session.remaining_seconds);

    if (sessionStartedAt) {
      const elapsed = Math.max(0, Math.floor((Date.now() - new Date(sessionStartedAt).getTime()) / 1000));
      elapsedLabel = formatSeconds(elapsed);
    }
  }

  async function refreshHeatmap(): Promise<void> {
    if (!sessionId) return;
    heatmapSrc = `/session/${sessionId}/heatmap.png?t=${Date.now()}`;
  }

  async function persistLocalHistory(session: SessionStatus): Promise<void> {
    const imageDataUrl = await fetchHeatmapDataUrl(sessionId);
    if (!imageDataUrl) return;

    historyItems = [
      {
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
      },
      ...historyItems,
    ].slice(0, 10);
    saveHistory(historyItems);
  }

  async function stopMeasurement(reason = "計測停止"): Promise<void> {
    if (!running) return;

    running = false;
    stateActive = false;

    if (sessionId) {
      try {
        const res = await stopSession(sessionId);
        if (res.ok) {
          const session = (await res.json()) as SessionStatus;
          applySessionStatus(session);
          await persistLocalHistory(session);
        }
      } catch (error) {
        statusText = `停止APIエラー: ${error}`;
      }
    }

    await refreshHeatmap();

    if (wakeLock) {
      try {
        await wakeLock.release();
      } catch {
        // no-op
      }
      wakeLock = null;
    }

    statusText = reason;
  }

  async function sendFrameLoop(): Promise<void> {
    while (running && camera) {
      const { width, height } = camera.getVideoSize();
      if (width === 0 || height === 0) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        continue;
      }

      try {
        const blob = await camera.captureFrameBlob(0.7);
        const data = await detectFrame(blob, sessionId);

        drawDetections(data.detections || [], width, height);
        peopleCount = data.counts?.person || 0;

        if (data.session) {
          applySessionStatus(data.session);
          if (!data.session.is_active) {
            await stopMeasurement("計測時間が終了しました");
            return;
          }
        }

        statusText = `人物検出中: ${peopleCount}人 / 平面投影: ${data.session?.projected_points || 0}`;
      } catch (error) {
        statusText = `通信エラー: ${error}`;
      }

      await new Promise((resolve) => setTimeout(resolve, Math.max(200, Number(intervalMs) || 1000)));
    }
  }

  async function handleStartCamera(): Promise<void> {
    if (!camera) return;
    await camera.ensureCamera();
    cameraActive = true;
    structureEstimated = false;
    statusText = "カメラ起動済み。次に部屋の構造推定を実行してください。";
  }

  async function handleEstimateStructure(): Promise<void> {
    if (!camera || !camera.hasStream()) {
      throw new Error("先にカメラ起動を押してください");
    }

    const blob = await camera.captureFrameBlob(0.85);
    const data = await estimateStructure(blob);

    floorTopYRatio = data.projection.floor_top_y_ratio ?? floorTopYRatio;
    floorTopWidthRatio = data.projection.floor_top_width_ratio ?? floorTopWidthRatio;
    floorBottomWidthRatio = data.projection.floor_bottom_width_ratio ?? floorBottomWidthRatio;
    structureEstimated = true;
    statusText = `構造推定完了 (confidence=${data.confidence ?? "n/a"})。計測開始できます。`;
  }

  async function handleStartMeasurement(): Promise<void> {
    if (!camera || !camera.hasStream()) {
      throw new Error("先にカメラ起動を押してください");
    }
    if (!structureEstimated) {
      throw new Error("先に部屋の構造推定を実行してください");
    }

    const session = await startSession({
      durationMinutes: Math.max(1, Number(durationMinutes) || 60),
      roomWidthUnits: Math.max(1, Number(roomWidthUnits) || 10),
      roomHeightUnits: Math.max(1, Number(roomHeightUnits) || 10),
      floorTopYRatio: Number(floorTopYRatio) || 0.35,
      floorTopWidthRatio: Number(floorTopWidthRatio) || 0.38,
      floorBottomWidthRatio: Number(floorBottomWidthRatio) || 1.0,
    });

    sessionId = session.session_id;
    running = true;
    stateActive = true;
    applySessionStatus(session);
    statusText = "部屋平面ヒートマップ計測を開始しました";

    if ("wakeLock" in navigator) {
      try {
        wakeLock = await (navigator as Navigator & {
          wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> };
        }).wakeLock?.request("screen") ?? null;
      } catch {
        wakeLock = null;
      }
    }

    void sendFrameLoop();
  }

  onMount(() => {
    overlayCtx = overlayEl.getContext("2d");
    videoEl.setAttribute("webkit-playsinline", "true");
    camera = createCameraController(videoEl);
    historyItems = loadHistory();
  });
</script>

<svelte:head>
  <link rel="preconnect" href="https://cdn.jsdelivr.net" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/latin.css" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/geist-mono@5.0.3/latin-400.css" />
</svelte:head>

<div class="wrap">
  <h1>YOLOv8 Person Heatmap PoC</h1>
  <p class="hint">
    固定したスマホカメラから人物のみを検出し、足元位置を床面へ推定投影して、部屋平面の長方形ヒートマップを作成します。
    `カメラ起動` -> `部屋の構造推定` -> `計測開始` の順で操作してください。
  </p>

  <section class="card">
    <h2 class="card-title">計測設定</h2>
    <div class="controls">
      <div class="field">
        <label for="durationInput">計測時間（分）</label>
        <input id="durationInput" type="number" min="1" max="1440" bind:value={durationMinutes} />
      </div>
      <div class="field">
        <label for="intervalInput">送信間隔（ms）</label>
        <input id="intervalInput" type="number" min="200" max="5000" bind:value={intervalMs} />
      </div>
      <div class="field">
        <label for="roomWidthInput">部屋幅（任意単位）</label>
        <input id="roomWidthInput" type="number" min="1" step="0.5" bind:value={roomWidthUnits} />
      </div>
      <div class="field">
        <label for="roomHeightInput">部屋奥行（任意単位）</label>
        <input id="roomHeightInput" type="number" min="1" step="0.5" bind:value={roomHeightUnits} />
      </div>
      <div class="field">
        <label for="floorTopInput">床開始Y比率</label>
        <input id="floorTopInput" type="number" min="0.05" max="0.95" step="0.01" bind:value={floorTopYRatio} />
      </div>
      <div class="field">
        <label for="topWidthInput">奥側の見かけ幅</label>
        <input id="topWidthInput" type="number" min="0.05" max="1" step="0.01" bind:value={floorTopWidthRatio} />
      </div>
      <div class="field">
        <label for="bottomWidthInput">手前の見かけ幅</label>
        <input id="bottomWidthInput" type="number" min="0.05" max="1" step="0.01" bind:value={floorBottomWidthRatio} />
      </div>
      <button class="btn-primary" type="button" disabled={cameraActive} onclick={async () => {
        try {
          await handleStartCamera();
        } catch (error) {
          statusText = `カメラ起動失敗: ${error}`;
        }
      }}>カメラ起動</button>
      <button class="btn-primary" type="button" disabled={!cameraActive || running} onclick={async () => {
        try {
          await handleEstimateStructure();
        } catch (error) {
          statusText = `構造推定失敗: ${error}`;
        }
      }}>部屋の構造推定</button>
      <button class="btn-success" type="button" disabled={!cameraActive || !structureEstimated || running} onclick={async () => {
        try {
          await handleStartMeasurement();
        } catch (error) {
          statusText = `開始失敗: ${error}`;
        }
      }}>計測開始</button>
      <button class="btn-danger" type="button" disabled={!running} onclick={() => void stopMeasurement("ユーザーが計測を停止しました")}>計測停止</button>
    </div>
  </section>

  <section class="card">
    <div id="videoWrap">
      <video bind:this={videoEl} playsinline autoplay muted aria-label="カメラ映像"></video>
      <canvas bind:this={overlayEl} id="overlay" aria-hidden="true"></canvas>
    </div>
  </section>

  <section class="card">
    <h2 class="card-title">計測状況</h2>
    <div class="stats">
      <div class="stat">
        <div class="statLabel">状態</div>
        <div class="statValue">
          <span class="badge" class:badge-success={stateActive} class:badge-neutral={!stateActive}>
            <span class="badge-dot"></span> {stateActive ? "計測中" : "待機中"}
          </span>
        </div>
      </div>
      <div class="stat">
        <div class="statLabel">経過時間</div>
        <div class="statValue">{elapsedLabel}</div>
      </div>
      <div class="stat">
        <div class="statLabel">残り時間</div>
        <div class="statValue">{remainingLabel}</div>
      </div>
      <div class="stat">
        <div class="statLabel">処理フレーム数</div>
        <div class="statValue">{framesCount}</div>
      </div>
      <div class="stat">
        <div class="statLabel">現在の検出人数</div>
        <div class="statValue">{peopleCount}</div>
      </div>
    </div>
    <p id="status">{statusText}</p>
  </section>

  <section class="card heatmapPanel">
    <h2 class="card-title">ヒートマップ</h2>
    <p>カメラ画像ではなく、部屋平面を長方形で表した占有ヒートマップです。上側が奥、下側がカメラ手前です。</p>
    <div class="heatmapFrame">
      <img src={heatmapSrc} alt="人物ヒートマップ" />
    </div>
  </section>

  <section class="card">
    <h2 class="card-title">ローカル履歴</h2>
    <div class="historyList">
      {#if historyItems.length === 0}
        <p class="historyEmpty">まだ保存されたヒートマップはありません。</p>
      {:else}
        {#each historyItems as item (item.savedAt + item.sessionId)}
          <article class="historyItem">
            <img class="historyThumb" src={item.imageDataUrl} alt="保存済みヒートマップ" />
            <div class="historyMeta">
              <div class="historyTitle">{item.savedAtLabel}</div>
              <div class="historyText">セッションID: {item.sessionId}</div>
              <div class="historyText">計測時間: {item.durationMinutes}分 / 処理フレーム: {item.processedFrames}</div>
              <div class="historyText">累積人物検出: {item.personDetections} / 平面投影: {item.projectedPoints}</div>
              <div class="historyText">部屋設定: {item.roomWidth} x {item.roomHeight} / floorTop={item.floorTopY}</div>
              <div class="historyText">サーバ保存PNG: {item.savedHeatmapPath || "未保存"}</div>
              <div class="historyText">サーバ保存JSON: {item.savedMetadataPath || "未保存"}</div>
            </div>
          </article>
        {/each}
      {/if}
    </div>
  </section>
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: "Geist Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.5;
    color: #0a0a0a;
    background: #ffffff;
    -webkit-font-smoothing: antialiased;
  }

  :global(*) {
    box-sizing: border-box;
  }

  .wrap {
    max-width: 920px;
    margin: 0 auto;
    padding: 32px 16px;
  }

  h1 {
    margin: 0 0 8px;
    font-size: 1.75rem;
    font-weight: 600;
    letter-spacing: -0.02em;
  }

  .hint,
  #status,
  .heatmapPanel p,
  .historyText,
  .historyEmpty {
    color: #737373;
    font-size: 0.875rem;
  }

  .card {
    margin-top: 16px;
    padding: 20px;
    background: #fafafa;
    border: 1px solid #e5e5e5;
    border-radius: 12px;
  }

  .card-title {
    margin: 0 0 8px;
    font-size: 0.8125rem;
    font-weight: 600;
    color: #737373;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 16px;
  }

  .field {
    display: grid;
    gap: 4px;
  }

  .field label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: #737373;
  }

  .field input {
    width: 120px;
    height: 40px;
    padding: 0 12px;
    font-family: "Geist Mono", ui-monospace, monospace;
    font-size: 0.875rem;
    color: #0a0a0a;
    background: #ffffff;
    border: 1px solid #e5e5e5;
    border-radius: 8px;
  }

  button {
    font-family: "Geist Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 0.875rem;
    font-weight: 500;
    height: 40px;
    padding: 0 16px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-primary {
    background: #0a0a0a;
    color: #ffffff;
  }

  .btn-success {
    background: #22c55e;
    color: #ffffff;
  }

  .btn-danger {
    background: #ef4444;
    color: #ffffff;
  }

  #videoWrap,
  .heatmapFrame {
    position: relative;
    margin-top: 16px;
    border-radius: 12px;
    overflow: hidden;
    background: #000;
    border: 1px solid #e5e5e5;
  }

  video,
  canvas,
  img {
    width: 100%;
    display: block;
  }

  #overlay {
    position: absolute;
    left: 0;
    top: 0;
    pointer-events: none;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
  }

  .stat {
    padding: 12px 0;
  }

  .statLabel {
    font-size: 0.75rem;
    font-weight: 500;
    color: #737373;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .statValue {
    margin-top: 4px;
    font-family: "Geist Mono", ui-monospace, monospace;
    font-size: 1.25rem;
    font-weight: 600;
    color: #0a0a0a;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    font-size: 0.75rem;
    font-weight: 500;
    border-radius: 9999px;
  }

  .badge-neutral {
    background: #f5f5f5;
    color: #737373;
  }

  .badge-success {
    background: rgba(34, 197, 94, 0.15);
    color: #22c55e;
  }

  .badge-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
  }

  .historyList {
    display: grid;
    gap: 16px;
  }

  .historyItem {
    display: grid;
    grid-template-columns: 160px 1fr;
    gap: 16px;
    padding: 12px;
    border: 1px solid #e5e5e5;
    border-radius: 8px;
    background: #ffffff;
  }

  .historyThumb {
    width: 100%;
    border-radius: 8px;
    border: 1px solid #e5e5e5;
    background: #fafafa;
  }

  .historyMeta {
    display: grid;
    gap: 4px;
    min-width: 0;
  }

  .historyTitle {
    font-weight: 600;
  }

  @media (max-width: 640px) {
    .historyItem {
      grid-template-columns: 1fr;
    }
  }
</style>
