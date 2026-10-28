import test from 'node:test';
import assert from 'node:assert/strict';
import { flushEffects, importMobileModule, loadRenderer, renderElement, textOf } from './support/componentHarness.mjs';

const { React, act } = await loadRenderer();
const api = await importMobileModule('../services/api.js');
const { default: SharedMaterialRanking } = await importMobileModule(
  'screens/groupstudy/room/SharedMaterialRanking.jsx'
);
const { resourceTabs } = await importMobileModule('screens/groupstudy/room/StudyResourcesPanel.jsx');

const mountedRenderers = [];

function stubServer({ materials, quizzesByMaterial = {}, rankingFor }) {
  const calls = { quizzes: [], ranking: [] };
  api.groupService.getSharedMaterials = async () => materials;
  api.materialService.getSharedQuizzes = async (materialId) => {
    calls.quizzes.push(String(materialId));
    return quizzesByMaterial[materialId] || [];
  };
  api.materialService.getQuizRanking = async (materialId, quizId) => {
    calls.ranking.push(`${materialId}/${quizId}`);
    return rankingFor(materialId, quizId);
  };
  return calls;
}

async function mount() {
  const renderer = await renderElement(React.createElement(SharedMaterialRanking, { groupId: 51 }));
  mountedRenderers.push(renderer);
  await flushEffects();
  await flushEffects();
  return renderer;
}

test.afterEach(async () => {
  while (mountedRenderers.length > 0) {
    const renderer = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
});

const PDF_A = { materialId: 10, title: '재무관리.pdf', ownerNickname: '고병준', quizCount: 1, mine: false };
const PDF_B = { materialId: 20, title: '회계원리.pdf', ownerNickname: '김도형', quizCount: 1, mine: true };

test('그룹 자료/퀴즈 패널에 PDF 랭킹 탭은 기능 플래그가 켜진 빌드에서만 있다', () => {
  assert.deepEqual(
    resourceTabs({ rankingEnabled: true }).map((tab) => tab.label),
    ['학습자료', '퀴즈', 'PDF 랭킹']
  );
  assert.deepEqual(
    resourceTabs({ rankingEnabled: false }).map((tab) => tab.label),
    ['학습자료', '퀴즈']
  );
});

test('공유된 PDF 의 퀴즈 랭킹을 순위·닉네임·최고점·정답률·본인 강조로 표시한다', async () => {
  const calls = stubServer({
    materials: [PDF_A],
    quizzesByMaterial: { 10: [{ quizId: 100, materialId: 10, createdAt: '2026-10-28T10:00:00', questions: [] }] },
    rankingFor: (materialId, quizId) => ({
      materialId,
      quizId,
      totalParticipants: 2,
      entries: [
        { rank: 1, nickname: 'B', score: 95, correctCount: 19, totalQuestions: 20, attemptCount: 1, isMe: false },
        { rank: 2, nickname: 'A', score: 90, correctCount: 18, totalQuestions: 20, attemptCount: 3, isMe: true },
      ],
      me: null,
    }),
  });

  const renderer = await mount();
  const text = textOf(renderer.toJSON());

  assert.deepEqual(calls.quizzes, ['10'], '공유 자료 퀴즈 목록(shared-quizzes)을 쓴다');
  assert.deepEqual(calls.ranking, ['10/100']);
  assert.match(text, /재무관리\.pdf/);
  assert.match(text, /참여 2명/);
  assert.match(text, /95점/);
  assert.match(text, /정답률 90%/);
  const myRow = renderer.root.find(
    (node) => node.type === 'li' && typeof node.props.className === 'string' && node.props.className.includes('is-me')
  );
  assert.match(textOf(myRow.children), /A/);
});

test('PDF 를 바꾸면 그 PDF 의 랭킹만 새로 요청한다(PDF별 독립)', async () => {
  const calls = stubServer({
    materials: [PDF_A, PDF_B],
    quizzesByMaterial: {
      10: [{ quizId: 100, materialId: 10, createdAt: '2026-10-28T10:00:00' }],
      20: [{ quizId: 200, materialId: 20, createdAt: '2026-10-28T10:00:00' }],
    },
    rankingFor: (materialId, quizId) => ({ materialId, quizId, totalParticipants: 0, entries: [], me: null }),
  });

  const renderer = await mount();
  const select = renderer.root.find((node) => node.type === 'select' && node.props['aria-label'] === '랭킹을 볼 PDF 선택');
  await act(async () => select.props.onChange({ target: { value: '20' } }));
  await flushEffects();
  await flushEffects();

  assert.deepEqual(calls.ranking, ['10/100', '20/200']);
  assert.match(textOf(renderer.toJSON()), /회계원리\.pdf/);
});

test('공유 자료 없음 · 퀴즈 없음 · 응시자 없음을 구분해 안내한다', async () => {
  stubServer({ materials: [], rankingFor: () => null });
  let renderer = await mount();
  assert.match(textOf(renderer.toJSON()), /공유된 PDF 자료가 없습니다/);

  stubServer({ materials: [PDF_A], quizzesByMaterial: { 10: [] }, rankingFor: () => null });
  renderer = await mount();
  assert.match(textOf(renderer.toJSON()), /아직 퀴즈가 없어 랭킹이 없습니다/);

  stubServer({
    materials: [PDF_A],
    quizzesByMaterial: { 10: [{ quizId: 100, materialId: 10 }] },
    rankingFor: (materialId, quizId) => ({ materialId, quizId, totalParticipants: 0, entries: [], me: null }),
  });
  renderer = await mount();
  assert.match(textOf(renderer.toJSON()), /아직 이 퀴즈의 응시 기록이 없습니다/);
});

test('랭킹 429 는 재시도 버튼과 함께 요청 제한을 안내하고, 그룹 비멤버 403 은 권한 안내만 한다', async () => {
  stubServer({
    materials: [PDF_A],
    quizzesByMaterial: { 10: [{ quizId: 100, materialId: 10 }] },
    rankingFor: () => {
      throw { response: { status: 429, data: {} } };
    },
  });
  let renderer = await mount();
  assert.match(textOf(renderer.toJSON()), /요청이 많아 잠시 제한되었습니다/);

  api.groupService.getSharedMaterials = async () => {
    throw { response: { status: 403, data: { code: 'FORBIDDEN' } } };
  };
  renderer = await mount();
  assert.match(textOf(renderer.toJSON()), /권한이 없습니다/);
});
