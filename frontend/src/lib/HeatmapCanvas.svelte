<script lang="ts">
  import { onMount } from "svelte";

  import { getHeatmapColor, type HeatmapScheme } from "./heatmapColors";

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

    ctx.fillStyle = "#fbfdff";
    ctx.fillRect(planeX, planeY, planeWidth, planeHeight);

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

        ctx.save();
        ctx.filter = blurRadius > 0 ? `blur(${blurRadius}px)` : "none";
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(source, planeX, planeY, planeWidth, planeHeight);
        ctx.restore();

        ctx.globalCompositeOperation = "multiply";
        ctx.fillStyle = "rgba(255, 153, 0, 0.06)";
        ctx.fillRect(planeX, planeY, planeWidth, planeHeight);
        ctx.globalCompositeOperation = "source-over";
      }
    }

    if (showGrid && rows > 0 && cols > 0) {
      ctx.strokeStyle = "rgba(15, 23, 42, 0.08)";
      ctx.lineWidth = 1;
      for (let row = 1; row < rows; row += 1) {
        const y = planeY + (row / rows) * planeHeight;
        ctx.beginPath();
        ctx.moveTo(planeX, y);
        ctx.lineTo(planeX + planeWidth, y);
        ctx.stroke();
      }
      for (let col = 1; col < cols; col += 1) {
        const x = planeX + (col / cols) * planeWidth;
        ctx.beginPath();
        ctx.moveTo(x, planeY);
        ctx.lineTo(x, planeY + planeHeight);
        ctx.stroke();
      }
    }

    ctx.strokeStyle = "rgba(15, 23, 42, 0.16)";
    ctx.lineWidth = 2;
    ctx.strokeRect(planeX, planeY, planeWidth, planeHeight);

    if (showLabels) {
      ctx.fillStyle = "rgba(17, 24, 39, 0.92)";
      ctx.font = '600 16px "Geist Sans", sans-serif';
      ctx.fillText("Far side", planeX + planeWidth - 72, planeY - 8);
      ctx.fillText("Near camera", planeX + planeWidth - 102, planeY + planeHeight + 22);

      ctx.font = '500 13px "Geist Mono", monospace';
      ctx.fillStyle = "rgba(71, 85, 105, 0.9)";
      ctx.fillText(`room ${roomWidthUnits.toFixed(1)} x ${roomHeightUnits.toFixed(1)}`, planeX, height - 12);
      ctx.fillText(`live ${currentCount} people`, planeX, 18);
      ctx.fillText(`elapsed ${formatSeconds(elapsedSeconds)}`, planeX + 150, 18);
      ctx.fillText(`max ${Math.round(maxValue)}`, planeX + 310, 18);
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
