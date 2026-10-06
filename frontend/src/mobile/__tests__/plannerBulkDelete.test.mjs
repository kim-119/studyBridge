import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_SELECTION,
  bulkDeleteConfirmMessage,
  isAllSelected,
  pruneSelection,
  runBulkDelete,
  startSelecting,
  toggleSelectAll,
  toggleSelected,
  withoutPlanners,
} from '../screens/planner/plannerSelection.js';

test('T10 여러 플래너를 선택하고 해제할 수 있다', () => {
  let selection = startSelecting();
  selection = toggleSelected(selection, 1);
  selection = toggleSelected(selection, 3);
  assert.deepEqual(selection.selectedIds, [1, 3]);

  selection = toggleSelected(selection, 1);
  assert.deepEqual(selection.selectedIds, [3]);

  selection = toggleSelectAll(selection, [1, 2, 3]);
  assert.equal(isAllSelected(selection, [1, 2, 3]), true);
  assert.deepEqual(toggleSelectAll(selection, [1, 2, 3]).selectedIds, []);
  assert.deepEqual(pruneSelection({ isSelecting: true, selectedIds: [1, 9] }, [1, 2]).selectedIds, [1]);
});

test('T11 삭제 전 확인 문구에 선택 개수를 보여주고, 빈 선택은 요청하지 않는다', async () => {
  assert.match(bulkDeleteConfirmMessage(3), /플래너 3개를 삭제할까요\?/);

  let calls = 0;
  const outcome = await runBulkDelete({
    plannerIds: [],
    bulkDelete: async () => {
      calls += 1;
    },
  });
  assert.equal(outcome.ok, false);
  assert.equal(calls, 0);
});

test('T12 삭제에 성공한 플래너만 목록에서 제거하고, 실패하면 목록을 유지하며 이유를 알린다', async () => {
  const requested = [];
  const success = await runBulkDelete({
    plannerIds: [1, 3],
    bulkDelete: async (ids) => {
      requested.push(ids);
      return { success: true, deletedCount: 2, message: '2개의 플래너를 삭제했습니다.' };
    },
  });
  const planners = [{ id: 1 }, { id: 2 }, { id: 3 }];

  assert.deepEqual(requested, [[1, 3]]);
  assert.equal(success.ok, true);
  assert.equal(success.message, '2개의 플래너를 삭제했습니다.');
  assert.deepEqual(withoutPlanners(planners, success.deletedIds), [{ id: 2 }]);

  const rejected = await runBulkDelete({
    plannerIds: [1, 99],
    bulkDelete: async () => {
      throw {
        response: {
          status: 400,
          data: { success: false, message: '본인 소유가 아니거나 존재하지 않는 플래너가 포함되어 있습니다.' },
        },
      };
    },
  });
  assert.equal(rejected.ok, false);
  assert.match(rejected.message, /존재하지 않는 플래너/);
  assert.deepEqual(withoutPlanners(planners, rejected.deletedIds), planners);

  const softFailure = await runBulkDelete({
    plannerIds: [2],
    bulkDelete: async () => ({ success: false, message: '선택삭제 실패' }),
  });
  assert.deepEqual(softFailure, { ok: false, deletedIds: [], message: '선택삭제 실패' });
});

test('T13 삭제 완료 후 선택 상태를 초기화한다', () => {
  const afterDelete = EMPTY_SELECTION;

  assert.equal(afterDelete.isSelecting, false);
  assert.deepEqual(afterDelete.selectedIds, []);
  assert.deepEqual(pruneSelection({ isSelecting: true, selectedIds: [1, 3] }, [2]).selectedIds, []);
});
