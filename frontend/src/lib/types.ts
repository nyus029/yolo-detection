export type Detection = {
  bbox: [number, number, number, number];
  score: number;
  class_id: number;
  class_name: string;
};

export type Projection = {
  room_width_units: number;
  room_height_units: number;
  floor_top_y_ratio: number;
  floor_top_width_ratio: number;
  floor_bottom_width_ratio: number;
};

export type SessionStatus = {
  session_id: string;
  started_at: string;
  expires_at: string;
  ended_at: string | null;
  is_active: boolean;
  duration_minutes: number;
  processed_frames: number;
  person_detections: number;
  last_person_count: number;
  projected_points: number;
  ignored_points: number;
  frame_width: number | null;
  frame_height: number | null;
  remaining_seconds: number;
  saved_heatmap_path: string | null;
  saved_metadata_path: string | null;
  projection: Projection;
};

export type DetectResponse = {
  detections: Detection[];
  counts: {
    person: number;
  };
  session?: SessionStatus | null;
  message?: string;
};

export type EstimateStructureResponse = {
  projection: Pick<Projection, "floor_top_y_ratio" | "floor_top_width_ratio" | "floor_bottom_width_ratio">;
  confidence: number;
  frame_width: number;
  frame_height: number;
  message: string;
};

export type StartSessionInput = {
  durationMinutes: number;
  roomWidthUnits: number;
  roomHeightUnits: number;
  floorTopYRatio: number;
  floorTopWidthRatio: number;
  floorBottomWidthRatio: number;
};

export type HistoryItem = {
  sessionId: string;
  savedAt: string;
  savedAtLabel: string;
  durationMinutes: number;
  processedFrames: number;
  personDetections: number;
  projectedPoints: number;
  roomWidth: number | string;
  roomHeight: number | string;
  floorTopY: number | string;
  savedHeatmapPath: string;
  savedMetadataPath: string;
  imageDataUrl: string;
};
