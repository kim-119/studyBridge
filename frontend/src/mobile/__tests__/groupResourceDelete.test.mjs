import test from 'node:test';
import assert from 'node:assert/strict';
import {
  RESOURCE_KIND,
  describeDeleteFailure,
  shouldReloadAfterDeleteFailure,
} from '../screens/groupstudy/resourceDeleteModel.js';

function httpError(status, message) {
  return { response: { status, data: message ? { message } : {} } };
}

test('일반 회원이 직접 삭제하면 서버 403 을 방장 전용 안내로 보여준다', () => {
  assert.equal(describeDeleteFailure(httpError(403), RESOURCE_KIND.MATERIAL), '방장만 삭제할 수 있습니다.');
});

test('다른 방 자료 우회 삭제의 404 는 이 방 항목이 아니라고 안내하고 목록을 새로 고친다', () => {
  const crossGroup = httpError(404);

  assert.equal(describeDeleteFailure(crossGroup, RESOURCE_KIND.QUIZ), '이미 삭제되었거나 이 방의 항목이 아닙니다.');
  assert.equal(shouldReloadAfterDeleteFailure(crossGroup), true);
  assert.equal(shouldReloadAfterDeleteFailure(httpError(403)), false);
});

test('진행 중 세션 409 는 서버 메시지를 우선한다', () => {
  assert.equal(describeDeleteFailure(httpError(409, '세션 진행 중'), RESOURCE_KIND.QUIZ), '세션 진행 중');
  assert.equal(describeDeleteFailure(httpError(409), RESOURCE_KIND.QUIZ), '진행 중인 퀴즈 세션이 있어 삭제할 수 없습니다.');
});

test('네트워크 오류는 종류별 기본 문구를 쓴다', () => {
  assert.match(describeDeleteFailure(new Error('Network Error'), RESOURCE_KIND.MATERIAL), /자료 삭제에 실패/);
  assert.match(describeDeleteFailure(new Error('Network Error'), RESOURCE_KIND.QUIZ), /퀴즈 삭제에 실패/);
});
