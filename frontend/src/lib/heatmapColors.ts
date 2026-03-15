export type HeatmapScheme = "heat" | "inferno" | "cool";

type ColorStop = {
  at: number;
  rgb: [number, number, number];
};

const SCHEMES: Record<HeatmapScheme, ColorStop[]> = {
  heat: [
    { at: 0.0, rgb: [255, 255, 255] },
    { at: 0.1, rgb: [219, 234, 254] },
    { at: 0.28, rgb: [125, 211, 252] },
    { at: 0.5, rgb: [74, 222, 128] },
    { at: 0.72, rgb: [250, 204, 21] },
    { at: 0.88, rgb: [249, 115, 22] },
    { at: 1.0, rgb: [220, 38, 38] },
  ],
  inferno: [
    { at: 0.0, rgb: [8, 6, 22] },
    { at: 0.18, rgb: [52, 15, 99] },
    { at: 0.4, rgb: [145, 31, 97] },
    { at: 0.64, rgb: [221, 81, 57] },
    { at: 0.82, rgb: [250, 170, 55] },
    { at: 1.0, rgb: [252, 255, 164] },
  ],
  cool: [
    { at: 0.0, rgb: [248, 250, 252] },
    { at: 0.24, rgb: [191, 219, 254] },
    { at: 0.5, rgb: [96, 165, 250] },
    { at: 0.76, rgb: [59, 130, 246] },
    { at: 1.0, rgb: [109, 40, 217] },
  ],
};

function lerp(start: number, end: number, amount: number): number {
  return start + (end - start) * amount;
}

export function getHeatmapColor(value: number, scheme: HeatmapScheme): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, value));
  const stops = SCHEMES[scheme] ?? SCHEMES.inferno;

  for (let index = 1; index < stops.length; index += 1) {
    const prev = stops[index - 1];
    const next = stops[index];
    if (clamped <= next.at) {
      const span = Math.max(0.0001, next.at - prev.at);
      const amount = (clamped - prev.at) / span;
      return [
        Math.round(lerp(prev.rgb[0], next.rgb[0], amount)),
        Math.round(lerp(prev.rgb[1], next.rgb[1], amount)),
        Math.round(lerp(prev.rgb[2], next.rgb[2], amount)),
      ];
    }
  }

  return stops[stops.length - 1].rgb;
}

export function buildGradientCss(scheme: HeatmapScheme): string {
  const stops = SCHEMES[scheme] ?? SCHEMES.inferno;
  return `linear-gradient(to top, ${stops.map((stop) => `rgb(${stop.rgb.join(" ")}) ${Math.round(stop.at * 100)}%`).join(", ")})`;
}
