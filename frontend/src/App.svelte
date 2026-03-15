<script lang="ts">
  import { onMount } from "svelte";

  import ColorBar from "./lib/ColorBar.svelte";
  import HeatmapCanvas from "./lib/HeatmapCanvas.svelte";
  import { detectFrame, estimateStructure, fetchHeatmapDataUrl, startSession, stopSession } from "./lib/api-client";
  import { createCameraController, type CameraController } from "./lib/camera";
  import { loadHistory, saveHistory } from "./lib/history";
  import { heatmapData } from "./lib/heatmapStore";
  import { setHeatmapData, startPolling, stopPolling } from "./lib/heatmapStore";
  import type { Detection, HeatmapData, HistoryItem, SessionStatus } from "./lib/types";

  let videoEl: HTMLVideoElement;
  let overlayEl: HTMLCanvasElement;
  let overlayCtx: CanvasRenderingContext2D | null = null;
  let camera: CameraController | null = null;
  let liveHeatmapCanvas: { downloadPng: (filename?: string) => void } | null = null;
  let finalHeatmapCanvas: { downloadPng: (filename?: string) => void } | null = null;

  let durationMinutes = 60;
  let intervalMs = 1000;
  let roomWidthUnits = 10;
  let roomHeightUnits = 10;
  let floorTopYRatio = 0.35;
  let floorTopWidthRatio = 0.38;
  let floorBottomWidthRatio = 1.0;
  let heatmapRefreshMs = 2000;
  let blurRadius = 16;
  let showHeatmapGrid = false;

  let running = false;
  let sessionId: string | null = null;
  let sessionStartedAt: string | null = null;
  let lastCompletedSessionId: string | null = null;
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

  let latestHeatmap: HeatmapData | null = null;

  $: latestHeatmap = $heatmapData;

  $: peakSummary = (() => {
    if (!latestHeatmap?.grid?.length) {
      return null;
    }

    let peakValue = 0;
    let peakX = 0;
    let peakY = 0;
    for (let row = 0; row < latestHeatmap.grid.length; row += 1) {
      for (let col = 0; col < latestHeatmap.grid[row].length; col += 1) {
        const value = latestHeatmap.grid[row][col] ?? 0;
        if (value > peakValue) {
          peakValue = value;
          peakX = col;
          peakY = row;
        }
      }
    }

    return {
      peakValue,
      peakXLabel: `${peakX + 1}/${latestHeatmap.grid_width}`,
      peakYLabel: `${peakY + 1}/${latestHeatmap.grid_height}`,
    };
  })();

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
      overlayCtx!.fillStyle = "#fbbf24";
      overlayCtx!.fill();
      overlayCtx!.fillStyle = "rgba(5,10,20,0.72)";
      overlayCtx!.fillRect(x1, Math.max(0, y1 - 24), 116, 22);
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
    const imageDataUrl = await fetchHeatmapDataUrl(session.session_id);
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
    if (!running && !sessionId) return;

    running = false;
    stateActive = false;
    stopPolling();

    if (sessionId) {
      lastCompletedSessionId = sessionId;
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
    lastCompletedSessionId = null;
    heatmapSrc = "";
    setHeatmapData(null);
    running = true;
    stateActive = true;
    applySessionStatus(session);
    statusText = "部屋平面ヒートマップ計測を開始しました";
    startPolling(session.session_id, Math.max(1000, Number(heatmapRefreshMs) || 2000));

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

  function handleRestartMeasurement(): void {
    sessionId = null;
    lastCompletedSessionId = null;
    heatmapSrc = "";
    setHeatmapData(null);
    elapsedLabel = "00:00";
    remainingLabel = "--:--";
    framesCount = 0;
    peopleCount = 0;
    stateActive = false;
    statusText = "再計測の準備ができました。計測開始を押してください。";
  }

  function downloadFinalHeatmap(): void {
    const targetSessionId = lastCompletedSessionId || sessionId || "session";
    finalHeatmapCanvas?.downloadPng(`heatmap_${targetSessionId}.png`);
  }

  onMount(() => {
    overlayCtx = overlayEl.getContext("2d");
    videoEl.setAttribute("webkit-playsinline", "true");
    camera = createCameraController(videoEl);
    historyItems = loadHistory();
    return () => {
      stopPolling();
    };
  });
</script>

<svelte:head>
  <link rel="preconnect" href="https://cdn.jsdelivr.net" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/geist-sans@5.2.5/latin.css" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource/geist-mono@5.0.3/latin-400.css" />
</svelte:head>

<div class="page">
  <section class="hero">
    <div>
      <p class="eyebrow">YOLOv8 Person Heatmap</p>
      <h1>部屋の占有をライブヒートマップで追跡</h1>
      <p class="heroText">
        固定スマホカメラの人物足元位置を床平面へ投影し、計測中は Canvas でライブ表示、計測終了後は PNG と履歴を残します。
      </p>
    </div>
    <div class="heroBadge">
      <div>更新間隔</div>
      <strong>{Math.max(1000, Number(heatmapRefreshMs) || 2000)}ms</strong>
    </div>
  </section>

  <section class="panel controlsPanel">
    <h2 class="panelTitle">計測設定</h2>
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
        <label for="heatmapRefreshInput">ヒートマップ更新（ms）</label>
        <input id="heatmapRefreshInput" type="number" min="1000" max="10000" step="500" bind:value={heatmapRefreshMs} />
      </div>
      <div class="field">
        <label for="roomWidthInput">部屋幅</label>
        <input id="roomWidthInput" type="number" min="1" step="0.5" bind:value={roomWidthUnits} />
      </div>
      <div class="field">
        <label for="roomHeightInput">部屋奥行</label>
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
      <div class="field">
        <label for="blurInput">ぼかし</label>
        <input id="blurInput" type="number" min="0" max="32" step="1" bind:value={blurRadius} />
      </div>
      <label class="toggle">
        <input type="checkbox" bind:checked={showHeatmapGrid} />
        <span>グリッド表示</span>
      </label>
    </div>
    <div class="actions">
      <button class="btn-primary" type="button" disabled={cameraActive} onclick={async () => {
        try {
          await handleStartCamera();
        } catch (error) {
          statusText = `カメラ起動失敗: ${error}`;
        }
      }}>カメラ起動</button>
      <button class="btn-secondary" type="button" disabled={!cameraActive || running} onclick={async () => {
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

  <section class="panel statusPanel">
    <div class="statusBar">
      <div class="statusMeta">
        <span class:live={stateActive} class="pill">{stateActive ? "LIVE" : "IDLE"}</span>
        <span>{statusText}</span>
      </div>
      <div class="statusStats">
        <div><strong>{remainingLabel}</strong><span>残り</span></div>
        <div><strong>{peopleCount}</strong><span>現在人数</span></div>
        <div><strong>{framesCount}</strong><span>フレーム</span></div>
      </div>
    </div>
  </section>

  <section class="liveGrid">
    <article class="panel cameraPanel">
      <div class="panelHeader">
        <h2 class="panelTitle">カメラプレビュー</h2>
        <span class="mono">{elapsedLabel}</span>
      </div>
      <div id="videoWrap">
        <video bind:this={videoEl} playsinline autoplay muted aria-label="カメラ映像"></video>
        <canvas bind:this={overlayEl} id="overlay" aria-hidden="true"></canvas>
      </div>
    </article>

    <article class="panel liveHeatmapPanel">
      <div class="panelHeader">
        <div>
          <h2 class="panelTitle">ライブヒートマップ</h2>
          <p class="subtle">上側が部屋の奥、下側がカメラ手前です。</p>
        </div>
      </div>
      <div class="heatmapLayout">
        <div class="heatmapSurface">
          {#if latestHeatmap}
            <HeatmapCanvas
              bind:this={liveHeatmapCanvas}
              grid={latestHeatmap.grid}
              maxValue={latestHeatmap.max_value}
              blurRadius={blurRadius}
              colorScheme="heat"
              showGrid={showHeatmapGrid}
              roomWidthUnits={latestHeatmap.room_width_units}
              roomHeightUnits={latestHeatmap.room_height_units}
              currentCount={latestHeatmap.current_count}
              elapsedSeconds={latestHeatmap.elapsed_seconds}
            />
          {:else}
            <div class="heatmapEmpty">計測開始後にライブヒートマップを表示します。</div>
          {/if}
        </div>
        <ColorBar colorScheme="heat" maxValue={latestHeatmap?.max_value || 0} />
      </div>
    </article>
  </section>

  {#if !running && latestHeatmap}
    <section class="panel resultPanel">
      <div class="panelHeader">
        <div>
          <h2 class="panelTitle">計測完了</h2>
          <p class="subtle">ライブ最終状態とサーバ保存 PNG を確認できます。</p>
        </div>
        <div class="actions compact">
          <button class="btn-secondary" type="button" onclick={downloadFinalHeatmap}>PNG保存</button>
          <button class="btn-primary" type="button" onclick={handleRestartMeasurement}>もう一度計測</button>
        </div>
      </div>
      <div class="resultGrid">
        <div class="resultCanvas">
          <HeatmapCanvas
            bind:this={finalHeatmapCanvas}
            grid={latestHeatmap.grid}
            maxValue={latestHeatmap.max_value}
            blurRadius={blurRadius}
            colorScheme="heat"
            showGrid={showHeatmapGrid}
            roomWidthUnits={latestHeatmap.room_width_units}
            roomHeightUnits={latestHeatmap.room_height_units}
            currentCount={latestHeatmap.current_count}
            elapsedSeconds={latestHeatmap.elapsed_seconds}
          />
        </div>
        <div class="resultMeta">
          <div class="summaryGrid">
            <div class="summaryCard">
              <span>計測時間</span>
              <strong>{formatSeconds(latestHeatmap.elapsed_seconds)}</strong>
            </div>
            <div class="summaryCard">
              <span>総検出回数</span>
              <strong>{framesCount}</strong>
            </div>
            <div class="summaryCard">
              <span>最大密度</span>
              <strong>{Math.round(latestHeatmap.max_value)}</strong>
            </div>
            <div class="summaryCard">
              <span>ピーク位置</span>
              <strong>{peakSummary ? `${peakSummary.peakXLabel} / ${peakSummary.peakYLabel}` : "--"}</strong>
            </div>
          </div>
          {#if heatmapSrc}
            <div class="savedPng">
              <img src={heatmapSrc} alt="保存済みヒートマップPNG" />
            </div>
          {/if}
        </div>
      </div>
    </section>
  {/if}

  <section class="panel historyPanel">
    <h2 class="panelTitle">ローカル履歴</h2>
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
    color: #171717;
    background: #ffffff;
    -webkit-font-smoothing: antialiased;
  }

  :global(*) {
    box-sizing: border-box;
  }

  .page {
    max-width: 1120px;
    margin: 0 auto;
    padding: 32px 16px 56px;
  }

  .hero {
    display: flex;
    justify-content: space-between;
    gap: 20px;
    align-items: flex-end;
    margin-bottom: 18px;
  }

  .eyebrow,
  .subtle,
  .historyText,
  .historyEmpty {
    margin: 0;
    color: #737373;
    font-size: 0.875rem;
  }

  h1 {
    margin: 6px 0 8px;
    font-size: clamp(2rem, 3vw, 3.3rem);
    line-height: 1.02;
    letter-spacing: -0.04em;
  }

  .heroText {
    max-width: 720px;
    margin: 0;
    color: #525252;
    font-size: 1rem;
  }

  .heroBadge {
    min-width: 120px;
    padding: 14px 16px;
    border-radius: 14px;
    background: #fafafa;
    border: 1px solid #e5e5e5;
  }

  .heroBadge div {
    color: #737373;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .heroBadge strong {
    display: block;
    margin-top: 6px;
    font-family: "Geist Mono", ui-monospace, monospace;
    font-size: 1.25rem;
  }

  .panel {
    margin-top: 16px;
    padding: 20px;
    border-radius: 16px;
    background: #ffffff;
    border: 1px solid #e5e5e5;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  }

  .panelHeader {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: flex-start;
    margin-bottom: 14px;
  }

  .panelTitle {
    margin: 0 0 4px;
    font-size: 0.8rem;
    font-weight: 700;
    color: #737373;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 16px;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 18px;
  }

  .actions.compact {
    margin-top: 0;
  }

  .field {
    display: grid;
    gap: 6px;
  }

  .field label,
  .toggle {
    font-size: 0.82rem;
    color: #737373;
  }

  .field input {
    width: 132px;
    height: 42px;
    padding: 0 12px;
    font-family: "Geist Mono", ui-monospace, monospace;
    font-size: 0.92rem;
    color: #171717;
    background: #ffffff;
    border: 1px solid #e5e5e5;
    border-radius: 10px;
  }

  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 10px;
  }

  button {
    height: 42px;
    padding: 0 16px;
    border: none;
    border-radius: 999px;
    font-family: "Geist Sans", sans-serif;
    font-size: 0.92rem;
    font-weight: 600;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .btn-primary {
    color: #ffffff;
    background: #171717;
  }

  .btn-secondary {
    color: #171717;
    background: #ffffff;
    border: 1px solid #e5e5e5;
  }

  .btn-success {
    color: #ffffff;
    background: #0070f3;
  }

  .btn-danger {
    color: #ffffff;
    background: #e5484d;
  }

  .statusBar {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: center;
  }

  .statusMeta {
    display: flex;
    gap: 12px;
    align-items: center;
    color: #171717;
  }

  .pill {
    display: inline-flex;
    align-items: center;
    min-width: 58px;
    justify-content: center;
    height: 28px;
    padding: 0 12px;
    border-radius: 999px;
    font-family: "Geist Mono", ui-monospace, monospace;
    font-size: 0.75rem;
    color: #525252;
    background: #f5f5f5;
  }

  .pill.live {
    color: #075985;
    background: #e0f2fe;
  }

  .statusStats {
    display: flex;
    gap: 22px;
  }

  .statusStats div {
    display: grid;
    gap: 2px;
    text-align: right;
  }

  .statusStats strong,
  .mono {
    font-family: "Geist Mono", ui-monospace, monospace;
  }

  .statusStats span {
    color: #737373;
    font-size: 0.8rem;
  }

  .liveGrid {
    display: grid;
    grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
    gap: 16px;
    align-items: start;
  }

  #videoWrap {
    position: relative;
    overflow: hidden;
    border-radius: 14px;
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

  .heatmapLayout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 44px;
    gap: 16px;
    align-items: center;
  }

  .heatmapSurface,
  .resultCanvas {
    min-width: 0;
  }

  .heatmapEmpty {
    display: grid;
    place-items: center;
    min-height: 320px;
    border-radius: 14px;
    color: #737373;
    background: #fafafa;
    border: 1px dashed #d4d4d8;
  }

  .resultGrid {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
    gap: 18px;
    align-items: start;
  }

  .resultMeta {
    display: grid;
    gap: 16px;
  }

  .summaryGrid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .summaryCard {
    display: grid;
    gap: 8px;
    padding: 16px;
    border-radius: 14px;
    background: #fafafa;
    border: 1px solid #e5e5e5;
  }

  .summaryCard span {
    color: #737373;
    font-size: 0.82rem;
  }

  .summaryCard strong {
    font-size: 1.25rem;
  }

  .savedPng img {
    border-radius: 14px;
    border: 1px solid #e5e5e5;
    background: #fafafa;
  }

  .historyList {
    display: grid;
    gap: 16px;
  }

  .historyItem {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 16px;
    padding: 14px;
    border-radius: 14px;
    background: #ffffff;
    border: 1px solid #e5e5e5;
  }

  .historyThumb {
    border-radius: 12px;
    background: #fafafa;
  }

  .historyMeta {
    display: grid;
    gap: 4px;
    min-width: 0;
  }

  .historyTitle {
    font-weight: 700;
    color: #171717;
  }

  @media (max-width: 960px) {
    .liveGrid,
    .resultGrid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 768px) {
    .hero,
    .statusBar,
    .panelHeader {
      display: grid;
    }

    .statusStats {
      justify-content: space-between;
    }

    .heatmapLayout {
      grid-template-columns: 1fr;
    }

    .summaryGrid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 640px) {
    .page {
      padding: 20px 12px 40px;
    }

    .controls {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .field input {
      width: 100%;
    }

    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
    }

    .historyItem {
      grid-template-columns: 1fr;
    }
  }
</style>
