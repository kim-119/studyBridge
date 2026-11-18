import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_SCREEN_AI_LIMITS,
  SCREEN_AI_PRESETS,
  analyzableShares,
  base64Bytes,
  buildAnalyzeRequest,
  describeScreenAiError,
  describeShareAvailability,
  fitWithin,
  limitsFrom,
  newClientRequestId,
  normalizeRegion,
  regionToSourceRect,
  validateQuestion,
} from '../screens/groupstudy/screenAiModel.js';

const httpError = (status, data = {}, headers = {}) => ({ response: { status, data, headers } });

const SERVER = {
  enabled: true,
  viewerConnected: true,
  shares: [
    { connectionId: 'con_pc', streamId: 'str_pc', sharerName: '고병준', isMine: false, analyzable: true, deviceType: 'WEB' },
    { connectionId: 'con_off', streamId: 'str_off', sharerName: '이서연', isMine: false, analyzable: false },
    { connectionId: 'con_mine', streamId: 'str_mine', sharerName: '나', isMine: true, analyzable: true },
  ],
  limits: { maxQuestionChars: 500, maxImageBytes: 900000, maxLongSide: 1024, minSide: 32, timeoutSeconds: 200 },
};

test('다섯 가지 화면 분석 명령을 제공하고 선택 영역 설명만 영역 선택이 필요하다', () => {
  assert.deepEqual(
    SCREEN_AI_PRESETS.map((preset) => preset.label),
    ['화면 요약', '코드 설명', '오류 분석', '중요 내용 정리', '선택 영역 설명']
  );
  assert.deepEqual(
    SCREEN_AI_PRESETS.filter((preset) => preset.needsRegion).map((preset) => preset.key),
    ['region']
  );
});

test('서버 한도를 따르고 없으면 기본값을 쓴다', () => {
  assert.equal(limitsFrom(SERVER).maxLongSide, 1024);
  assert.equal(limitsFrom(SERVER).timeoutSeconds, 200);
  assert.deepEqual(limitsFrom(null), { ...DEFAULT_SCREEN_AI_LIMITS });
});

test('분석 대상은 남의 화면공유 중 지금 영상을 받는 것만, 동의 여부를 함께 표시한다', () => {
  const remotes = [
    { connectionId: 'con_pc', videoKind: 'SCREEN', streamManager: {}, screenOn: true },
    { connectionId: 'con_cam', videoKind: 'CAMERA', streamManager: {} },
  ];
  const shares = analyzableShares(SERVER, remotes);

  assert.deepEqual(
    shares.map((share) => [share.connectionId, share.hasConsent, share.isReceiving]),
    [
      ['con_pc', true, true],
      ['con_off', false, false],
    ],
    '내 화면(isMine)은 빠진다'
  );
  assert.equal(describeShareAvailability(shares[0]), null);
  assert.match(describeShareAvailability(shares[1]), /허용하지 않았습니다/);
  assert.match(describeShareAvailability({ ...shares[0], isReceiving: false }), /영상을 아직 받지 못했습니다/);
});

test('질문은 비우거나 한도를 넘을 수 없다', () => {
  assert.equal(validateQuestion('  ').ok, false);
  assert.equal(validateQuestion('x'.repeat(501), limitsFrom(SERVER)).ok, false);
  assert.deepEqual(validateQuestion('  요약해 줘 '), { ok: true, question: '요약해 줘' });
});

test('요청 본문은 서버 계약 필드만 담고 사용자 식별자를 보내지 않는다', () => {
  const body = buildAnalyzeRequest({
    share: { connectionId: 'con_pc', streamId: 'str_pc', sharerName: '고병준' },
    question: '요약',
    image: 'data:image/jpeg;base64,AAAA',
    clientRequestId: 'and-abc-123456789012',
  });
  assert.deepEqual(Object.keys(body).sort(), ['clientRequestId', 'connectionId', 'image', 'mime', 'question', 'streamId']);
  assert.equal(body.mime, 'image/jpeg');
});

test('clientRequestId 는 서버 형식([A-Za-z0-9_-]{8,64})을 따른다', () => {
  const id = newClientRequestId();
  assert.match(id, /^[A-Za-z0-9_-]{8,64}$/);
  assert.notEqual(newClientRequestId(), newClientRequestId());
});

test('프레임은 긴 변 한도 안으로 비율을 유지해 줄인다', () => {
  assert.deepEqual(fitWithin(1920, 1080, 1280), { width: 1280, height: 720 });
  assert.deepEqual(fitWithin(1080, 2400, 1280), { width: 576, height: 1280 });
  assert.deepEqual(fitWithin(800, 600, 1280), { width: 800, height: 600 });
});

test('선택 영역은 표시 크기 기준 정규화 후 원본 해상도로 변환한다(회전·해상도 차이 무관)', () => {
  const region = normalizeRegion({ x: 300, y: 50 }, { x: 100, y: 150 }, { width: 400, height: 200 });
  assert.deepEqual(region, { x: 0.25, y: 0.25, width: 0.5, height: 0.5 });

  assert.deepEqual(regionToSourceRect(region, { width: 1920, height: 1080 }), { x: 480, y: 270, width: 960, height: 540 });
  assert.deepEqual(regionToSourceRect(region, { width: 1080, height: 2400 }), { x: 270, y: 600, width: 540, height: 1200 });

  const outside = normalizeRegion({ x: -50, y: -10 }, { x: 900, y: 900 }, { width: 400, height: 200 });
  assert.deepEqual(outside, { x: 0, y: 0, width: 1, height: 1 }, '영역 밖 드래그는 잘라낸다');

  const tiny = normalizeRegion({ x: 10, y: 10 }, { x: 12, y: 12 }, { width: 400, height: 200 });
  assert.equal(regionToSourceRect(tiny, { width: 1280, height: 720 }), null, '최소 변보다 작으면 거부');
});

test('Base64 크기 계산', () => {
  assert.equal(base64Bytes('data:image/jpeg;base64,AAAA'), 3);
  assert.equal(base64Bytes('AAA='), 2);
  assert.equal(base64Bytes(''), 0);
});

test('오류 코드별 안내: 동의 없음·공유 종료·진행 중·요청 제한·타임아웃·서버 오류', () => {
  assert.match(describeScreenAiError(httpError(403, { code: 'SHARER_CONSENT_REQUIRED' })).message, /허용하지 않았습니다/);

  const ended = describeScreenAiError(httpError(404, { code: 'SCREEN_NOT_FOUND', retryable: false }));
  assert.equal(ended.shareEnded, true);
  assert.equal(ended.retryable, false);

  assert.match(describeScreenAiError(httpError(429, { code: 'SCREEN_AI_IN_PROGRESS' })).message, /진행 중인/);
  const limited = describeScreenAiError(httpError(429, { code: 'SCREEN_AI_RATE_LIMITED', retryAfterSeconds: 20 }));
  assert.match(limited.message, /20초 후/);
  assert.equal(limited.retryable, true);

  assert.match(describeScreenAiError({ code: 'ECONNABORTED', message: 'timeout' }).message, /시간이 초과/);
  assert.match(describeScreenAiError(httpError(503, {})).message, /일시적인 문제/);
  assert.equal(describeScreenAiError({ name: 'CanceledError', code: 'ERR_CANCELED' }).cancelled, true);
});
