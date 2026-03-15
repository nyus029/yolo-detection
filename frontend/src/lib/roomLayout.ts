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
  visibleZone: Array<{ x: number; y: number }>;
  cameraDoorWidth: number;
  cameraX: number;
  cameraY: number;
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function computeRoomLayout(
  x: number,
  y: number,
  width: number,
  height: number,
  projection: RoomProjectionGuide,
): RoomLayout {
  const outerPadding = Math.max(14, Math.min(width, height) * 0.04);
  const roomX = x + outerPadding;
  const roomY = y + outerPadding;
  const roomWidth = Math.max(120, width - outerPadding * 2);
  const roomHeight = Math.max(120, height - outerPadding * 2);
  const wallThickness = clamp(Math.min(roomWidth, roomHeight) * 0.035, 8, 18);

  const visibleTopWidth = roomWidth * clamp(projection.floor_top_width_ratio, 0.08, 1);
  const visibleBottomWidth = roomWidth * clamp(projection.floor_bottom_width_ratio, 0.08, 1);
  const visibleTopInset = (roomWidth - visibleTopWidth) / 2;
  const visibleBottomInset = (roomWidth - visibleBottomWidth) / 2;
  const visibleTopY =
    roomY + roomHeight * clamp(0.08 + projection.floor_top_y_ratio * 0.42, 0.1, 0.5);
  const visibleBottomY = roomY + roomHeight - wallThickness * 1.4;

  const cameraDoorWidth = clamp(roomWidth * 0.2, 36, 96);
  const cameraX = roomX + roomWidth / 2;
  const cameraY = roomY + roomHeight + wallThickness * 1.8;

  return {
    roomX,
    roomY,
    roomWidth,
    roomHeight,
    wallThickness,
    visibleZone: [
      { x: roomX + visibleTopInset, y: visibleTopY },
      { x: roomX + roomWidth - visibleTopInset, y: visibleTopY },
      { x: roomX + roomWidth - visibleBottomInset, y: visibleBottomY },
      { x: roomX + visibleBottomInset, y: visibleBottomY },
    ],
    cameraDoorWidth,
    cameraX,
    cameraY,
  };
}
