<script lang="ts">
  import { onMount } from "svelte";

  import { getHeatmapColor, type HeatmapScheme } from "./heatmapColors";
  import { computeRoomLayout, type RoomProjectionGuide } from "./roomLayout";

  let {
    grid = [],
    maxValue = 0,
    blurRadius = 16,
    colorScheme = "inferno",
    showGrid = false,
    showLabels = true,
    roomWidthUnits = 10,
    roomHeightUnits = 10,
    currentCount = 0,
    elapsedSeconds = 0,
    projection = {
      floor_top_y_ratio: 0.35,
      floor_top_width_ratio: 0.38,
      floor_bottom_width_ratio: 1.0,
    },
    showStats = true,
  }: {
    grid?: number[][];
    maxValue?: number;
    blurRadius?: number;
    colorScheme?: HeatmapScheme;
    showGrid?: boolean;
    showLabels?: boolean;
    roomWidthUnits?: number;
    roomHeightUnits?: number;
    currentCount?: number;
    elapsedSeconds?: number;
    projection?: RoomProjectionGuide;
    showStats?: boolean;
  } = $props();

  let canvasEl: HTMLCanvasElement;
  let frameEl: HTMLDivElement;
  let resizeObserver: ResizeObserver | null = null;

  function formatSeconds(totalSeconds: number): string {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function createSurface(width: number, height: number): OffscreenCanvas | HTMLCanvasElement {
    if (typeof OffscreenCanvas !== "undefined") {
      return new OffscreenCanvas(width, height);
    }

    const fallback = document.createElement("canvas");
    fallback.width = width;
    fallback.height = height;
    return fallback;
  }

  function draw(): void {
    if (!canvasEl || !frameEl) return;

    const rows = grid.length;
    const cols = rows > 0 ? grid[0].length : 0;
    const width = Math.max(320, Math.round(frameEl.clientWidth));
    const height = Math.max(240, Math.round(frameEl.clientHeight));
    const dpr = window.devicePixelRatio || 1;

    canvasEl.width = Math.round(width * dpr);
    canvasEl.height = Math.round(height * dpr);
    canvasEl.style.width = `${width}px`;
    canvasEl.style.height = `${height}px`;

    const ctx = canvasEl.getContext("2d");
    if (!ctx) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const background = ctx.createLinearGradient(0, 0, width, height);
    background.addColorStop(0, "#ffffff");
    background.addColorStop(1, "#f8fafc");
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);

    const planeX = 26;
    const planeY = 26;
    const planeWidth = width - 52;
    const planeHeight = height - 52;
    const layout = computeRoomLayout(planeX, planeY, planeWidth, planeHeight, projection);
    const roomLeft = layout.roomX;
    const roomTop = layout.roomY;
    const roomRight = layout.roomX + layout.roomWidth;
    const roomBottom = layout.roomY + layout.roomHeight;
    const doorwayHalf = layout.cameraDoorWidth / 2;

    const floorGradient = ctx.createLinearGradient(roomLeft, roomTop, roomRight, roomBottom);
    floorGradient.addColorStop(0, "#fffdf8");
    floorGradient.addColorStop(1, "#f3efe6");
    ctx.fillStyle = "#ece7dc";
    ctx.fillRect(roomLeft - layout.wallThickness, roomTop - layout.wallThickness, layout.roomWidth + layout.wallThickness * 2, layout.roomHeight + layout.wallThickness * 2);
    ctx.fillStyle = floorGradient;
    ctx.fillRect(roomLeft, roomTop, layout.roomWidth, layout.roomHeight);

    ctx.save();
    ctx.beginPath();
    ctx.rect(roomLeft, roomTop, layout.roomWidth, layout.roomHeight);
    ctx.clip();

    if (rows > 0 && cols > 0 && maxValue > 0) {
      const source = createSurface(cols, rows);
      const sourceCtx = source.getContext("2d");
      if (sourceCtx) {
        const image = sourceCtx.createImageData(cols, rows);
        for (let row = 0; row < rows; row += 1) {
          for (let col = 0; col < cols; col += 1) {
            const rawValue = grid[row]?.[col] ?? 0;
            const normalized = Math.max(0, Math.min(1, rawValue / maxValue));
            const weighted = Math.pow(normalized, 0.58);
            const [r, g, b] = getHeatmapColor(weighted, colorScheme);
            const alpha = rawValue > 0 ? Math.round(50 + weighted * 205) : 0;
            const offset = (row * cols + col) * 4;
            image.data[offset] = r;
            image.data[offset + 1] = g;
            image.data[offset + 2] = b;
            image.data[offset + 3] = alpha;
          }
        }
        sourceCtx.putImageData(image, 0, 0);

        ctx.filter = blurRadius > 0 ? `blur(${blurRadius}px)` : "none";
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(source, roomLeft, roomTop, layout.roomWidth, layout.roomHeight);

        ctx.globalCompositeOperation = "multiply";
        ctx.fillStyle = "rgba(255, 153, 0, 0.06)";
        ctx.fillRect(roomLeft, roomTop, layout.roomWidth, layout.roomHeight);
        ctx.globalCompositeOperation = "source-over";
      }
    }
    ctx.restore();

    if (showGrid && rows > 0 && cols > 0) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(roomLeft, roomTop, layout.roomWidth, layout.roomHeight);
      ctx.clip();
      ctx.strokeStyle = "rgba(15, 23, 42, 0.08)";
      ctx.lineWidth = 1;
      for (let row = 1; row < rows; row += 1) {
        const y = roomTop + (row / rows) * layout.roomHeight;
        ctx.beginPath();
        ctx.moveTo(roomLeft, y);
        ctx.lineTo(roomRight, y);
        ctx.stroke();
      }
      for (let col = 1; col < cols; col += 1) {
        const x = roomLeft + (col / cols) * layout.roomWidth;
        ctx.beginPath();
        ctx.moveTo(x, roomTop);
        ctx.lineTo(x, roomBottom);
        ctx.stroke();
      }
      ctx.restore();
    }

    ctx.fillStyle = "rgba(148, 163, 184, 0.15)";
    ctx.beginPath();
    ctx.moveTo(layout.visibleZone[0].x, layout.visibleZone[0].y);
    for (let index = 1; index < layout.visibleZone.length; index += 1) {
      ctx.lineTo(layout.visibleZone[index].x, layout.visibleZone[index].y);
    }
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = "rgba(30, 41, 59, 0.18)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(layout.visibleZone[0].x, layout.visibleZone[0].y);
    for (let index = 1; index < layout.visibleZone.length; index += 1) {
      ctx.lineTo(layout.visibleZone[index].x, layout.visibleZone[index].y);
    }
    ctx.closePath();
    ctx.stroke();

    ctx.strokeStyle = "#3f3f46";
    ctx.lineWidth = layout.wallThickness;
    ctx.lineCap = "square";
    ctx.beginPath();
    ctx.moveTo(roomLeft, roomTop);
    ctx.lineTo(roomRight, roomTop);
    ctx.moveTo(roomLeft, roomTop);
    ctx.lineTo(roomLeft, roomBottom);
    ctx.moveTo(roomRight, roomTop);
    ctx.lineTo(roomRight, roomBottom);
    ctx.moveTo(roomLeft, roomBottom);
    ctx.lineTo(layout.cameraX - doorwayHalf, roomBottom);
    ctx.moveTo(layout.cameraX + doorwayHalf, roomBottom);
    ctx.lineTo(roomRight, roomBottom);
    ctx.stroke();

    ctx.strokeStyle = "rgba(255, 255, 255, 0.5)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(layout.cameraX - doorwayHalf, roomBottom);
    ctx.quadraticCurveTo(layout.cameraX, roomBottom - doorwayHalf * 0.5, layout.cameraX + doorwayHalf, roomBottom);
    ctx.stroke();

    ctx.fillStyle = "#0f172a";
    ctx.beginPath();
    ctx.arc(layout.cameraX, layout.cameraY, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(15, 23, 42, 0.2)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(layout.cameraX, layout.cameraY - 5);
    ctx.lineTo(layout.visibleZone[2].x, layout.visibleZone[2].y);
    ctx.moveTo(layout.cameraX, layout.cameraY - 5);
    ctx.lineTo(layout.visibleZone[3].x, layout.visibleZone[3].y);
    ctx.stroke();

    if (showLabels) {
      ctx.fillStyle = "rgba(17, 24, 39, 0.92)";
      ctx.font = '600 16px "Geist Sans", sans-serif';
      ctx.fillText("Far side", roomRight - 72, roomTop - 10);
      ctx.fillText("Near camera", roomRight - 108, roomBottom + 28);

      ctx.font = '500 13px "Geist Mono", monospace';
      ctx.fillStyle = "rgba(71, 85, 105, 0.9)";
      ctx.fillText(`room ${roomWidthUnits.toFixed(1)} x ${roomHeightUnits.toFixed(1)}`, roomLeft, height - 12);
      ctx.fillText("camera", layout.cameraX - 24, layout.cameraY + 20);
      if (showStats) {
        ctx.fillText(`live ${currentCount} people`, planeX, 18);
        ctx.fillText(`elapsed ${formatSeconds(elapsedSeconds)}`, planeX + 150, 18);
        ctx.fillText(`max ${Math.round(maxValue)}`, planeX + 310, 18);
      } else {
        ctx.fillText(`visible top ${projection.floor_top_width_ratio.toFixed(2)}`, planeX, 18);
        ctx.fillText(`floor start ${projection.floor_top_y_ratio.toFixed(2)}`, planeX + 170, 18);
      }
    }
  }

  export function toDataUrl(): string {
    return canvasEl?.toDataURL("image/png") ?? "";
  }

  export function downloadPng(filename = "heatmap-live.png"): void {
    const dataUrl = toDataUrl();
    if (!dataUrl) return;
    const anchor = document.createElement("a");
    anchor.href = dataUrl;
    anchor.download = filename;
    anchor.click();
  }

  $effect(() => {
    grid;
    maxValue;
    blurRadius;
    colorScheme;
    showGrid;
    showLabels;
    roomWidthUnits;
    roomHeightUnits;
    currentCount;
    elapsedSeconds;
    projection;
    showStats;
    draw();
  });

  onMount(() => {
    resizeObserver = new ResizeObserver(() => draw());
    if (frameEl) {
      resizeObserver.observe(frameEl);
    }
    draw();
    return () => {
      resizeObserver?.disconnect();
    };
  });
</script>

<div class="frame" bind:this={frameEl}>
  <canvas bind:this={canvasEl} aria-label="ライブヒートマップ"></canvas>
</div>

<style>
  .frame {
    width: 100%;
    aspect-ratio: 16 / 10;
    min-height: 260px;
  }

  canvas {
    display: block;
    width: 100%;
    height: 100%;
    border-radius: 18px;
    border: 1px solid #e5e7eb;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
  }
</style>
