// node --test frontend/src/components/groupstudy/__tests__
//  esbuild 로 JSX 를 번들한 뒤 react-dom/server 로 정적 렌더해 AI 화면 분석 탭·공유자 동의 토글의 노출 규칙을 단언한다(effect 미실행).
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '../../../..');
const require = createRequire(path.join(frontendRoot, 'package.json'));
const esbuild = require('esbuild');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const cacheRoot = path.join(frontendRoot, 'node_modules', '.cache');
fs.mkdirSync(cacheRoot, { recursive: true });
const outDir = fs.mkdtempSync(path.join(cacheRoot, 'sb-screenai-test-'));
test.after(() => { try { fs.rmSync(outDir, { recursive: true, force: true }); } catch (e) { /* ignore */ } });
async function load(relPath) {
  const outfile = path.join(outDir, relPath.replace(/[\\/]/g, '_') + '.mjs');
  await esbuild.build({
    entryPoints: [path.join(frontendRoot, 'src', relPath)],
    bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic', logLevel: 'silent',
    define: { 'import.meta.env': '{}' }, // services/api.js 의 Vite env 참조
    external: ['react', 'react-dom', 'react/jsx-runtime', 'lucide-react', 'axios'],
  });
  return import(pathToFileURL(outfile).href);
}

const html = (el) => renderToStaticMarkup(el);
const has = (markup, testid) => markup.includes(`data-testid="${testid}"`);
const sm = (streamId) => ({ stream: { streamId, connection: { connectionId: 'con_x' } }, addVideoElement() {} });
const share = (id, name, extra = {}) => ({ connectionId: id, userId: 1, name, isMine: false, isOwnUser: false, streamManager: sm(`str_${id}`), connectedAt: 1, ...extra });
const base = { groupId: 25, stageSelectedId: null, onFocusShare: () => {}, visible: false, consentNonce: 0, myConsent: { connectionId: null, allowed: false, busy: false }, onToggleMyConsent: () => {} };

test('공유 화면이 없으면 빈 안내 + 질문 입력 비활성', async () => {
  const { default: ScreenAiPanel } = await load('components/groupstudy/ScreenAiPanel.jsx');
  const m = html(React.createElement(ScreenAiPanel, { ...base, shares: [] }));
  assert.ok(has(m, 'screen-ai-empty'));
  assert.match(m, /data-testid="screen-ai-question"[^>]*disabled/);
  assert.match(m, /data-testid="screen-ai-ask"[^>]*disabled/);
});

test('공유 화면 2개: 화면 번호·공유자 이름으로 구분해 고를 수 있고, 예시 질문이 보인다', async () => {
  const { default: ScreenAiPanel } = await load('components/groupstudy/ScreenAiPanel.jsx');
  const m = html(React.createElement(ScreenAiPanel, { ...base, shares: [share('con_SA', '민지'), share('con_SB', '서준')] }));
  assert.equal((m.match(/data-testid="screen-ai-share"/g) || []).length, 2);
  assert.match(m, /화면 1/);
  assert.match(m, /민지님의 화면/);
  assert.match(m, /화면 2/);
  assert.match(m, /서준님의 화면/);
  assert.match(m, /공유자 동의 확인 중/); // 서버 상태를 읽기 전(effect 미실행) — 남의 화면은 분석 가능으로 보이지 않는다
  assert.match(m, /data-analyzable="false"/);
  assert.ok(has(m, 'screen-ai-example'));
  assert.match(m, /이 Python 오류의 원인을 분석해 줘/);
  assert.ok(!has(m, 'screen-ai-my-consent'));
});

test('내가 공유 중이면 "내 화면 AI 분석 허용" 토글이 보이고, 내 화면은 바로 분석 가능', async () => {
  const { default: ScreenAiPanel } = await load('components/groupstudy/ScreenAiPanel.jsx');
  const mine = share('con_ME', '나', { isMine: true, isOwnUser: true });
  const m = html(React.createElement(ScreenAiPanel, { ...base, shares: [mine], myConsent: { connectionId: 'con_ME', allowed: true, busy: false } }));
  assert.ok(has(m, 'screen-ai-my-consent'));
  assert.match(m, /role="switch" aria-checked="true"/);
  assert.match(m, /내 화면 · 분석 가능/);
  assert.match(m, /data-analyzable="true"/);
});

test('송출자 상태 카드에 AI 분석 허용 토글(기본 꺼짐) — 시청자 화면에는 없음', async () => {
  const { default: ScreenShareStage } = await load('components/groupstudy/ScreenShareStage.jsx');
  const stageBase = { onSelect: () => {}, onStopMine: () => {}, ownShare: { status: 'live', health: 'ok', liveSince: 0 }, viewers: [], receipts: {}, onReceipt: () => {}, onToggleAiConsent: () => {} };
  const mine = { connectionId: 'con_ME', name: '나', isMine: true, isOwnUser: true, streamManager: sm('str_ME'), hasAudio: false };
  const own = html(React.createElement(ScreenShareStage, { ...stageBase, shares: [mine], selectedId: 'con_ME', aiConsent: { connectionId: 'con_ME', allowed: false, busy: false } }));
  assert.ok(has(own, 'screen-own-ai-consent'));
  assert.match(own, /data-allowed="false"/);
  const remote = html(React.createElement(ScreenShareStage, { ...stageBase, shares: [{ ...share('con_SA', '민지'), hasAudio: false }], selectedId: 'con_SA' }));
  assert.ok(!has(remote, 'screen-own-ai-consent'));
});

test('공유 준비 안내: AI 분석 허용 체크박스는 기본 꺼짐(opt-in)', async () => {
  const { default: ScreenSharePrepDialog } = await load('components/groupstudy/ScreenSharePrepDialog.jsx');
  const m = html(React.createElement(ScreenSharePrepDialog, { mode: 'document', withAudio: true, aiConsent: false, onAiConsentChange: () => {}, onModeChange: () => {}, onAudioChange: () => {}, onCancel: () => {}, onConfirm: () => {} }));
  assert.ok(has(m, 'screen-share-ai-consent'));
  assert.ok(!/data-testid="screen-share-ai-consent"[^>]*checked/.test(m));
});
