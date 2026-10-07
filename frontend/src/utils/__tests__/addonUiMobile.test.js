// node --test frontend/src/utils/__tests__ — ADDON-UI 모바일 회귀(정적 소스/CSS 가드)
//  · 주간 일정: 종료 날짜 input[type=date] 모바일 폭 고정 규칙 + 1열(minmax(0,1fr)) + 할 일 입력 행 grid
//  · 캘린더: FullCalendar 7열(calc(100%/7)) + 테이블 100%/fixed + 모바일 dot 표시(list-item)
//  · 학습일지 상세: data-detail-type="journal" 1열 grid(minmax(0,1fr)) + 액션/제목 순서
//  · 핵심 기능 카드 aiQna → /studymate, App 에 /learning-mate 페이지 라우트 없음(리다이렉트만), LearningMate.jsx 삭제
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FEATURE_ROUTES } from '../featureRoutes.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(__dirname, '../..');
const read = (rel) => fs.readFileSync(path.join(srcRoot, rel), 'utf8');
const css = read('index.css');

// `@media (max-width: 768px)` 블록 본문만 이어 붙임(중괄호 균형 기반, mobile-modal-system.test.mjs 와 동일 방식)
function mobileLayer(text) {
  const out = [];
  const re = /@media\s*\(max-width:\s*768px\)\s*\{/g;
  let m;
  while ((m = re.exec(text))) {
    let depth = 1; let i = re.lastIndex;
    while (i < text.length && depth > 0) { if (text[i] === '{') depth++; else if (text[i] === '}') depth--; i++; }
    out.push(text.slice(re.lastIndex, i - 1));
  }
  return out.join('\n');
}
// 선택자(정확히 포함)를 가진 첫 규칙의 선언 본문
function ruleBody(text, selector) {
  const idx = text.indexOf(selector);
  if (idx < 0) return null;
  const open = text.indexOf('{', idx); const close = text.indexOf('}', open);
  return text.slice(open + 1, close);
}
const mobile = mobileLayer(css);
const norm = (s) => s.replace(/\s+/g, ' ');

test('주간 일정: 종료 날짜 date 입력이 모바일 레이어에서 폭 100%/min-width:0/appearance 제거로 고정된다', () => {
  const body = ruleBody(mobile, '.ws-enddate input[type="date"]');
  assert.ok(body, '.ws-enddate input[type="date"] 규칙이 ≤768px 레이어에 있어야 함');
  for (const decl of ['width: 100%', 'min-width: 0', 'max-width: 100%', 'box-sizing: border-box', '-webkit-appearance: none']) {
    assert.ok(norm(body).includes(decl), `date 입력 규칙에 ${decl} 필요`);
  }
  assert.ok(norm(ruleBody(mobile, '.dashboard-page .main-grid') || '').includes('minmax(0, 1fr)'), '.main-grid 는 모바일 1열 minmax(0,1fr)');
  const add = norm(ruleBody(mobile, '.ws-add-row') || '');
  assert.ok(add.includes('display: grid') && add.includes('minmax(0, 1fr)'), '.ws-add-row 는 grid minmax(0,1fr) + 버튼 열');
  const jsx = read('pages/WeeklySchedule.jsx');
  for (const cls of ['ws-enddate', 'ws-add-row', 'ws-date-card', 'ws-todo-stats']) assert.ok(jsx.includes(`className="${cls}"`), `WeeklySchedule.jsx 에 ${cls} 래퍼 필요`);
});

test('캘린더: 모바일 7열 고정(calc(100% / 7)) + 테이블 100%/fixed + dot 표시(list-item)', () => {
  const cell = norm(ruleBody(mobile, '.dashboard-page .fc .fc-daygrid-day {') || ruleBody(mobile, '.dashboard-page .fc .fc-col-header-cell,') || '');
  assert.ok(cell.includes('calc(100% / 7)'), '요일 헤더/일 셀 폭 = calc(100% / 7)');
  assert.ok(cell.includes('min-width: 0'), '셀 min-width:0');
  const table = norm(ruleBody(mobile, '.dashboard-page .fc .fc-scrollgrid,') || '');
  assert.ok(table.includes('width: 100% !important') && table.includes('table-layout: fixed'), '스크롤그리드 테이블 100% + fixed');
  assert.ok(norm(mobile).includes('.ws-event-dot {'), '모바일 dot 클래스 규칙');
  const jsx = read('pages/WeeklySchedule.jsx');
  assert.ok(jsx.includes("eventDisplay={isMobile ? 'list-item' : 'auto'}"), 'FullCalendar eventDisplay list-item on mobile');
  assert.ok(jsx.includes("useIsMobile"), 'useIsMobile 훅 사용');
  assert.ok(jsx.includes("height={isMobile ? 'auto' : '650px'}"), '데스크톱 650px 유지, 모바일 auto');
  // 데스크톱 규칙 불변: 기본 main-grid 3열
  assert.ok(norm(ruleBody(css, '.dashboard-page .main-grid {')).includes('repeat(3, 1fr)'), '데스크톱 .main-grid 3열 유지');
});

test('학습일지 상세: 모바일 1열(grid minmax(0,1fr)) + 패널 폭 100%/높이 auto + 제목→액션 순서', () => {
  const split = norm(ruleBody(mobile, '.archive-detail-container[data-detail-type="journal"] .archive-split-view') || '');
  assert.ok(split.includes('display: grid') && split.includes('grid-template-columns: minmax(0, 1fr)'), '학습일지 split-view 는 1열 grid');
  const panel = norm(ruleBody(mobile, '.archive-detail-container[data-detail-type="journal"] .archive-left-panel,') || '');
  for (const decl of ['width: 100% !important', 'max-width: 100%', 'min-width: 0', 'height: auto !important']) assert.ok(panel.includes(decl), `패널 규칙에 ${decl}`);
  assert.ok(norm(ruleBody(mobile, '.archive-journal-head .archive-journal-title') || '').includes('order: 1'));
  assert.ok(norm(ruleBody(mobile, '.archive-journal-head .archive-journal-actions') || '').includes('order: 2'));
  const jsx = read('pages/ArchiveDetail.jsx');
  assert.ok(jsx.includes('data-detail-type={type}'), 'ArchiveDetail 컨테이너에 data-detail-type');
  for (const cls of ['archive-journal-head', 'archive-journal-actions', 'archive-journal-title']) assert.ok(jsx.includes(`className="${cls}"`), `${cls} 래퍼`);
  // 전역 svg 리사이즈 규칙 금지(기존 규칙 유지)
  assert.ok(!/(^|[\s,}])svg\s*\{/m.test(css.replace(/svg\.lucide|svg\[[^\]]*\]/g, '')), '전역 svg{} 규칙 금지');
});

test('/learning-mate 중복 화면 제거: featureRoutes aiQna=/studymate, App 은 Navigate 리다이렉트만, LearningMate.jsx 없음', () => {
  assert.equal(FEATURE_ROUTES.aiQna, '/studymate');
  assert.ok(!Object.values(FEATURE_ROUTES).includes('/learning-mate'));
  const app = read('App.jsx');
  assert.ok(!app.includes("import LearningMate"), 'App.jsx 는 LearningMate 를 import 하지 않음');
  assert.ok(!/<LearningMate\b/.test(app), 'App.jsx 에 <LearningMate /> 페이지 라우트 없음');
  const redirect = app.match(/<Route path="\/learning-mate" element=\{<Navigate to="\/studymate" replace \/>\} \/>/);
  assert.ok(redirect, '/learning-mate → /studymate Navigate replace 리다이렉트');
  assert.ok(/<Route path="\/studymate" element=\{<PrivateRoute><StudyMate \/>/.test(app), '/studymate canonical 라우트 유지');
  assert.ok(!fs.existsSync(path.join(srcRoot, 'pages/LearningMate.jsx')), 'LearningMate.jsx 삭제됨');
  // 리다이렉트 루프 방지: /studymate 가 /learning-mate 로 가는 Navigate 가 없어야 함
  assert.ok(!/Navigate to="\/learning-mate"/.test(app));
});
