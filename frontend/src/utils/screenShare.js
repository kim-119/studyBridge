// 화면공유 캡처 정책(브라우저 표준 API 만 사용, OpenVidu 내부 API 비의존).
//
// openvidu-browser 2.30 은 videoSource:'screen' 일 때 getDisplayMedia({ video: true, audio }) 를 직접 부르고 옵션을 받지 않는다.
// 트랙을 직접 만들어 넘기면 publish 시 typeOfVideo 가 CUSTOM 으로 재계산되므로(Stream.ts publishVideo), 그 대신 호출 순간에만
// getDisplayMedia 를 감싸 선택창 힌트를 더한다 → typeOfVideo=SCREEN·contentHint=detail·serverData kind=SCREEN 계약은 그대로.
// 힌트를 모르는 브라우저(Firefox·Safari)는 사전(dictionary)의 모르는 키를 무시한다.

export const SCREEN_SHARE_MODES = Object.freeze({
  // 문서·코드: 해상도 유지 우선(대역폭이 모자라면 프레임을 먼저 줄인다) — PPT·PDF·IDE 글자 선명도
  document: { contentHint: 'detail', label: '문서·코드', desc: '글자를 선명하게 (PPT·PDF·IDE)' },
  // 영상·애니메이션: 프레임 유지 우선(대역폭이 모자라면 해상도를 먼저 줄인다)
  motion: { contentHint: 'motion', label: '영상·애니메이션', desc: '움직임을 부드럽게' },
});

export const resolveShareMode = (mode) => (SCREEN_SHARE_MODES[mode] ? mode : 'document');

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
