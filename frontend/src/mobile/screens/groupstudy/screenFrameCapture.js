// 수신 중인 화면공유(원격 WebRTC 트랙)의 현재 프레임 1장을 JPEG 로 캡처한다.
// 원격 MediaStream 을 srcObject 로 붙인 <video> 는 교차 출처 리소스가 아니라 canvas 가 오염(taint)되지 않는다(Chromium WebView 포함).
// 캡처한 프레임은 요청 본문으로만 쓰고 저장하지 않는다. 공유자가 FLAG_SECURE 등으로 막은 화면은 송출 단계에서 이미 검게 오며 우회하지 않는다.
import { base64Bytes, fitWithin, SCREEN_AI_MIME } from './screenAiModel.js';

const JPEG_QUALITIES = [0.85, 0.7, 0.55, 0.4];
const DOWNSCALE_STEP = 0.75;
const MAX_DOWNSCALE_ATTEMPTS = 4;
const FRAME_WAIT_MS = 3000;

function liveVideoElements(streamManager) {
  return (streamManager?.videos || [])
    .map((entry) => entry?.video)
    .filter((video) => video && video.videoWidth > 0 && video.videoHeight > 0);
}

function waitForFrame(video) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('화면공유 영상 프레임을 받지 못했습니다.')), FRAME_WAIT_MS);
    video.addEventListener(
      'loadeddata',
      () => {
        clearTimeout(timer);
        resolve(video);
      },
      { once: true }
    );
  });
}

// 표시 중인 타일이 없으면(다른 패널이 화면을 덮은 경우 등) 같은 MediaStream 으로 임시 <video> 를 만든다.
async function frameSource(streamManager) {
  const [visible] = liveVideoElements(streamManager);
  if (visible) return { video: visible, release: () => {} };

  const mediaStream = streamManager?.stream?.getMediaStream?.();
  if (!mediaStream) throw new Error('화면공유 영상을 받을 수 없습니다.');

  const video = document.createElement('video');
  video.muted = true;
  video.playsInline = true;
  video.srcObject = mediaStream;
  const ready = video.videoWidth > 0 ? Promise.resolve(video) : waitForFrame(video);
  await video.play().catch(() => {});
  await ready;
  return {
    video,
    release: () => {
      video.pause();
      video.srcObject = null;
    },
  };
}

function encode(source, sourceRect, size, quality) {
  const canvas = document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext('2d');
  context.drawImage(source, sourceRect.x, sourceRect.y, sourceRect.width, sourceRect.height, 0, 0, size.width, size.height);
  const dataUrl = canvas.toDataURL(SCREEN_AI_MIME, quality);
  canvas.width = 0;
  canvas.height = 0;
  return dataUrl;
}

// source: <video> 또는 <img>/<canvas>(영역 선택용 스냅샷). sourceRect 가 없으면 전체 프레임.
export function encodeFrame(source, { sourceRect, frameSize, maxLongSide, maxBytes }) {
  const rect = sourceRect || { x: 0, y: 0, width: frameSize.width, height: frameSize.height };
  let size = fitWithin(rect.width, rect.height, maxLongSide);

  for (let attempt = 0; attempt < MAX_DOWNSCALE_ATTEMPTS; attempt += 1) {
    for (const quality of JPEG_QUALITIES) {
      const dataUrl = encode(source, rect, size, quality);
      if (base64Bytes(dataUrl) <= maxBytes) return { dataUrl, width: size.width, height: size.height };
    }
    size = { width: Math.max(1, Math.round(size.width * DOWNSCALE_STEP)), height: Math.max(1, Math.round(size.height * DOWNSCALE_STEP)) };
  }
  throw new Error('화면 이미지를 전송 가능한 크기로 줄이지 못했습니다. 영역을 좁혀 다시 시도해 주세요.');
}

export async function captureScreenFrame(streamManager, limits, { sourceRect } = {}) {
  const { video, release } = await frameSource(streamManager);
  try {
    const frameSize = { width: video.videoWidth, height: video.videoHeight };
    const encoded = encodeFrame(video, { sourceRect, frameSize, maxLongSide: limits.maxLongSide, maxBytes: limits.maxImageBytes });
    const blank = encoded.dataUrl.length < 64;
    if (blank) throw new Error('화면 프레임을 캡처하지 못했습니다.');
    return { ...encoded, frameSize };
  } finally {
    release();
  }
}

// 영역 선택용: 지금 프레임을 원본 해상도 그대로(전송 한도 내) 고정한다. 같은 스냅샷에서 영역을 잘라 보내므로 좌표와 프레임이 어긋나지 않는다.
export async function snapshotScreenFrame(streamManager, limits) {
  const { video, release } = await frameSource(streamManager);
  try {
    const frameSize = { width: video.videoWidth, height: video.videoHeight };
    const canvas = document.createElement('canvas');
    canvas.width = frameSize.width;
    canvas.height = frameSize.height;
    canvas.getContext('2d').drawImage(video, 0, 0, frameSize.width, frameSize.height);
    const preview = encodeFrame(canvas, { frameSize, maxLongSide: limits.maxLongSide, maxBytes: limits.maxImageBytes });
    return { canvas, frameSize, previewUrl: preview.dataUrl };
  } finally {
    release();
  }
}

export function releaseSnapshot(snapshot) {
  if (snapshot?.canvas) {
    snapshot.canvas.width = 0;
    snapshot.canvas.height = 0;
  }
}
