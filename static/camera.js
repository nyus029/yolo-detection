export function createCameraController(video) {
  const captureCanvas = document.createElement("canvas");
  const captureCtx = captureCanvas.getContext("2d");
  let stream = null;

  async function ensureCamera() {
    if (stream) return stream;

    const isLocalhost = location.hostname === "localhost" || location.hostname === "127.0.0.1";
    if (!window.isSecureContext && !isLocalhost) {
      throw new Error("HTTPSでアクセスしてください（localhost以外のHTTPではカメラ不可）");
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("このブラウザ/接続では getUserMedia が利用できません");
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: false,
      });
    } catch {
      stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
    }

    video.srcObject = stream;
    await video.play();
    return stream;
  }

  async function captureFrameBlob(quality = 0.7) {
    if (video.videoWidth === 0 || video.videoHeight === 0) {
      throw new Error("カメラ映像がまだ準備中です");
    }

    captureCanvas.width = video.videoWidth;
    captureCanvas.height = video.videoHeight;
    captureCtx.drawImage(video, 0, 0);

    const blob = await new Promise((resolve) => captureCanvas.toBlob(resolve, "image/jpeg", quality));
    if (!blob) {
      throw new Error("フレーム取得に失敗しました");
    }

    return blob;
  }

  return {
    ensureCamera,
    captureFrameBlob,
    hasStream() {
      return !!stream;
    },
    getStream() {
      return stream;
    },
    getVideoSize() {
      return { width: video.videoWidth, height: video.videoHeight };
    },
  };
}
