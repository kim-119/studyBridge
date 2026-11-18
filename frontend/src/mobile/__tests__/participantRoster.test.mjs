import test from 'node:test';
import assert from 'node:assert/strict';
import { importMobileModule, registerComponentLoader } from './support/componentHarness.mjs';

registerComponentLoader();

const { buildParticipantRoster, formatStudyTime } = await importMobileModule(
  'screens/groupstudy/room/participantRoster.js'
);
const { countDistinctParticipants } = await importMobileModule('screens/groupstudy/participantTileModel.js');

const LEADER_ID = 1;
const MY_ID = 2;

function rosterOf(members, onlineUserIds = []) {
  return buildParticipantRoster({
    members,
    leaderId: LEADER_ID,
    userId: MY_ID,
    onlineUserIds: new Set(onlineUserIds.map(String)),
  });
}

test('같은 userId가 두 번 내려와도 한 명으로 합친다', () => {
  const roster = rosterOf([
    { userId: 1, displayName: '고병준', role: 'LEADER', points: 0 },
    { userId: 1, displayName: '고병준', role: 'MEMBER', points: 0 },
  ]);

  assert.equal(roster.length, 1);
  assert.equal(roster[0].isLeader, true);
});

test('이름이 같아도 userId가 다르면 서로 다른 멤버로 남긴다', () => {
  const roster = rosterOf([
    { userId: 1, displayName: '고병준', role: 'LEADER' },
    { userId: 3, displayName: '고병준', role: 'MEMBER' },
  ]);

  assert.deepEqual(
    roster.map((entry) => [entry.userId, entry.isLeader]),
    [
      [1, true],
      [3, false],
    ]
  );
});

test('방장 여부는 클라이언트 role이 아니라 그룹 leaderId로 정한다', () => {
  const roster = rosterOf([
    { userId: 1, displayName: '방장', role: 'MEMBER' },
    { userId: 4, displayName: '다른 사람', role: 'LEADER' },
  ]);

  assert.deepEqual(
    roster.map((entry) => [entry.userId, entry.isLeader]),
    [
      [1, true],
      [4, false],
    ]
  );
});

test('leaderId를 모르면 서버 role로 방장을 표시한다', () => {
  const roster = buildParticipantRoster({
    members: [{ userId: 5, displayName: '방장', role: 'LEADER' }],
    leaderId: undefined,
    userId: MY_ID,
    onlineUserIds: new Set(),
  });

  assert.equal(roster[0].isLeader, true);
});

test('그룹 닉네임이 있으면 닉네임을, 없으면 회원 이름을 보여준다', () => {
  const roster = rosterOf([
    { userId: 1, displayName: '고병준', nickname: '  양치빌런 ' },
    { userId: 2, displayName: '김도형', nickname: '' },
    { userId: 6, displayName: '' },
  ]);

  assert.deepEqual(
    roster.map((entry) => entry.name),
    ['양치빌런', '김도형', '이름 없음']
  );
});

test('점수·본인·접속 상태를 정규화한다', () => {
  const roster = rosterOf(
    [
      { userId: 1, displayName: '방장', points: 30 },
      { userId: 2, displayName: '나', points: null },
      { userId: 7, displayName: '오프라인 멤버', points: '12' },
    ],
    [1, 2]
  );

  assert.deepEqual(
    roster.map((entry) => [entry.userId, entry.points, entry.isMe, entry.isOnline]),
    [
      [1, 30, false, true],
      [2, 0, true, true],
      [7, 12, false, false],
    ]
  );
});

test('방장을 맨 위에, 그다음 온라인 멤버, 마지막에 오프라인 멤버를 둔다', () => {
  const roster = rosterOf(
    [
      { userId: 8, displayName: '오프라인' },
      { userId: 9, displayName: '온라인' },
      { userId: 1, displayName: '방장' },
      { userId: 2, displayName: '나' },
    ],
    [9, 2]
  );

  assert.deepEqual(
    roster.map((entry) => entry.userId),
    [1, 9, 2, 8]
  );
});

test('userId가 없는 행은 표시하지 않는다', () => {
  assert.equal(rosterOf([{ displayName: '식별자 없음' }, null]).length, 0);
});

test('참여 인원은 연결 수가 아니라 고유 회원 수로 센다', () => {
  const tiles = [
    { connectionId: 'local', userId: 2 },
    { connectionId: 'stale-own-connection', userId: '2' },
    { connectionId: 'c3', userId: 3 },
    { connectionId: 'c3-second-device', userId: 3 },
    { connectionId: 'ghost', userId: undefined },
  ];

  assert.equal(countDistinctParticipants(tiles), 3);
});

test('공부 시간은 웹 멤버 관리 화면과 같은 N시간 N분 형식으로 표시한다', () => {
  assert.equal(formatStudyTime(0), '0시간 0분');
  assert.equal(formatStudyTime(59), '0시간 0분');
  assert.equal(formatStudyTime(6300), '1시간 45분');
  assert.equal(formatStudyTime(38100), '10시간 35분');
  assert.equal(formatStudyTime(null), '0시간 0분');
  assert.equal(formatStudyTime(-5), '0시간 0분');
  assert.equal(formatStudyTime('abc'), '0시간 0분');
});

test('최근·누적 공부 시간은 서버 초 단위 값을 그대로 담는다', () => {
  const [entry] = rosterOf([
    { userId: 1, displayName: '고병준', recentStudyTimeSeconds: 6300, cumulativeStudyTimeSeconds: 17100 },
  ]);
  const [emptyEntry] = rosterOf([{ userId: 7, displayName: '신규' }]);

  assert.deepEqual([entry.recentStudySeconds, entry.cumulativeStudySeconds], [6300, 17100]);
  assert.deepEqual([emptyEntry.recentStudySeconds, emptyEntry.cumulativeStudySeconds], [0, 0]);
});
