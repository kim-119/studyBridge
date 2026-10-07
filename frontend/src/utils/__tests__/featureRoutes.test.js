// node --test frontend/src/utils/__tests__ — 홈 핵심 기능 카드 목적지 계약 + 유사문제 문항 수 계약
import test from 'node:test';
import assert from 'node:assert/strict';
import { FEATURE_ROUTES, featureRoute } from '../featureRoutes.js';

test('핵심 기능 카드 6개는 각자 실제 기능 라우트로 간다(전부 /studymate 금지)', () => {
  assert.equal(featureRoute('pdfSummary'), '/archive');
  assert.equal(featureRoute('roadmap'), '/planner');
  assert.equal(featureRoute('quiz'), '/archive');
  assert.equal(featureRoute('aiQna'), '/learning-mate');
  assert.equal(featureRoute('groupStudy'), '/groupstudy');
  assert.equal(featureRoute('progress'), '/study-report');
  assert.equal(Object.keys(FEATURE_ROUTES).length, 6);
  assert.ok(!Object.values(FEATURE_ROUTES).every((r) => r === '/studymate'));
  assert.equal(featureRoute('unknown'), '/');
});
