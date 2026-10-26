import test from 'node:test';
import assert from 'node:assert/strict';
import {
  findAllByText,
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  renderElement,
} from './support/componentHarness.mjs';

const PACKAGE_NAME = 'kr.co.studybridge.app';
const STABLE_DOWNLOAD_URL = 'https://studybridge.co.kr/downloads/android/StudyBridge-latest.apk';

const { checkForAppUpdate, createUpdateSession } = await importMobileModule('update/appUpdateCheck.js');
const { RELEASE_STATUS, fetchLatestRelease } = await importMobileModule('update/latestRelease.js');
const { UPDATE_KIND, formatFileSize, parseVersionCode } = await importMobileModule('update/releaseManifest.js');
const { openUpdateDownload } = await importMobileModule('update/updateDownload.js');
const { default: AppUpdateGate } = await importMobileModule('update/AppUpdateGate.jsx');
const { dismissTopLayer, pendingDismissCount } = await importMobileModule('platform/backDismissStack.js');

function installedApp(versionCode, versionName = `1.0.${versionCode - 1}`) {
  return { packageName: PACKAGE_NAME, versionCode, versionName };
}

function releaseBody(overrides = {}) {
  return {
    platform: 'android',
    packageName: PACKAGE_NAME,
    versionCode: 2,
    versionName: '1.0.1',
    downloadUrl: STABLE_DOWNLOAD_URL,
    versionedDownloadUrl: 'https://studybridge.co.kr/downloads/android/StudyBridge-1.0.1.apk',
    releaseDate: '2026-10-06T21:00:00+09:00',
    releaseNotes: ['모바일 안정성 개선', '회원가입 오류 수정'],
    forceUpdate: false,
    minimumSupportedVersionCode: 1,
    sha256: 'abc',
    fileSize: 19196753,
    ...overrides,
  };
}

function available(body) {
  return async () => ({ status: RELEASE_STATUS.AVAILABLE, body });
}

function check(installed, fetchRelease) {
  return checkForAppUpdate({ readApp: async () => installed, fetchRelease });
}

async function quietly(run) {
  const original = { warn: console.warn, error: console.error };
  const messages = [];
  console.warn = (...args) => messages.push(['warn', ...args]);
  console.error = (...args) => messages.push(['error', ...args]);
  try {
    return { result: await run(), messages };
  } finally {
    console.warn = original.warn;
    console.error = original.error;
  }
}

function jsonResponse(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  };
}

test('A. 404 NO_RELEASE 는 업데이트 없음으로 처리한다', async () => {
  const fetchImpl = async () => jsonResponse(404, { status: 404, code: 'NO_RELEASE', message: '배포된 Android 릴리즈가 아직 없습니다.' });
  const release = await fetchLatestRelease({ fetchImpl });
  assert.equal(release.status, RELEASE_STATUS.NO_RELEASE);

  const { result, messages } = await quietly(() => check(installedApp(1), () => fetchLatestRelease({ fetchImpl })));
  assert.equal(result.kind, UPDATE_KIND.NONE);
  assert.equal(messages.length, 0);
});

test('A-2. NO_RELEASE 가 아닌 404 는 장애로 보고 조용히 건너뛴다', async () => {
  const fetchImpl = async () => jsonResponse(404, { code: 'OTHER' });
  const { result, messages } = await quietly(() => check(installedApp(1), () => fetchLatestRelease({ fetchImpl })));
  assert.equal(result.kind, UPDATE_KIND.NONE);
  assert.equal(messages.length, 1);
});

test('B. 같은 versionCode 면 업데이트하지 않는다', async () => {
  const result = await check(installedApp(2), available(releaseBody({ versionCode: 2 })));
  assert.equal(result.kind, UPDATE_KIND.NONE);
});

test('B-2. 서버가 더 낮은 versionCode 면 업데이트하지 않는다', async () => {
  const result = await check(installedApp(3), available(releaseBody({ versionCode: 2, forceUpdate: true })));
  assert.equal(result.kind, UPDATE_KIND.NONE);
});

test('C. 새 버전 + forceUpdate=false 는 선택 업데이트다', async () => {
  const result = await check(installedApp(1, '1.0.0'), available(releaseBody()));
  assert.equal(result.kind, UPDATE_KIND.OPTIONAL);
  assert.equal(result.currentVersionName, '1.0.0');
  assert.equal(result.latestVersionName, '1.0.1');
  assert.equal(result.downloadUrl, STABLE_DOWNLOAD_URL);
  assert.deepEqual(result.releaseNotes, ['모바일 안정성 개선', '회원가입 오류 수정']);
});

test('C-2. versionName 문자열이 아니라 versionCode 정수로만 비교한다', async () => {
  const result = await check(installedApp(9, '1.9'), available(releaseBody({ versionCode: 10, versionName: '1.10' })));
  assert.equal(result.kind, UPDATE_KIND.OPTIONAL);

  const older = await check(installedApp(10, '1.10'), available(releaseBody({ versionCode: 9, versionName: '1.9' })));
  assert.equal(older.kind, UPDATE_KIND.NONE);
});

test('D. forceUpdate=true 는 강제 업데이트다', async () => {
  const result = await check(installedApp(1), available(releaseBody({ forceUpdate: true })));
  assert.equal(result.kind, UPDATE_KIND.FORCED);
});

test('D-2. forceUpdate 가 문자열 "true" 여도 true 로 해석하지 않는다', async () => {
  const result = await check(installedApp(1), available(releaseBody({ forceUpdate: 'true' })));
  assert.equal(result.kind, UPDATE_KIND.OPTIONAL);
});

test('E. minimumSupportedVersionCode 보다 낮으면 forceUpdate 와 무관하게 강제 업데이트다', async () => {
  const result = await check(installedApp(1), available(releaseBody({ forceUpdate: false, minimumSupportedVersionCode: 2 })));
  assert.equal(result.kind, UPDATE_KIND.FORCED);

  const supported = await check(installedApp(3), available(releaseBody({ versionCode: 6, minimumSupportedVersionCode: 3 })));
  assert.equal(supported.kind, UPDATE_KIND.OPTIONAL);
});

test('F. packageName 이 다르면 업데이트를 거부하고 오류를 기록한다', async () => {
  const { result, messages } = await quietly(() => check(installedApp(1), available(releaseBody({ packageName: 'com.example.other' }))));
  assert.equal(result.kind, UPDATE_KIND.NONE);
  assert.equal(messages[0][0], 'error');
});

test('G. platform 이 android 가 아니면 응답을 무시한다', async () => {
  const { result } = await quietly(() => check(installedApp(1), available(releaseBody({ platform: 'ios' }))));
  assert.equal(result.kind, UPDATE_KIND.NONE);
});

test('H. http 다운로드 주소는 업데이트로 제공하지 않고 열지도 않는다', async () => {
  const { result } = await quietly(() =>
    check(installedApp(1), available(releaseBody({ downloadUrl: 'http://studybridge.co.kr/downloads/android/StudyBridge-latest.apk' })))
  );
  assert.equal(result.kind, UPDATE_KIND.NONE);

  const openedUrls = [];
  const openUrl = async (url) => openedUrls.push(url);
  const { result: isOpened } = await quietly(() => openUpdateDownload('http://studybridge.co.kr/a.apk', openUrl));
  assert.equal(isOpened, false);
  assert.equal(await quietly(() => openUpdateDownload('javascript:alert(1)', openUrl)).then((r) => r.result), false);
  assert.equal(await quietly(() => openUpdateDownload('not a url', openUrl)).then((r) => r.result), false);
  assert.deepEqual(openedUrls, []);

  assert.equal(await openUpdateDownload(STABLE_DOWNLOAD_URL, openUrl), true);
  assert.deepEqual(openedUrls, [STABLE_DOWNLOAD_URL]);
});

test('I. 형식이 잘못된 응답은 조용히 업데이트 없음으로 처리한다', async () => {
  const malformedBodies = [
    null,
    'not-json',
    [],
    releaseBody({ versionCode: '2' }),
    releaseBody({ versionCode: 2.5 }),
    releaseBody({ versionCode: -1 }),
    releaseBody({ versionName: '' }),
    releaseBody({ downloadUrl: undefined }),
    releaseBody({ packageName: undefined }),
  ];

  for (const body of malformedBodies) {
    const { result } = await quietly(() => check(installedApp(1), available(body)));
    assert.equal(result.kind, UPDATE_KIND.NONE, JSON.stringify(body));
  }

  const brokenJson = async () => ({ status: 200, ok: true, json: async () => { throw new SyntaxError('Unexpected token'); } });
  const { result } = await quietly(() => check(installedApp(1), () => fetchLatestRelease({ fetchImpl: brokenJson })));
  assert.equal(result.kind, UPDATE_KIND.NONE);
});

test('I-2. releaseNotes 가 배열이 아니거나 비어도 업데이트 안내는 동작한다', async () => {
  for (const releaseNotes of [undefined, null, 'text', [], [' ', 3, null]]) {
    const result = await check(installedApp(1), available(releaseBody({ releaseNotes })));
    assert.equal(result.kind, UPDATE_KIND.OPTIONAL);
    assert.deepEqual(result.releaseNotes, []);
  }
});

test('J. 네트워크 실패·타임아웃·5xx 는 앱을 막지 않는다', async () => {
  const failures = [
    async () => { throw new TypeError('Failed to fetch'); },
    async () => jsonResponse(500, { message: 'error' }),
    async () => jsonResponse(502, null),
    async () => jsonResponse(503, null),
  ];

  for (const fetchImpl of failures) {
    const { result } = await quietly(() => check(installedApp(1), () => fetchLatestRelease({ fetchImpl })));
    assert.equal(result.kind, UPDATE_KIND.NONE);
  }

  const hangingFetch = (_url, { signal }) =>
    new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  const { result } = await quietly(() => check(installedApp(1), () => fetchLatestRelease({ fetchImpl: hangingFetch, timeoutMs: 20 })));
  assert.equal(result.kind, UPDATE_KIND.NONE);
});

test('J-2. 설치 앱 정보를 읽지 못해도 앱을 막지 않는다', async () => {
  const { result } = await quietly(() =>
    checkForAppUpdate({ readApp: async () => { throw new Error('Unable to get App Info'); }, fetchRelease: available(releaseBody()) })
  );
  assert.equal(result.kind, UPDATE_KIND.NONE);

  const webResult = await checkForAppUpdate({ readApp: async () => null, fetchRelease: available(releaseBody()) });
  assert.equal(webResult.kind, UPDATE_KIND.NONE);
});

test('업데이트 확인 요청에는 인증 헤더와 쿠키를 싣지 않는다', async () => {
  localStorage.setItem('token', 'expired-access-token');
  let captured = null;
  const fetchImpl = async (url, options) => {
    captured = { url, options };
    return jsonResponse(404, { code: 'NO_RELEASE' });
  };

  await fetchLatestRelease({ fetchImpl });
  localStorage.removeItem('token');

  assert.equal(captured.url, 'https://studybridge.test/api/app/version');
  assert.equal(captured.options.method, 'GET');
  assert.equal(captured.options.credentials, 'omit');
  assert.equal(captured.options.headers.Authorization, undefined);
});

test('versionCode 변환과 파일 크기 표시', () => {
  assert.equal(parseVersionCode('2'), 2);
  assert.equal(parseVersionCode(' 12 '), 12);
  assert.equal(parseVersionCode(3), 3);
  assert.equal(parseVersionCode('1.0'), null);
  assert.equal(parseVersionCode('0'), null);
  assert.equal(parseVersionCode(''), null);
  assert.equal(parseVersionCode(undefined), null);
  assert.equal(formatFileSize(19196753), '18.3 MB');
  assert.equal(formatFileSize(0), null);
  assert.equal(formatFileSize('19196753'), null);
});

test('세션당 한 번만 검사한다', async () => {
  let calls = 0;
  const session = createUpdateSession(async () => {
    calls += 1;
    return { kind: UPDATE_KIND.NONE, problem: null };
  });

  await Promise.all([session.check(), session.check()]);
  await session.check();
  assert.equal(calls, 1);
});

function optionalDecision(overrides = {}) {
  return {
    kind: UPDATE_KIND.OPTIONAL,
    problem: null,
    currentVersionName: '1.0.0',
    latestVersionName: '1.0.1',
    versionCode: 2,
    releaseNotes: ['모바일 안정성 개선', '회원가입 오류 수정'],
    downloadUrl: STABLE_DOWNLOAD_URL,
    fileSize: 19196753,
    ...overrides,
  };
}

async function renderGate({ decision, openDownload = async () => true, session }) {
  const { React } = await loadRenderer();
  const activeSession = session || createUpdateSession(async () => decision);
  const element = (key) =>
    React.createElement(
      AppUpdateGate,
      { session: activeSession, openDownload },
      React.createElement('main', { key }, `screen-${key}`)
    );
  const renderer = await renderElement(element('home'));
  await flushEffects();
  return { renderer, session: activeSession, element };
}

test('NO_RELEASE·같은 버전이면 화면만 보이고 모달이 없다', async () => {
  const { renderer } = await renderGate({ decision: { kind: UPDATE_KIND.NONE, problem: null } });
  assert.equal(findAllByText(renderer, 'screen-home').length, 1);
  assert.equal(renderer.root.findAll((node) => node.props?.role === 'alertdialog').length, 0);
  renderer.unmount();
});

test('선택 업데이트 모달은 버전·업데이트 내용·두 버튼을 보여준다', async () => {
  const { renderer } = await renderGate({ decision: optionalDecision() });

  assert.equal(findAllByText(renderer, '새로운 업데이트가 있습니다').length > 0, true);
  assert.equal(findAllByText(renderer, '1.0.0').length > 0, true);
  assert.equal(findAllByText(renderer, '1.0.1').length > 0, true);
  assert.equal(findAllByText(renderer, '회원가입 오류 수정').length > 0, true);
  assert.equal(findAllByText(renderer, '18.3 MB').length > 0, true);
  assert.ok(findButtonByText(renderer, '나중에'));
  assert.ok(findButtonByText(renderer, '업데이트'));
  assert.equal(findAllByText(renderer, 'screen-home').length, 1);
  renderer.unmount();
});

test('릴리즈 노트가 없어도 버전과 업데이트 버튼은 보인다', async () => {
  const { renderer } = await renderGate({ decision: optionalDecision({ releaseNotes: [], fileSize: null }) });
  assert.equal(findAllByText(renderer, '업데이트 내용').length, 0);
  assert.equal(findAllByText(renderer, '현재 버전').length > 0, true);
  assert.ok(findButtonByText(renderer, '업데이트'));
  renderer.unmount();
});

test('K. 나중에를 누른 뒤 화면이 다시 그려지거나 다시 마운트돼도 같은 세션에서는 다시 뜨지 않는다', async () => {
  const { renderer, session, element } = await renderGate({ decision: optionalDecision() });
  const { act } = await loadRenderer();

  await press(findButtonByText(renderer, '나중에'));
  assert.equal(findButtonByText(renderer, '업데이트'), null);

  await act(async () => renderer.update(element('planner')));
  await flushEffects();
  assert.equal(findButtonByText(renderer, '업데이트'), null);
  renderer.unmount();

  const remounted = await renderGate({ decision: optionalDecision(), session });
  assert.equal(findButtonByText(remounted.renderer, '업데이트'), null);
  remounted.renderer.unmount();
});

test('선택 업데이트에서 하드웨어 뒤로가기는 나중에와 같다', async () => {
  const { renderer } = await renderGate({ decision: optionalDecision() });
  const { act } = await loadRenderer();

  await act(async () => {
    assert.equal(dismissTopLayer(), true);
  });
  assert.equal(findButtonByText(renderer, '업데이트'), null);
  renderer.unmount();
  assert.equal(pendingDismissCount(), 0);
});

test('강제 업데이트는 나중에가 없고 뒤로가기로 닫히지 않는다', async () => {
  const { renderer } = await renderGate({ decision: optionalDecision({ kind: UPDATE_KIND.FORCED }) });
  const { act } = await loadRenderer();

  assert.equal(findAllByText(renderer, '업데이트가 필요합니다').length > 0, true);
  assert.equal(findAllByText(renderer, '최신 버전으로 업데이트해야 합니다').length > 0, true);
  assert.equal(findButtonByText(renderer, '나중에'), null);

  await act(async () => {
    assert.equal(dismissTopLayer(), true);
  });
  assert.ok(findButtonByText(renderer, '업데이트'));
  await act(async () => renderer.unmount());
  assert.equal(pendingDismissCount(), 0);
});

test('업데이트 버튼은 서버가 준 downloadUrl 을 연다. 강제 업데이트는 연 뒤에도 남는다', async () => {
  const openedUrls = [];
  const openDownload = async (url) => {
    openedUrls.push(url);
    return true;
  };

  const forced = await renderGate({ decision: optionalDecision({ kind: UPDATE_KIND.FORCED }), openDownload });
  await press(findButtonByText(forced.renderer, '업데이트'));
  assert.deepEqual(openedUrls, [STABLE_DOWNLOAD_URL]);
  assert.ok(findButtonByText(forced.renderer, '업데이트'));
  forced.renderer.unmount();

  const optional = await renderGate({ decision: optionalDecision(), openDownload });
  await press(findButtonByText(optional.renderer, '업데이트'));
  assert.equal(findButtonByText(optional.renderer, '업데이트'), null);
  optional.renderer.unmount();
});

test('다운로드 주소를 열지 못하면 모달에 안내하고 앱은 계속 동작한다', async () => {
  const { renderer } = await renderGate({ decision: optionalDecision(), openDownload: async () => false });
  await press(findButtonByText(renderer, '업데이트'));
  assert.equal(findAllByText(renderer, '다운로드 페이지를 열지 못했습니다').length > 0, true);
  assert.equal(findAllByText(renderer, 'screen-home').length, 1);
  renderer.unmount();
});
