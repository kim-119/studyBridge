// 화면공유 캡처 정책(브라우저 표준 API 만 사용, OpenVidu 내부 API 비의존).
//
// openvidu-browser 2.30 은 videoSource:'screen' 일 때 getDisplayMedia({ video: true, audio }) 를 직접 부르고 옵션을 받지 않는다.
// 트랙을 직접 만들어 넘기면 publish 시 typeOfVideo 가 CUSTOM 으로 재계산되므로(Stream.ts publishVideo), 그 대신 호출 순간에만
// getDisplayMedia 를 감싸 선택창 힌트를 더한다 → typeOfVideo=SCREEN·contentHint=detail·serverData kind=SCREEN 계약은 그대로.
// 힌트를 모르는 브라우저(Firefox·Safari)는 사전(dictionary)의 모르는 키를 무시한다.

// 두 모드 모두 해상도는 줄이지 않는다(lockScreenResolution). 모드는 인코더가 화면을 압축하는 방식(contentHint)만 바꾼다.
export const SCREEN_SHARE_MODES = Object.freeze({
  // 문서·코드: 화면 콘텐츠 압축 — PPT·PDF·IDE 글자 선명도
  document: { contentHint: 'detail', label: '문서·코드', desc: '글자를 선명하게 (PPT·PDF·IDE)' },
  // 영상·애니메이션: 움직이는 장면용 압축. 대역폭이 모자라면 프레임 수가 줄어든다(해상도 유지).
  motion: { contentHint: 'motion', label: '영상·애니메이션', desc: '움직이는 화면에 맞춘 압축' },
});

export const resolveShareMode = (mode) => (SCREEN_SHARE_MODES[mode] ? mode : 'document');

// 방별 동시 화면공유 상한. 최종 판정은 서버(POST /video/screen-token → 409 SCREEN_SHARE_LIMIT_REACHED, details.limit)가 하고,
// 클라이언트 값은 선택창을 열기 전 안내용이다(서버가 알려 준 limit 이 있으면 그 값을 쓴다).
export const SCREEN_SHARE_LIMIT = 2;
export const screenShareLimitMessage = (limit = SCREEN_SHARE_LIMIT) => `현재 화면공유 가능 인원(최대 ${limit}명)이 모두 사용 중입니다.`;

/**
 * 지금 방에서 다른 사람이 쓰는 화면공유 슬롯 수. screens = deriveRoomPresence().screens([connectionId, connection][]).
 * 내 화면공유(이 탭·내 다른 기기)는 세지 않는다 — 사용자당 1개는 서버가 따로 판정한다(SCREEN_ALREADY_ACTIVE).
 */
export function screenShareAvailability(screens, myUserId, limit = SCREEN_SHARE_LIMIT) {
  const cap = Number.isInteger(limit) && limit > 0 ? limit : SCREEN_SHARE_LIMIT;
  const used = (screens || []).filter(([, c]) => c && (c.userId === null || c.userId === undefined || String(c.userId) !== String(myUserId))).length;
  return { used, limit: cap, full: used >= cap };
}

/**
 * 화면공유 송출은 해상도를 줄이지 않는다(문서·영상 모드 공통) — RTCRtpSender.degradationPreference = 'maintain-resolution'.
 *  · openvidu-browser 2.30 은 createOffer(첫 publish, ICE 실패 뒤 스트림 재연결)마다 contentHint 가 detail/text 가 아니면 'balanced' 를 넣는다.
 *  · balanced 면 WebRTC 가 더 적은 픽셀을 요청하고, Chrome 탭 캡처는 그 요청을 캡처 단계에서 (원본 높이 − 90·k) 크기로 반영한다
 *    → 1895×848 탭이 284×128 까지 줄고, 프레임이 적은 화면 콘텐츠에서는 다시 올라오지 않는다(운영 "원본 크기 286×128").
 *  · maintain-resolution 이면 대역·CPU 가 모자랄 때 프레임 수·압축률만 조정한다. 실행 중에 바꿔도 2~3초 안에 원래 해상도로 돌아온다.
 * 이미 맞으면 setParameters 를 부르지 않는다. 반환 applied = 적용된 값(송신기 없음·미지원·실패 = null), changed = 이번에 바꿨는지.
 */
export const SCREEN_DEGRADATION_PREFERENCE = 'maintain-resolution';

export async function lockScreenResolution(sender) {
  if (!sender || typeof sender.getParameters !== 'function' || typeof sender.setParameters !== 'function') return { applied: null, changed: false };
  try {
    const params = sender.getParameters();
    if (params.degradationPreference === SCREEN_DEGRADATION_PREFERENCE) return { applied: SCREEN_DEGRADATION_PREFERENCE, changed: false };
    params.degradationPreference = SCREEN_DEGRADATION_PREFERENCE;
    await sender.setParameters(params);
    return { applied: sender.getParameters().degradationPreference || null, changed: true };
  } catch (e) {
    return { applied: null, changed: false };
  }
}

/** PeerConnection 의 영상 송신기(화면공유 PC 는 영상 송신기가 하나). 닫힌 PC·미지원이면 null. */
export function findVideoSender(pc) {
  try {
    return pc?.getSenders?.().find((s) => s.track?.kind === 'video') || null;
  } catch (e) {
    return null;
  }
}

/** 선택창 힌트. selfBrowserSurface:'exclude' = 지금 탭(StudyBridge 회의)을 목록에서 뺀다(Chrome·Edge). */
export function buildDisplayMediaHints({ withAudio } = {}) {
  return {
    selfBrowserSurface: 'exclude',
    surfaceSwitching: 'include',
    monitorTypeSurfaces: 'include',
    ...(withAudio ? { systemAudio: 'include' } : {}),
  };
}

/**
 * fn 실행 동안만 mediaDevices.getDisplayMedia 에 힌트를 더한다(호출자가 준 키가 우선). 끝나면 반드시 원래 함수로 되돌린다.
 * getDisplayMedia 가 없으면 아무것도 하지 않고 fn 만 실행한다.
 */
export async function withDisplayMediaHints(mediaDevices, hints, fn) {
  if (!mediaDevices || typeof mediaDevices.getDisplayMedia !== 'function') return fn();
  const hadOwn = Object.prototype.hasOwnProperty.call(mediaDevices, 'getDisplayMedia');
  const original = mediaDevices.getDisplayMedia;
  mediaDevices.getDisplayMedia = (constraints) => original.call(mediaDevices, { ...hints, ...(constraints || {}) });
  try {
    return await fn();
  } finally {
    if (hadOwn) mediaDevices.getDisplayMedia = original;
    else delete mediaDevices.getDisplayMedia;
  }
}

/**
 * 캡처 트랙 설정 → 사용자 안내 + 내 미리보기 정책.
 *  · monitor: 회의 창이 화면에 보이면 미리보기가 다시 캡처돼 반복 화면이 생긴다(브라우저 API 로 완전히 막을 수 없음)
 *    → 미리보기는 정지 화면(스냅샷)이 기본, 실시간은 사용자가 따로 켤 때만.
 *  · window: 고른 창이 이 브라우저 창이면 같은 일이 생길 수 있다(어느 창인지 웹에서 알 수 없음) → 안내만.
 *  · browser: selfBrowserSurface:'exclude' 로 이 탭은 고를 수 없다 → 실시간 미리보기.
 * '전체 모니터'(송출자가 고른 공유 범위)는 시청자의 '전체화면 보기'와 다른 기능이라 용어를 분리한다.
 */
export function describeCaptureSurface(settings) {
  const s = settings || {};
  const label = { browser: '브라우저 탭', window: '창', monitor: '전체 모니터', application: '앱' }[s.displaySurface] || '화면';
  const width = Number(s.width) || null;
  const height = Number(s.height) || null;
  return {
    surface: s.displaySurface || null,
    label,
    width,
    height,
    resolution: width && height ? `${width}×${height}` : null,
    frameRate: Number.isFinite(s.frameRate) ? Math.round(s.frameRate) : null,
    recursionRisk: s.displaySurface === 'monitor',
    recursionPossible: s.displaySurface === 'monitor' || s.displaySurface === 'window',
    previewPolicy: s.displaySurface === 'monitor' ? 'snapshot' : 'live',
  };
}
