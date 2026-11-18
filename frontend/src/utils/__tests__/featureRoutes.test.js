// node --test frontend/src/utils/__tests__ — 홈 핵심 기능 카드 목적지 계약 + 유사문제 문항 수 계약
import test from 'node:test';
import assert from 'node:assert/strict';
import { FEATURE_ROUTES, featureRoute } from '../featureRoutes.js';

test('핵심 기능 카드 6개는 각자 실제 기능 라우트로 간다(전부 /studymate 금지)', () => {
  assert.equal(featureRoute('pdfSummary'), '/archive');
  assert.equal(featureRoute('roadmap'), '/planner');
  assert.equal(featureRoute('quiz'), '/archive');
  assert.equal(featureRoute('aiQna'), '/studymate'); // 구 /learning-mate 중복 화면 제거 → canonical 학습메이트
  assert.equal(featureRoute('groupStudy'), '/groupstudy');
  assert.equal(featureRoute('progress'), '/study-report');
  assert.equal(Object.keys(FEATURE_ROUTES).length, 6);
  assert.ok(!Object.values(FEATURE_ROUTES).every((r) => r === '/studymate'));
  assert.ok(!Object.values(FEATURE_ROUTES).includes('/learning-mate'), '레거시 /learning-mate 는 라우트 아님(리다이렉트만)');
  assert.equal(featureRoute('unknown'), '/');
});
