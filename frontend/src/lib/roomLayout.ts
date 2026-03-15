export type RoomProjectionGuide = {
  floor_top_y_ratio: number;
  floor_top_width_ratio: number;
  floor_bottom_width_ratio: number;
};

export type RoomLayout = {
  roomX: number;
  roomY: number;
  roomWidth: number;
  roomHeight: number;
  wallThickness: number;
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function computeRoomLayout(
  x: number,
  y: number,
  width: number,
  height: number,
  roomWidthUnits: number,
  roomHeightUnits: number,
): RoomLayout {
  const outerPadding = Math.max(14, Math.min(width, height) * 0.04);
  const availableWidth = Math.max(120, width - outerPadding * 2);
  const availableHeight = Math.max(120, height - outerPadding * 2);
  const roomRatio = Math.max(1, roomWidthUnits) / Math.max(1, roomHeightUnits);

  let roomWidth: number;
  let roomHeight: number;
  if (availableWidth / Math.max(1, availableHeight) > roomRatio) {
    roomHeight = availableHeight;
    roomWidth = Math.max(120, roomHeight * roomRatio);
  } else {
    roomWidth = availableWidth;
    roomHeight = Math.max(120, roomWidth / Math.max(0.001, roomRatio));
  }

  const roomX = x + outerPadding + Math.max(0, (availableWidth - roomWidth) / 2);
  const roomY = y + outerPadding + Math.max(0, (availableHeight - roomHeight) / 2);
  const wallThickness = clamp(Math.min(roomWidth, roomHeight) * 0.035, 8, 18);

  return {
    roomX,
    roomY,
    roomWidth,
    roomHeight,
    wallThickness,
  };
}
