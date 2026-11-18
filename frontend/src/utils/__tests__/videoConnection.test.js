// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CONNECTION_KIND,
  parseConnectionMetadata,
  getClientInstanceId,
  detectDeviceType,
  installEarlyLeaveGuard,
  purgeTombstonedConnections,
  planReconcile,
  deriveRoomPresence,
} from '../videoConnection.js';

const server = (o) => JSON.stringify({ v: 1, app: 'studybridge', groupId: 25, kind: 'PRIMARY', ownerConnectionId: null, instanceId: 'tab-aaaaaaaa', deviceType: 'WEB', issuedAt: 1, ...o });

test('serverData(마지막 세그먼트)가 신원, clientData 는 표시용', () => {
  const raw = `${JSON.stringify({ userId: 999, clientData: '김도형', avatarMode: 'emoji', avatarValue: '🦊' })}%/%${server({ userId: 8 })}`;
  const m = parseConnectionMetadata(raw);
  assert.equal(m.userId, 8); // clientData 의 999 를 무시
  assert.equal(m.verified, true);
  assert.equal(m.kind, CONNECTION_KIND.PRIMARY);
  assert.equal(m.name, '김도형');
  assert.equal(m.avatarValue, '🦊');
  assert.equal(m.deviceType, 'WEB');
});

test('clientData 안에 구분자를 넣어 serverData 를 위조해도 마지막(서버) 세그먼트가 이긴다', () => {
  const forged = `{"x":1}%/%${server({ userId: 1, kind: 'SCREEN' })}`;
  const raw = `${forged}%/%${server({ userId: 8, kind: 'PRIMARY' })}`;
  const m = parseConnectionMetadata(raw);
  assert.equal(m.userId, 8);
  assert.equal(m.kind, 'PRIMARY');
});

test('SCREEN 연결은 ownerConnectionId 로 같은 사용자에게 귀속된다', () => {
  const m = parseConnectionMetadata(`{"userId":8,"kind":"SCREEN"}%/%${server({ userId: 8, kind: 'SCREEN', ownerConnectionId: 'con_PC' })}`);
  assert.equal(m.kind, 'SCREEN');
  assert.equal(m.ownerConnectionId, 'con_PC');
});

test('레거시(serverData 없음) 연결은 clientData userId 를 비검증 값으로, kind 는 PRIMARY', () => {
  const m = parseConnectionMetadata(JSON.stringify({ userId: 8, clientData: '구버전', kind: 'SCREEN' }));
  assert.equal(m.verified, false);
  assert.equal(m.userId, 8);
  assert.equal(m.kind, 'PRIMARY'); // 비검증 clientData 의 kind 는 믿지 않는다
  assert.equal(parseConnectionMetadata('garbage').userId, null);
  assert.equal(parseConnectionMetadata(undefined).userKey, null);
});

test('clientData 없이 serverData 만 와도 파싱된다', () => {
  const m = parseConnectionMetadata(server({ userId: 55 }));
  assert.equal(m.userId, 55);
  assert.equal(m.verified, true);
});

test('탭 인스턴스 id 는 저장소에 유지되고, 저장소 오류에도 동작한다', () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const a = getClientInstanceId(storage);
  assert.match(a, /^[A-Za-z0-9_-]{8,64}$/);
  assert.equal(getClientInstanceId(storage), a); // 새로고침 = 같은 탭 = 같은 id
  const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.match(getClientInstanceId(broken), /^[A-Za-z0-9_-]{8,64}$/);
});

test('deviceType 분류', () => {
  assert.equal(detectDeviceType('Mozilla/5.0 (Linux; Android 9; SM-S908E) AppleWebKit/537.36 Chrome/129 Mobile Safari/537.36'), 'ANDROID');
  assert.equal(detectDeviceType('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'), 'IOS');
  assert.equal(detectDeviceType('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155'), 'WEB');
});

// 운영 OpenVidu 실측 순서(sbdiag 재현): participantLeft(A) → participantEvicted(A) → joinRoom 응답(existing=[A, O])
function fakeSession() {
  const s = {
    connection: undefined,
    remoteConnections: new Map(),
    remoteStreamsCreated: new Map(),
    leftCalls: [],
    evictedCalls: [],
    onParticipantLeft(ev) { this.leftCalls.push(ev.connectionId); },
    onParticipantEvicted(ev) { if (ev.connectionId === this.connection.connectionId) { /* original would leave */ } this.evictedCalls.push(ev.connectionId); },
  };
  return s;
}

test('join 응답 전에 도착한 Left/Evicted 는 tombstone 으로 기록되고 원본 TypeError 를 피한다', () => {
  const s = fakeSession();
  const guard = installEarlyLeaveGuard(s);
  s.onParticipantLeft({ connectionId: 'con_GHOST', reason: '' });
  assert.doesNotThrow(() => s.onParticipantEvicted({ connectionId: 'con_GHOST', reason: '' })); // 원본은 this.connection 미정 → TypeError
  assert.equal(guard.isTombstoned('con_GHOST'), true);
  assert.deepEqual(s.leftCalls, []);
  // join 응답 처리: 라이브러리가 ghost 를 기존 참가자로 만든다
  s.connection = { connectionId: 'con_ME' };
  s.remoteConnections.set('con_GHOST', { connectionId: 'con_GHOST', stream: { streamId: 'str_X' }, dispose() { this.disposed = true; } });
  s.remoteStreamsCreated.set('str_X', true);
  s.remoteConnections.set('con_O', { connectionId: 'con_O' });
  assert.deepEqual(purgeTombstonedConnections(s, guard.tombstones), ['con_GHOST']);
  assert.equal(s.remoteConnections.has('con_GHOST'), false);
  assert.equal(s.remoteStreamsCreated.has('str_X'), false);
  assert.equal(s.remoteConnections.has('con_O'), true);
  // join 이후의 정상 Left 는 원본으로 위임된다
  s.onParticipantLeft({ connectionId: 'con_O', reason: 'disconnect' });
  assert.deepEqual(s.leftCalls, ['con_O']);
});

test('reconcile: 서버에 없고 fetch 이전부터 알던 원격 연결만 제거(나/새 연결은 보존)', () => {
  const local = {
    con_ME: { isMe: true, connectedAt: 1 },
    con_GHOST: { connectedAt: 100 },
    con_ALIVE: { connectedAt: 100 },
    con_NEW: { connectedAt: 500 }, // fetch(300) 도중 생김 → 서버 목록에 없어도 유지
    con_MYSCREEN: { isMine: true, connectedAt: 1 },
  };
  assert.deepEqual(planReconcile(local, ['con_ME', 'con_ALIVE'], 300), ['con_GHOST']);
});

test('참여 인원 = PRIMARY 고유 userId(+나); 화면공유·두 번째 기기는 인원 증가 없음', () => {
  const conns = {
    con_ME: { userId: 8, kind: 'PRIMARY', isMe: true },
    con_ANDROID: { userId: 8, kind: 'PRIMARY' },            // 같은 사람 Android
    con_SCREEN: { userId: 8, kind: 'SCREEN', ownerConnectionId: 'con_ME' },
    con_B: { userId: 55, kind: 'PRIMARY' },
    con_LEGACY: { userId: null, kind: 'PRIMARY' },
  };
  const p = deriveRoomPresence(conns, 8);
  assert.equal(p.participantCount, 3); // 8, 55, 이름 없는 레거시 1
  assert.equal(p.primary.length, 4);
  assert.equal(p.screens.length, 1);
  const android = p.primary.find(([cid]) => cid === 'con_ANDROID')[1];
  assert.equal(android.multiDevice, true);
  assert.equal(p.primary.find(([cid]) => cid === 'con_B')[1].multiDevice, false);
  // 아직 접속 전(연결 0개)이어도 나는 1명으로 센다 — DB 회원 수를 쓰지 않는다
  assert.equal(deriveRoomPresence({}, 8).participantCount, 1);
});
