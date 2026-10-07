// node --test frontend/src/components/groupstudy/__tests__
//  모바일 모달 시스템(≤768px) 회귀 테스트 — prejoin.render.test.mjs 와 같은 방식(esbuild 번들 + react-dom/server 정적 렌더 + 소스/CSS 가드).
//  · 대상 모달에 공통 클래스(.sb-modal-overlay/.sb-modal/.sb-modal-head/.sb-modal-body/.sb-modal-foot)가 붙어 있는지
//  · index.css ≤768px 레이어에 탭 nowrap/keep-all 규칙, 검색 아이콘 공통 규칙, 모달 골격 규칙이 있는지
//  · 전역 svg 리사이즈(svg { width/height }) 규칙이 생기지 않았는지
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
const outDir = fs.mkdtempSync(path.join(cacheRoot, 'sb-mobile-modal-test-'));
test.after(() => { try { fs.rmSync(outDir, { recursive: true, force: true }); } catch (e) { /* ignore */ } });
async function load(relPath) {
  const outfile = path.join(outDir, relPath.replace(/[\\/]/g, '_') + '.mjs');
  await esbuild.build({
    entryPoints: [path.join(frontendRoot, 'src', relPath)],
    bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic', logLevel: 'silent',
    external: ['react', 'react-dom', 'react/jsx-runtime', 'lucide-react'],
    // services/api(axios → form-data → util 동적 require)는 정적 렌더에 불필요 → 빈 모듈로 대체
    plugins: [{ name: 'stub-api', setup(b) {
      b.onResolve({ filter: /services\/api(\.js)?$/ }, (a) => ({ path: a.path, namespace: 'stub-api' }));
      b.onLoad({ filter: /.*/, namespace: 'stub-api' }, () => ({ contents: 'const svc = new Proxy({}, { get: () => async () => ({}) }); export default svc; export const groupService = svc; export const authService = svc; export const agentService = svc; export const API_BASE_URL = "";', loader: 'js' }));
    } }],
  });
  return import(pathToFileURL(outfile).href);
}
const src = (rel) => fs.readFileSync(path.join(frontendRoot, 'src', rel), 'utf8');
const html = (el) => renderToStaticMarkup(el);

// index.css 에서 `@media (max-width: 768px)` 블록들의 본문만 이어 붙인다(중괄호 균형 기반).
function mobileLayer(css) {
  const out = [];
  const re = /@media\s*\(max-width:\s*768px\)\s*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1; let i = re.lastIndex;
    while (i < css.length && depth > 0) { if (css[i] === '{') depth++; else if (css[i] === '}') depth--; i++; }
    out.push(css.slice(re.lastIndex, i - 1));
  }
  return out.join('\n');
}
// 선언 블록 추출: 선택자 목록에 selector 를 포함하는 첫 규칙의 본문
function ruleBody(cssText, selector) {
  const idx = cssText.indexOf(selector);
  if (idx < 0) return null;
  const open = cssText.indexOf('{', idx); const close = cssText.indexOf('}', open);
  return cssText.slice(open + 1, close);
}

test('GroupEditModal renders with the shared mobile modal classes (overlay/box/head/body/foot)', async () => {
  const { default: GroupEditModal } = await load('components/groupstudy/GroupEditModal.jsx');
  const study = { id: 1, title: 'T', description: 'D', currentMembers: 1, maxMembers: 5, studyType: 'GENERAL', targetStudyMinutes: 240, joinQuestionEnabled: false, nicknameRuleEnabled: false, hasCoverImage: false };
  const m = html(React.createElement(GroupEditModal, { study, onClose: () => {}, onSaved: () => {} }));
  assert.ok(/class="sb-modal-overlay"/.test(m));
  assert.ok(/class="gs-modal sb-modal"/.test(m));
  assert.ok(/class="gs-modal-header sb-modal-head"/.test(m));
  assert.ok(/class="gs-modal-body sb-modal-body"/.test(m));
  assert.ok(/class="gs-modal-footer sb-modal-foot"/.test(m));
  assert.ok(m.includes('class="sb-modal-title"'));
  assert.ok(/class="sb-icon-btn"[^>]*aria-label="닫기"/.test(m) || /aria-label="닫기"[^>]*class="sb-icon-btn"/.test(m));
});

test('source guard: StudyMate AI 그룹 스터디 생성 modal carries the modal classes, compact prev/next and 1-column grid hook', () => {
  const s = src('pages/StudyMate.jsx');
  const start = s.indexOf('{showModal && (');
  const end = s.indexOf('{showDetailsModal && selectedAgent && (');
  assert.ok(start > 0 && end > start);
  const block = s.slice(start, end);
  assert.ok(block.includes('className="modal-overlay sb-modal-overlay"'));
  assert.ok(block.includes('className="glass-panel modal-content sb-modal sb-modal-aig"'));
  assert.ok(block.includes('className="modal-header sb-modal-head"'));
  assert.ok(block.includes('className="sb-modal-body"'));
  assert.ok(block.includes('className="sb-modal-foot"'));
  assert.equal((block.match(/className="sb-aig-nav-col"/g) || []).length, 2); // 좌/우 큰 화살표 열
  assert.equal((block.match(/className="sb-aig-nav-compact sb-icon-btn"/g) || []).length, 2); // 푸터 컴팩트 ‹ ›
  assert.ok(block.includes('<ChevronLeft size={18} />') && block.includes('<ChevronRight size={18} />'));
  assert.ok(block.includes('className="sb-aig-grid2"'));
  // 로직 불변: 단계 이동 핸들러/제출 핸들러 그대로
  assert.ok(block.includes('onClick={goPrevModalStep}') && block.includes('onClick={goNextModalStep}') && block.includes('onSubmit={handleCreateAgent}'));
});

test('source guard: StudyRoom 방 관리 / 문의 및 신고 modals carry the modal classes, tab strip and 1-column rows', () => {
  const s = src('components/StudyRoom.jsx');
  const manageStart = s.indexOf('{showRoomManageModal && (');
  const reportStart = s.indexOf('{showAdminReportModal && (');
  const reportEnd = s.indexOf('{showPdfUploadModal && (');
  assert.ok(manageStart > 0 && reportStart > manageStart && reportEnd > reportStart);
  const manage = s.slice(manageStart, reportStart);
  const report = s.slice(reportStart, reportEnd);
  for (const block of [manage, report]) {
    assert.ok(block.includes('className="sb-modal-overlay"'));
    assert.ok(block.includes('className="sb-modal sb-modal-dark"'));
    assert.ok(block.includes('className="sb-modal-head sb-modal-tabs"'));
    assert.ok(block.includes('className="sb-modal-close sb-icon-btn"'));
    assert.ok(block.includes('className="custom-scrollbar sb-modal-body"'));
    assert.ok(block.includes('className="sb-modal-foot"'));
  }
  assert.equal((manage.match(/className="sb-modal-tab"/g) || []).length, 5); // 방 관리/멤버/가입 신청/실시간 퀴즈/퀴즈 랭킹
  assert.equal((manage.match(/className="sb-modal-row"/g) || []).length, 5); // 해시태그/기간/목표/장치/공지
  assert.ok(manage.includes('className="sb-chip-row"'));
  assert.equal((report.match(/className="sb-modal-tab"/g) || []).length, 2); // 1:1 문의 / 유저 신고
  assert.ok(report.includes('className="sb-modal-title"') && report.includes('문의 및 신고하기'));
  // 로직 불변
  assert.ok(manage.includes("onClick={() => setRoomManageTab('quiz')}") && report.includes("onClick={() => setAdminReportTab('report')}"));
});

test('source guard: GroupStudy 상세 모달 / 방장 관리 콘솔 carry the modal classes; search icon uses the shared class', () => {
  const s = src('pages/GroupStudy.jsx');
  assert.ok(s.includes('className="sb-modal" data-testid="gs-detail-modal"'));
  assert.ok(s.includes('className="glass-panel animate-fade-in sb-modal" data-testid="leader-console-modal"'));
  assert.equal((s.match(/className="sb-modal-overlay"/g) || []).length, 2);
  assert.ok(s.includes('<Search size={20} color="#9CA3AF" className="sb-search-icon"'));
  assert.ok(src('pages/Knowledge.jsx').includes('className="sb-search-icon"'));
  assert.ok(src('pages/ObsidianPage.jsx').includes('className="sb-search-icon sb-search-icon-abs"'));
});

test('index.css ≤768px layer: modal skeleton, tab nowrap/keep-all, shared search icon rule; no global svg resize', () => {
  const css = fs.readFileSync(path.join(frontendRoot, 'src/index.css'), 'utf8');
  const layer = mobileLayer(css);
  // 골격
  const box = ruleBody(layer, '.sb-modal {');
  assert.ok(box, '.sb-modal rule missing in mobile layer');
  assert.ok(/width:\s*calc\(100vw - 24px\)/.test(box) && /max-width:\s*440px/.test(box) && /margin-inline:\s*12px/.test(box));
  assert.ok(/max-height:\s*88vh/.test(box) && /88dvh/.test(box) && /safe-area-inset-bottom/.test(box));
  assert.ok(/flex-direction:\s*column/.test(box));
  assert.ok(/flex-shrink:\s*0/.test(ruleBody(layer, '.sb-modal-head {')));
  const body = ruleBody(layer, '.sb-modal-body {');
  assert.ok(/min-height:\s*0/.test(body) && /overflow-y:\s*auto/.test(body));
  assert.ok(/flex-shrink:\s*0/.test(ruleBody(layer, '.sb-modal-foot {')));
  // 탭: nowrap + keep-all + 축소 금지 + 스트립 가로 스크롤
  const tabs = ruleBody(layer, '.sb-modal-tabs > *');
  assert.ok(/white-space:\s*nowrap/.test(tabs) && /word-break:\s*keep-all/.test(tabs) && /flex-shrink:\s*0/.test(tabs));
  assert.ok(/overflow-x:\s*auto/.test(ruleBody(layer, '.sb-modal-tabs {')));
  // 검색 아이콘 공통 규칙(18px / stroke 1.8 토큰)
  const search = ruleBody(layer, 'svg.lucide.sb-search-icon {');
  assert.ok(search && /var\(--sb-icon-lg\)/.test(search) && /var\(--sb-icon-stroke\)/.test(search));
  assert.ok(/--sb-icon-lg:\s*18px/.test(css) && /--sb-icon-stroke:\s*1\.8/.test(css));
  // AI 그룹 모달: 좌우 화살표 열 숨김 + 2열 grid 1열
  assert.ok(/\.sb-modal-aig \.sb-aig-nav-col \{ display: none !important;/.test(layer));
  assert.ok(/grid-template-columns:\s*1fr !important/.test(ruleBody(layer, '.sb-modal-aig .sb-aig-grid2')));
  // 컴팩트 ‹ › 는 데스크톱(미디어 밖)에서 숨김
  assert.ok(/^\.sb-aig-nav-compact \{ display: none; \}/m.test(css));
  // 전역 svg 리사이즈 금지(아이콘 스케일 시스템은 svg.lucide 속성 기반만 허용)
  assert.equal(/(^|[\s}])svg\s*\{[^}]*(width|height)\s*:/m.test(css), false);
});
