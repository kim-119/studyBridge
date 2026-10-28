// 그룹스터디 화면공유 AI 분석(EC2 GroupScreenAiController → ai07 VLM) 클라이언트 모델. 화면과 분리된 순수 함수만 둔다.
//
//  GET    /api/groups/{g}/screen-ai/shares                      → { enabled, viewerConnected, shares[], limits }
//  PUT    /api/groups/{g}/screen-ai/shares/{connectionId}/consent  { allowed } (공유자 본인만)
//  POST   /api/groups/{g}/screen-ai/analyze { connectionId, streamId, question, image, mime, clientRequestId }
//  DELETE /api/groups/{g}/screen-ai/analyze/{clientRequestId}   (멱등 취소)
//
// 공유자 동의·그룹 권한·사용자별 진행 중 1건·분당 횟수 제한·스트림 일치·ai07 큐/타임아웃은 서버가 검증한다.
// 앱은 지금 보이는 프레임 1장만 캡처해 보내고, 분석이 끝나면 프레임을 보관하지 않는다.

export const SCREEN_AI_MIME = 'image/jpeg';

export const DEFAULT_SCREEN_AI_LIMITS = Object.freeze({
  maxQuestionChars: 1000,
  maxImageBytes: 1024 * 1024,
  maxLongSide: 1280,
  minSide: 32,
  timeoutSeconds: 260,
});

export const SCREEN_AI_PRESETS = Object.freeze([
  { key: 'summary', label: '화면 요약', question: '지금 보이는 화면을 요약해 줘.' },
  { key: 'code', label: '코드 설명', question: '현재 화면의 코드를 설명해 줘.' },
  { key: 'error', label: '오류 분석', question: '화면에 표시된 오류를 분석하고 해결 방법을 알려 줘.' },
  { key: 'highlights', label: '중요 내용 정리', question: '현재 화면에서 중요한 내용을 정리해 줘.' },
  { key: 'region', label: '선택 영역 설명', question: '선택한 화면 영역을 설명해 줘.', needsRegion: true },
]);

export function limitsFrom(response) {
  const limits = response?.limits || {};
  const pick = (key) => (Number.isFinite(limits[key]) && limits[key] > 0 ? limits[key] : DEFAULT_SCREEN_AI_LIMITS[key]);
  return {
    maxQuestionChars: pick('maxQuestionChars'),
    maxImageBytes: pick('maxImageBytes'),
    maxLongSide: pick('maxLongSide'),
    minSide: pick('minSide'),
    timeoutSeconds: pick('timeoutSeconds'),
  };
}

export function newClientRequestId(random = Math.random, now = Date.now()) {
  const suffix = Array.from({ length: 12 }, () => Math.floor(random() * 36).toString(36)).join('');
  return `and-${now.toString(36)}-${suffix}`;
}

// 서버 목록 × 지금 수신 중인 화면공유 영상. 영상이 없으면 캡처할 프레임이 없으므로 고를 수 없다.
export function analyzableShares(response, remoteParticipants) {
  const remotes = new Map(
    (remoteParticipants || [])
      .filter((participant) => participant?.isScreenShare || participant?.videoKind === 'SCREEN')
      .map((participant) => [participant.connectionId, participant])
  );

  return (Array.isArray(response?.shares) ? response.shares : [])
    .filter((share) => !share.isMine)
    .map((share) => {
      const remote = remotes.get(share.connectionId) || null;
      const isReceiving = Boolean(remote?.streamManager && remote.screenOn !== false);
      return {
        connectionId: share.connectionId,
        streamId: share.streamId,
        sharerName: share.sharerName || '참여자',
        deviceType: share.deviceType || null,
        hasConsent: share.analyzable === true,
        isReceiving,
        streamManager: remote?.streamManager || null,
      };
    });
}

export function describeShareAvailability(share) {
  if (!share) return '분석할 화면공유를 선택해 주세요.';
  if (!share.hasConsent) return `${share.sharerName}님이 AI 화면 분석을 허용하지 않았습니다.`;
  if (!share.isReceiving) return '화면공유 영상을 아직 받지 못했습니다. 잠시 후 다시 시도해 주세요.';
  return null;
}

export function validateQuestion(question, limits = DEFAULT_SCREEN_AI_LIMITS) {
  const text = String(question || '').trim();
  if (!text) return { ok: false, message: '질문을 입력해 주세요.' };
  if (text.length > limits.maxQuestionChars) {
    return { ok: false, message: `질문은 ${limits.maxQuestionChars}자 이하로 입력해 주세요.` };
  }
  return { ok: true, question: text };
}

export function fitWithin(width, height, maxLongSide) {
  const longSide = Math.max(width, height);
  if (!longSide || longSide <= maxLongSide) return { width: Math.round(width), height: Math.round(height) };
  const scale = maxLongSide / longSide;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

const clamp01 = (value) => Math.min(1, Math.max(0, value));

// 화면에 표시된 스냅샷 위 드래그 좌표 → 0..1 정규화 영역. 표시 크기와 원본 해상도가 달라도 같은 영역을 가리킨다.
export function normalizeRegion(start, end, displaySize) {
  const width = displaySize?.width || 0;
  const height = displaySize?.height || 0;
  if (!width || !height || !start || !end) return null;

  const x1 = clamp01(Math.min(start.x, end.x) / width);
  const y1 = clamp01(Math.min(start.y, end.y) / height);
  const x2 = clamp01(Math.max(start.x, end.x) / width);
  const y2 = clamp01(Math.max(start.y, end.y) / height);
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

// 정규화 영역 → 원본 프레임 픽셀 영역. 서버 최소 변(minSide)보다 작으면 null(너무 작은 영역).
export function regionToSourceRect(region, frameSize, minSide = DEFAULT_SCREEN_AI_LIMITS.minSide) {
  if (!region || !frameSize?.width || !frameSize?.height) return null;
  const rect = {
    x: Math.round(region.x * frameSize.width),
    y: Math.round(region.y * frameSize.height),
    width: Math.round(region.width * frameSize.width),
    height: Math.round(region.height * frameSize.height),
  };
  if (rect.width < minSide || rect.height < minSide) return null;
  return rect;
}

export function base64Bytes(dataUrl) {
  const base64 = String(dataUrl || '').replace(/^data:[^,]*,/, '');
  const padding = base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0;
  return Math.max(0, Math.floor((base64.length * 3) / 4) - padding);
}

export function buildAnalyzeRequest({ share, question, image, clientRequestId }) {
  return {
    connectionId: share.connectionId,
    streamId: share.streamId,
    question,
    image,
    mime: SCREEN_AI_MIME,
    clientRequestId,
  };
}

const ERROR_MESSAGES = {
  SCREEN_AI_DISABLED: 'AI 화면 분석 기능이 지금은 꺼져 있습니다.',
  SHARER_CONSENT_REQUIRED: '공유자가 AI 화면 분석을 허용하지 않았습니다.',
  VIEWER_NOT_CONNECTED: '스터디룸 영상 연결이 끊겨 분석할 수 없습니다. 연결이 복구되면 다시 시도해 주세요.',
  SCREEN_NOT_FOUND: '화면공유가 종료되어 분석을 중단했습니다.',
  SCREEN_STREAM_MISMATCH: '화면공유가 다시 시작되었습니다. 최신 화면으로 다시 시도해 주세요.',
  SCREEN_AI_IN_PROGRESS: '이미 진행 중인 화면 분석이 있습니다. 끝난 뒤 다시 시도해 주세요.',
  SCREEN_AI_RATE_LIMITED: '요청이 많아 잠시 제한되었습니다.',
  SCREEN_AI_QUESTION_INVALID: '질문을 확인해 주세요.',
  SCREEN_AI_IMAGE_TOO_LARGE: '화면 이미지가 너무 큽니다. 영역을 좁혀 다시 시도해 주세요.',
  NOT_GROUP_MEMBER: '그룹스터디 참여 멤버만 화면 분석을 사용할 수 있습니다.',
  VIDEO_STATE_UNAVAILABLE: '화면공유 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.',
};

export function describeScreenAiError(error) {
  if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') {
    return { message: '분석을 취소했습니다.', retryable: true, cancelled: true };
  }
  const status = error?.status || error?.response?.status;
  const body = error?.response?.data || {};
  const code = body.code;
  const retryAfter = Number(body.retryAfterSeconds) || Number(error?.response?.headers?.['retry-after']) || null;

  let message = ERROR_MESSAGES[code];
  if (!message) {
    if (error?.code === 'ECONNABORTED') message = 'AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.';
    else if (!error?.response) message = '서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.';
    else if (status === 401) message = '로그인이 만료되었습니다. 다시 로그인해 주세요.';
    else if (status === 403) message = '이 화면을 분석할 권한이 없습니다.';
    else if (status === 429) message = ERROR_MESSAGES.SCREEN_AI_RATE_LIMITED;
    else if (status >= 500) message = 'AI 화면 분석 서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.';
    else message = body.message || '화면 분석에 실패했습니다.';
  }
  if (retryAfter) message = `${message} (${retryAfter}초 후 다시 시도)`;

  const retryable = typeof body.retryable === 'boolean' ? body.retryable : status === 429 || status >= 500 || !error?.response;
  return { message, retryable, code: code || null, shareEnded: code === 'SCREEN_NOT_FOUND' };
}

// 내 화면공유(Android 네이티브·다른 기기 포함). 공유자 본인만 AI 분석 허용 여부를 바꿀 수 있다(PUT consent).
export function myShares(response) {
  return (Array.isArray(response?.shares) ? response.shares : [])
    .filter((share) => share.isMine)
    .map((share) => ({ connectionId: share.connectionId, hasConsent: share.aiConsent === true, deviceType: share.deviceType || null }));
}
