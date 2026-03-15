<script lang="ts">
  import { buildGradientCss, type HeatmapScheme } from "./heatmapColors";

  let {
    maxValue = 0,
    minLabel = "0",
    maxLabel,
    colorScheme = "inferno",
  }: {
    maxValue?: number;
    minLabel?: string;
    maxLabel?: string;
    colorScheme?: HeatmapScheme;
  } = $props();

  const fallbackMaxLabel = $derived(maxLabel ?? `${Math.round(maxValue)}`);
  const gradientStyle = $derived(`background: ${buildGradientCss(colorScheme)};`);
</script>

<div class="colorbar">
  <div class="bar" style={gradientStyle} aria-hidden="true"></div>
  <div class="labels">
    <span>{fallbackMaxLabel}</span>
    <span>{minLabel}</span>
  </div>
</div>

<style>
  .colorbar {
    display: grid;
    gap: 10px;
    justify-items: center;
    min-width: 40px;
  }

  .bar {
    width: 14px;
    min-height: 180px;
    border-radius: 999px;
    border: 1px solid #d4d4d8;
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.75);
  }

  .labels {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 180px;
    font-family: "Geist Mono", ui-monospace, monospace;
    font-size: 0.75rem;
    color: #52525b;
  }
</style>
