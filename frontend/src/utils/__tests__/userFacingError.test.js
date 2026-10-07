// node --test frontend/src/utils/__tests__
// 사용자 문구 매핑: 원본 axios/백엔드 오류 문자열이 사용자에게 그대로 노출되지 않는지.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  USER_FACING_MESSAGES, toUserFacingError, userFacingMessage, isGroupNotFoundError, isNetworkError, extractStatus,
} from '../userFacingError.js';

const axiosErr = (status, data, extra = {}) => Object.assign(new Error(status ? `Request failed with status code ${status}` : 'Network Error'), {
  isAxiosError: true,
  config: { url: '/api/x', method: 'post' },
  request: {},
  ...(status ? { response: { status, data } } : {}),
  ...extra,
});

const silent = { log: false };

test('401 → 로그인 만료 문구, 원본 axios 문자열은 노출되지 않는다', () => {
  const r = toUserFacingError(axiosErr(401, ''), silent);
  assert.equal(r.code, 'UNAUTHORIZED');
  assert.equal(r.message, '로그인 정보가 만료되었습니다. 다시 로그인해주세요.');
  assert.doesNotMatch(r.message, /Request failed|status code/i);
});

test('403 → 권한 문구', () => {
  const r = toUserFacingError(axiosErr(403, { status: 403, message: 'Forbidden' }), silent);
  assert.equal(r.code, 'FORBIDDEN');
  assert.equal(r.message, USER_FACING_MESSAGES.FORBIDDEN);
});

test('404 "Group study not found with ID: 106" → 스터디 정보를 찾을 수 없습니다 + groupNotFound 플래그', () => {
  const err = axiosErr(404, { status: 404, message: 'Group study not found with ID: 106' });
  assert.equal(isGroupNotFoundError(err), true);
  const r = toUserFacingError(err, silent);
  assert.equal(r.groupNotFound, true);
  assert.equal(r.code, 'GROUP_NOT_FOUND');
  assert.match(r.message, /^스터디 정보를 찾을 수 없습니다/);
  assert.doesNotMatch(r.message, /106|not found/i);
});

test('404 다른 리소스 → 일반 not-found 문구, context=group 이면 스터디 문구', () => {
  const err = axiosErr(404, { status: 404, message: 'Material not found with ID: 9' });
  assert.equal(isGroupNotFoundError(err), false);
  assert.equal(toUserFacingError(err, silent).code, 'NOT_FOUND');
  assert.equal(toUserFacingError(err, { ...silent, context: 'group' }).groupNotFound, true);
});

test('413/415 → 파일 크기/형식 문구', () => {
  assert.match(toUserFacingError(axiosErr(413, ''), silent).message, /파일 크기/);
  assert.match(toUserFacingError(axiosErr(415, ''), silent).message, /파일 형식/);
});

test('응답 없음(Network Error / ECONNABORTED timeout) → 네트워크 문구', () => {
  const net = axiosErr(null, null, { code: 'ERR_NETWORK' });
  assert.equal(isNetworkError(net), true);
  assert.equal(toUserFacingError(net, silent).code, 'NETWORK');
  const to = Object.assign(new Error('timeout of 60000ms exceeded'), { code: 'ECONNABORTED', config: {}, request: {} });
  assert.equal(toUserFacingError(to, silent).message, USER_FACING_MESSAGES.NETWORK);
});

test('5xx → 서버 오류 문구(서버 영문 메시지 노출 금지)', () => {
  const r = toUserFacingError(axiosErr(502, '<html>502 Bad Gateway</html>'), silent);
  assert.equal(r.code, 'SERVER');
  assert.doesNotMatch(r.message, /Bad Gateway/);
});

test('400/409 의 한국어 서버 안내는 그대로 전달, 영문/개발자 문자열은 fallback', () => {
  const ko = axiosErr(409, { status: 409, message: '진행 중인 퀴즈 세션이 있어 삭제할 수 없습니다.' });
  assert.equal(toUserFacingError(ko, silent).message, '진행 중인 퀴즈 세션이 있어 삭제할 수 없습니다.');
  const en = axiosErr(400, { status: 400, message: 'Required request part \'file\' is not present' });
  assert.equal(userFacingMessage(en, '업로드에 실패했습니다.', silent), '업로드에 실패했습니다.');
});

test('기본값: 알 수 없는 오류/문자열/undefined 도 generic 문구', () => {
  assert.equal(toUserFacingError(undefined, silent).message, USER_FACING_MESSAGES.GENERIC);
  assert.equal(toUserFacingError('boom', silent).message, USER_FACING_MESSAGES.GENERIC);
  assert.equal(userFacingMessage(new Error('x'), 'PDF 등록/퀴즈 생성에 실패했습니다.', silent), 'PDF 등록/퀴즈 생성에 실패했습니다.');
});

test('평면 {status,message} 객체(uploadProfileImage catch 가 던지는 response.data 형태)도 처리', () => {
  assert.equal(extractStatus({ status: 401, message: 'Unauthorized' }), 401);
  assert.equal(toUserFacingError({ status: 401, message: 'Unauthorized' }, silent).code, 'UNAUTHORIZED');
  assert.equal(toUserFacingError({ message: '프로필 이미지 업로드 실패' }, silent).message, '프로필 이미지 업로드 실패');
});

test('어떤 입력에도 "Request failed with status code" 가 사용자 문구로 새지 않는다', () => {
  for (const st of [400, 401, 403, 404, 409, 413, 415, 422, 500, 502, 503, 504]) {
    const m = userFacingMessage(axiosErr(st, null), undefined, silent);
    assert.doesNotMatch(m, /Request failed|status code|null|undefined/i, `status ${st}: ${m}`);
  }
});

test('log=true 기본값이면 console.error 로 원본을 남긴다', () => {
  const orig = console.error; const calls = [];
  console.error = (...a) => calls.push(a);
  try { toUserFacingError(axiosErr(401, '')); } finally { console.error = orig; }
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].status, 401);
});
