import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isGroupLeader } from '../screens/groupstudy/groupStudyModel.js';
import { RESOURCE_KIND, runResourceDeletion, withoutResource } from '../screens/groupstudy/resourceDeleteModel.js';

const RESOURCES_PANEL_SOURCE = readFileSync(
  new URL('../screens/groupstudy/room/StudyResourcesPanel.jsx', import.meta.url),
  'utf8'
);

function listHolder(initial) {
  let list = initial;
  return {
    read: () => list,
    setData: (updater) => {
      list = typeof updater === 'function' ? updater(list) : updater;
    },
  };
}

test('T1 방장에게는 그룹 퀴즈 삭제 UI 가 보인다', () => {
  assert.equal(isGroupLeader({ leaderId: 7 }, 7), true);
  assert.equal(isGroupLeader({ leaderId: '7' }, 7), true);
  assert.match(
    RESOURCES_PANEL_SOURCE,
    /\{isLeader && \(\s*<div[^>]*>\s*<LeaderDeleteAction kind=\{RESOURCE_KIND\.QUIZ\}/
  );
});

test('T2 일반 멤버와 비로그인 상태에서는 삭제 UI 를 숨긴다', () => {
  assert.equal(isGroupLeader({ leaderId: 7 }, 8), false);
  assert.equal(isGroupLeader({ leaderId: 7 }, null), false);
  assert.equal(isGroupLeader(null, 7), false);

  const unguardedDeleteActions = RESOURCES_PANEL_SOURCE.split('<LeaderDeleteAction kind=').length - 1;
  const guardedDeleteActions = RESOURCES_PANEL_SOURCE.match(/isLeader && \(\s*(<div[^>]*>\s*)?<LeaderDeleteAction/g) || [];
  assert.equal(guardedDeleteActions.length, unguardedDeleteActions);
});

test('T3 삭제 성공 시 새로고침을 기다리지 않고 목록에서 바로 사라진다', async () => {
  const quizzes = listHolder([
    { id: 1, title: 'A' },
    { id: 2, title: 'B' },
  ]);
  const deleted = [];
  let reloadCalls = 0;

  const outcome = await runResourceDeletion({
    kind: RESOURCE_KIND.QUIZ,
    resourceId: 2,
    deleteRequest: async (id) => deleted.push(id),
    removeFromList: quizzes.setData,
    reloadList: () => {
      reloadCalls += 1;
      return new Promise(() => {});
    },
  });

  assert.deepEqual(outcome, { ok: true, errorMessage: null });
  assert.deepEqual(deleted, [2]);
  assert.deepEqual(quizzes.read(), [{ id: 1, title: 'A' }]);
  assert.equal(reloadCalls, 1);
  assert.deepEqual(withoutResource([{ quizId: 3 }, { quizId: 4 }], RESOURCE_KIND.QUIZ, '3'), [{ quizId: 4 }]);
});

test('T4 삭제 실패 시 목록을 유지하고 오류 문구를 돌려준다', async () => {
  const quizzes = listHolder([{ id: 1 }]);

  const outcome = await runResourceDeletion({
    kind: RESOURCE_KIND.QUIZ,
    resourceId: 1,
    deleteRequest: async () => {
      throw { response: { status: 409, data: { message: '진행 중인 세션이 있습니다.' } } };
    },
    removeFromList: quizzes.setData,
    reloadList: async () => [],
  });

  assert.equal(outcome.ok, false);
  assert.equal(outcome.errorMessage, '진행 중인 세션이 있습니다.');
  assert.deepEqual(quizzes.read(), [{ id: 1 }]);
});
