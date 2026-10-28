import test from 'node:test';
import assert from 'node:assert/strict';
import { flushEffects, importMobileModule, loadRenderer, renderElement } from './support/componentHarness.mjs';

const { React, act } = await loadRenderer();
const api = await importMobileModule('../services/api.js');
const { useScreenAnalysis } = await importMobileModule('screens/groupstudy/useScreenAnalysis.js');

const mountedRenderers = [];
let latest;

const SHARE = { connectionId: 'con_pc', streamId: 'str_pc', sharerName: '고병준', isMine: false, analyzable: true };
const RECEIVING = [{ connectionId: 'con_pc', videoKind: 'SCREEN', streamManager: { id: 'sm' }, screenOn: true }];

function stubServer({ analyze } = {}) {
  const calls = { shares: 0, analyze: [], cancel: [], captures: 0 };
  api.groupService.getScreenAiShares = async () => {
    calls.shares += 1;
    return { enabled: true, viewerConnected: true, shares: [SHARE], limits: { timeoutSeconds: 10 } };
  };
  api.groupService.analyzeScreen = async (groupId, body, options) => {
    calls.analyze.push({ groupId, body, options });
    return analyze ? analyze(body, options) : { answer: '요약 결과', model: 'qwen3-vl' };
  };
  api.groupService.cancelScreenAnalysis = async (groupId, clientRequestId) => {
    calls.cancel.push(clientRequestId);
    return { cancelled: true };
  };
  return calls;
}

function Harness({ remotes, capture }) {
  latest = useScreenAnalysis(51, remotes, { capture });
  return null;
}

async function mount(remotes, calls) {
  const capture = async () => {
    calls.captures += 1;
    return { dataUrl: 'data:image/jpeg;base64,AAAA' };
  };
  const renderer = await renderElement(React.createElement(Harness, { remotes, capture }));
  mountedRenderers.push({ renderer, capture });
  await flushEffects();
  return { renderer, capture };
}

test.afterEach(async () => {
  while (mountedRenderers.length > 0) {
    const { renderer } = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
});

test('지금 프레임을 캡처해 서버 계약으로 보내고 답변을 표시한다', async () => {
  const calls = stubServer();
  await mount(RECEIVING, calls);

  let outcome;
  await act(async () => {
    outcome = await latest.analyze(latest.shares[0], '지금 보이는 화면을 요약해 줘.');
  });

  assert.equal(outcome.ok, true);
  assert.equal(calls.captures, 1);
  const [{ body, options }] = calls.analyze;
  assert.equal(body.connectionId, 'con_pc');
  assert.equal(body.streamId, 'str_pc');
  assert.equal(body.mime, 'image/jpeg');
  assert.equal(options.timeoutMs, 10_000 + 15_000, '서버 타임아웃 + 여유');
  assert.deepEqual(
    latest.entries.map((entry) => [entry.status, entry.answer]),
    [['done', '요약 결과']]
  );
  assert.equal(latest.isPending, false);
});

test('진행 중에는 두 번째 요청을 보내지 않는다(중복 분석 방지)', async () => {
  let release;
  const calls = stubServer({ analyze: () => new Promise((resolve) => (release = () => resolve({ answer: 'ok' }))) });
  await mount(RECEIVING, calls);

  let second;
  await act(async () => {
    latest.analyze(latest.shares[0], '첫 질문');
    await new Promise((resolve) => setTimeout(resolve, 0));
    second = await latest.analyze(latest.shares[0], '두 번째 질문');
  });

  assert.equal(second.ok, false);
  assert.equal(calls.analyze.length, 1);
  await act(async () => release());
});

test('분석 중 화면공유가 끝나면 요청을 취소하고 서버 취소 API 를 호출한다', async () => {
  const calls = stubServer({
    analyze: (body, { signal }) =>
      new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' })));
      }),
  });
  const { renderer, capture } = await mount(RECEIVING, calls);

  await act(async () => {
    latest.analyze(latest.shares[0], '오류를 분석해 줘');
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(latest.isPending, true);

  await act(async () => renderer.update(React.createElement(Harness, { remotes: [], capture })));
  await flushEffects();

  assert.equal(calls.cancel.length, 1);
  assert.equal(calls.cancel[0], calls.analyze[0].body.clientRequestId);
  const [entry] = latest.entries;
  assert.equal(entry.status, 'cancelled');
  assert.match(entry.errorMessage, /화면공유가 종료되어 분석을 중단했습니다/);
});

test('서버 거부(동의 철회)는 실패로 표시하고 다음 요청을 막지 않는다', async () => {
  let first = true;
  const calls = stubServer({
    analyze: () => {
      if (first) {
        first = false;
        throw { response: { status: 403, data: { code: 'SHARER_CONSENT_REQUIRED', retryable: false } } };
      }
      return { answer: '두 번째 답' };
    },
  });
  await mount(RECEIVING, calls);

  await act(async () => {
    await latest.analyze(latest.shares[0], '요약');
  });
  assert.equal(latest.entries[0].status, 'failed');
  assert.match(latest.entries[0].errorMessage, /허용하지 않았습니다/);

  await act(async () => {
    await latest.analyze(latest.shares[0], '요약');
  });
  assert.equal(latest.entries[1].status, 'done');
});

test('화면을 떠나면 진행 중 분석을 취소한다', async () => {
  const calls = stubServer({
    analyze: (body, { signal }) =>
      new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' })));
      }),
  });
  await mount(RECEIVING, calls);
  await act(async () => {
    latest.analyze(latest.shares[0], '요약');
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  const { renderer } = mountedRenderers.pop();
  await act(async () => renderer.unmount());
  assert.equal(calls.cancel.length, 1);
});

test('내 화면공유(Android 송출)는 분석 대상이 아니라 AI 분석 허용 토글로 보이고, 바꾸면 서버에 반영한다', async () => {
  const calls = stubServer();
  const consents = [];
  api.groupService.getScreenAiShares = async () => {
    calls.shares += 1;
    return {
      enabled: true,
      viewerConnected: true,
      shares: [{ connectionId: 'con_mine', streamId: 'str_m', sharerName: '나', isMine: true, aiConsent: consents.at(-1) ?? false }],
    };
  };
  api.groupService.setScreenAiConsent = async (groupId, connectionId, allowed) => {
    consents.push(allowed);
    return { connectionId, aiConsent: allowed };
  };
  await mount([], calls);

  assert.deepEqual(latest.shares, [], '내 공유는 분석 대상 목록에 없다');
  assert.deepEqual(latest.ownShares, [{ connectionId: 'con_mine', hasConsent: false, deviceType: null }]);

  await act(async () => latest.setConsent('con_mine', true));
  await flushEffects();
  assert.deepEqual(consents, [true]);
  assert.equal(latest.ownShares[0].hasConsent, true);
});
