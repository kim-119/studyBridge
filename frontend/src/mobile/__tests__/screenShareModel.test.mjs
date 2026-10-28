import test from 'node:test';
import assert from 'node:assert/strict';
import { parseConnectionIdentity } from '../screens/groupstudy/connectionIdentity.js';
import {
  SHARE_PHASE,
  buildScreenShareStart,
  canStopShare,
  describeScreenShareError,
  describeSharePhase,
  isOwnScreenConnection,
  phaseFromNative,
  precheckScreenShare,
  screenClientInstanceId,
  stopNoticeFrom,
} from '../screens/groupstudy/screenShareModel.js';

const httpError = (status, data = {}) => ({ response: { status, data } });

test('사전 확인: 그룹 화면공유 2명이 차면 동의창을 띄우기 전에 막는다', () => {
  const full = {
    screenShareCount: 2,
    screenShareLimit: 2,
    connections: [
      { kind: 'SCREEN', userId: 3 },
      { kind: 'SCREEN', userId: 4 },
      { kind: 'PRIMARY', userId: 7 },
    ],
  };
  const result = precheckScreenShare(full, 7);
  assert.equal(result.ok, false);
  assert.match(result.message, /최대 2명/);

  assert.deepEqual(precheckScreenShare({ screenShareCount: 1, screenShareLimit: 2, connections: [] }, 7), {
    ok: true,
    limit: 2,
    count: 1,
  });
});

test('사전 확인: 내 다른 기기가 이미 공유 중이면 막는다(사용자당 1개)', () => {
  const result = precheckScreenShare({ screenShareCount: 1, screenShareLimit: 2, connections: [{ kind: 'SCREEN', userId: 7 }] }, '7');
  assert.equal(result.ok, false);
  assert.match(result.message, /다른 기기/);
});

test('네이티브 시작 인자: 서버 토큰·연결 id·웹과 같은 clientData(kind=SCREEN)', () => {
  const args = buildScreenShareStart({
    tokenResponse: { token: 'wss://h?sessionId=s&token=t', connectionId: 'con_scr', maxSendKbps: 2500 },
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    userId: 7,
    displayName: '김민서',
  });
  assert.equal(args.token, 'wss://h?sessionId=s&token=t');
  assert.equal(args.connectionId, 'con_scr');
  assert.deepEqual(JSON.parse(args.metadata), { userId: '7', clientData: '김민서', kind: 'SCREEN' });
  assert.equal(args.maxSendKbps, 2500);
  assert.equal(args.iceServers.length, 1);
  assert.throws(() => buildScreenShareStart({ tokenResponse: {} }));
});

test('clientInstanceId 는 서버 형식([A-Za-z0-9_-]{8,64})이다', () => {
  assert.match(screenClientInstanceId(), /^[A-Za-z0-9_-]{8,64}$/);
});

test('서버 오류 코드별 안내', () => {
  assert.match(
    describeScreenShareError(httpError(409, { code: 'SCREEN_SHARE_LIMIT_REACHED', message: '현재 화면공유 가능 인원(최대 2명)이 모두 사용 중입니다.' })),
    /최대 2명/
  );
  assert.match(describeScreenShareError(httpError(409, { code: 'PRIMARY_NOT_ACTIVE' })), /화상 연결이 활성화된 뒤/);
  assert.match(describeScreenShareError(httpError(409, { code: 'SCREEN_ALREADY_ACTIVE' })), /이미 화면을 공유/);
  assert.match(describeScreenShareError(httpError(403, { code: 'NOT_GROUP_MEMBER' })), /참여 멤버/);
  assert.match(describeScreenShareError({ code: 'CONSENT_REQUIRED', message: 'x' }), /동의가 만료/);
  assert.match(describeScreenShareError(httpError(503)), /일시적인 문제/);
});

test('네이티브 상태 → 화면 단계, 사용자가 직접 끈 경우는 안내하지 않는다', () => {
  assert.equal(phaseFromNative({ state: 'starting' }), SHARE_PHASE.CONNECTING);
  assert.equal(phaseFromNative({ state: 'publishing' }), SHARE_PHASE.PUBLISHING);
  assert.equal(phaseFromNative({ state: 'idle' }), SHARE_PHASE.IDLE);
  assert.equal(stopNoticeFrom({ state: 'idle', reason: 'user-stopped', message: '종료' }), null);
  assert.match(stopNoticeFrom({ state: 'idle', reason: 'network-lost', message: '네트워크 연결이 끊겨' }), /네트워크/);
  assert.equal(stopNoticeFrom({ state: 'publishing' }), null);
});

test('단계 안내와 중지 가능 여부', () => {
  assert.match(describeSharePhase(SHARE_PHASE.PUBLISHING), /다른 앱으로 이동해도/);
  assert.match(describeSharePhase(SHARE_PHASE.CONSENT), /전체 화면/);
  assert.equal(describeSharePhase(SHARE_PHASE.IDLE), null);
  assert.equal(canStopShare(SHARE_PHASE.PUBLISHING), true);
  assert.equal(canStopShare(SHARE_PHASE.CONSENT), false);
});

test('내 PRIMARY 소유 SCREEN 만 "내 화면공유"로 본다(다른 사람·다른 기기 공유는 수신)', () => {
  const server = (overrides) =>
    JSON.stringify({ v: 1, app: 'studybridge', groupId: 51, userId: 7, kind: 'SCREEN', ownerConnectionId: 'con_me', ...overrides });
  const mine = parseConnectionIdentity({ data: `{"clientData":"나"}%/%${server()}` });
  const otherDevice = parseConnectionIdentity({ data: `{"clientData":"나"}%/%${server({ ownerConnectionId: 'con_tablet' })}` });
  const camera = parseConnectionIdentity({ data: `{"clientData":"나"}%/%${server({ kind: 'PRIMARY', ownerConnectionId: null })}` });

  assert.equal(isOwnScreenConnection(mine, 'con_me'), true);
  assert.equal(isOwnScreenConnection(otherDevice, 'con_me'), false);
  assert.equal(isOwnScreenConnection(camera, 'con_me'), false);
  assert.equal(isOwnScreenConnection(mine, null), false);
});
