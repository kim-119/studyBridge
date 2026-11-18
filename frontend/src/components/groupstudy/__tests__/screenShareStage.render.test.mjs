// node --test frontend/src/components/groupstudy/__tests__
//  esbuild 로 JSX 를 번들한 뒤 react-dom/server 로 정적 렌더해 화면공유 스테이지의 버튼 노출 규칙을 단언한다(effect 미실행).
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
const outDir = fs.mkdtempSync(path.join(cacheRoot, 'sb-screenstage-test-'));
test.after(() => { try { fs.rmSync(outDir, { recursive: true, force: true }); } catch (e) { /* ignore */ } });
async function load(relPath) {
  const outfile = path.join(outDir, relPath.replace(/[\\/]/g, '_') + '.mjs');
  await esbuild.build({
    entryPoints: [path.join(frontendRoot, 'src', relPath)],
    bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic', logLevel: 'silent',
    external: ['react', 'react-dom', 'react/jsx-runtime', 'lucide-react'],
  });
  return import(pathToFileURL(outfile).href);
}

const html = (el) => renderToStaticMarkup(el);
const has = (markup, testid) => markup.includes(`data-testid="${testid}"`);
const sm = { stream: { connection: { connectionId: 'con_S' } }, addVideoElement() {} };
const remote = (id, name) => ({ connectionId: id, name, isMine: false, isOwnUser: false, streamManager: sm, hasAudio: true });
const mine = { connectionId: 'con_ME_SCR', name: '나', isMine: true, isOwnUser: true, streamManager: sm, hasAudio: false };
const base = { selectedId: null, onSelect: () => {}, onStopMine: () => {}, ownShare: { status: 'live', health: 'ok', liveSince: 0 }, viewers: [], receipts: {}, onReceipt: () => {} };

test('다른 참가자의 공유: PC·모바일 모두 "전체화면 보기" 문구가 보이는 버튼(모바일에서 텍스트 숨김 없음)', async () => {
  const { default: ScreenShareStage } = await load('components/groupstudy/ScreenShareStage.jsx');
  for (const isMobile of [false, true]) {
    const m = html(React.createElement(ScreenShareStage, { ...base, shares: [remote('con_A', '민수')], isMobile }));
    assert.ok(has(m, 'screen-stage-fullscreen'), `isMobile=${isMobile}`);
    assert.match(m, /data-testid="screen-stage-fullscreen"[^>]*>(<svg[\s\S]*?<\/svg>)?전체화면 보기<\/button>/);
    assert.match(m, /data-fullscreen="off"/);
    assert.ok(has(m, 'screen-stage-actual-size'), '원본 크기 보기 유지');
    assert.ok(has(m, 'screen-stage-video'));
  }
});

test('송출자 본인: 전체화면 진입 버튼 없음(반복 화면 방지) — 상태 카드·미리보기·공유 중지는 그대로', async () => {
  const { default: ScreenShareStage } = await load('components/groupstudy/ScreenShareStage.jsx');
  const m = html(React.createElement(ScreenShareStage, { ...base, shares: [mine], selectedId: mine.connectionId, isMobile: true }));
  assert.ok(!has(m, 'screen-stage-fullscreen'));
  assert.ok(has(m, 'screen-stage-own'));
  assert.ok(has(m, 'screen-stage-own-preview'));
  assert.ok(has(m, 'screen-stage-stop'));
});

test('공유가 여러 개: 선택 칩 유지, 다른 사람 공유를 고르면 전체화면 버튼', async () => {
  const { default: ScreenShareStage } = await load('components/groupstudy/ScreenShareStage.jsx');
  const shares = [mine, remote('con_A', '민수'), remote('con_B', '지은')];
  const m = html(React.createElement(ScreenShareStage, { ...base, shares, selectedId: 'con_B', isMobile: true }));
  for (const label of ['내 화면', '민수', '지은']) assert.ok(m.includes(`>${label}</button>`), label);
  assert.match(m, /data-connection-id="con_B"/);
  assert.ok(has(m, 'screen-stage-fullscreen'));
  const own = html(React.createElement(ScreenShareStage, { ...base, shares, selectedId: mine.connectionId, isMobile: false }));
  assert.ok(!has(own, 'screen-stage-fullscreen'));
});
