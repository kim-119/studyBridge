import test from 'node:test';
import assert from 'node:assert/strict';
import {
  findButtonByText,
  importMobileModule,
  loadRenderer,
  registerComponentLoader,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

registerComponentLoader();

const { React } = await loadRenderer();
const { default: ParticipantsPanel } = await importMobileModule('screens/groupstudy/room/ParticipantsPanel.jsx');

const GROUP_ID = '24';
const LEADER_ID = 1;
const MEMBER_ID = 2;
const OTHER_ID = 3;

const SERVER_MEMBERS = [
  { userId: LEADER_ID, displayName: '고병준', role: 'LEADER', points: 0, recentStudyTimeSeconds: 6300, cumulativeStudyTimeSeconds: 17100 },
  { userId: MEMBER_ID, displayName: '김도형', role: 'MEMBER', points: 30, recentStudyTimeSeconds: 0, cumulativeStudyTimeSeconds: 38100 },
  { userId: OTHER_ID, displayName: '이서연', nickname: '서연', role: 'MEMBER', points: 5 },
];

function MembersHarness({ initialMembers, viewerId, onlineUserIds }) {
  const members = {
    data: initialMembers,
    isLoading: false,
    isError: false,
    isSuccess: true,
    reload: async () => initialMembers,
  };

  return React.createElement(ParticipantsPanel, {
    groupId: GROUP_ID,
    group: { id: Number(GROUP_ID), leaderId: LEADER_ID },
    members,
    isLeader: viewerId === LEADER_ID,
    userId: viewerId,
    onlineUserIds: new Set(onlineUserIds.map(String)),
    onClose: () => {},
  });
}

async function renderPanel({ viewerId, onlineUserIds = [], members = SERVER_MEMBERS }) {
  return renderElement(React.createElement(MembersHarness, { initialMembers: members, viewerId, onlineUserIds }));
}

function rowOf(renderer, userId) {
  return renderer.root.find(
    (instance) => instance.type === 'li' && instance.props['data-member-id'] === String(userId)
  );
}

function hasButtonIn(row, label) {
  return row.findAll((instance) => instance.type === 'button' && textOf(instance.children).includes(label)).length > 0;
}

test('멤버 카드에 역할 배지, 본인 표시, 획득 점수, 접속 상태를 보여준다', async () => {
  const renderer = await renderPanel({ viewerId: MEMBER_ID, onlineUserIds: [MEMBER_ID] });

  const leaderRow = textOf(rowOf(renderer, LEADER_ID).children);
  const myRow = textOf(rowOf(renderer, MEMBER_ID).children);
  const otherRow = textOf(rowOf(renderer, OTHER_ID).children);

  assert.match(leaderRow, /고병준/);
  assert.match(leaderRow, /방장/);
  assert.match(leaderRow, /획득 점수: 0점/);
  assert.match(leaderRow, /오프라인/);
  assert.match(leaderRow, /최근 공부 시간: 1시간 45분/);
  assert.match(leaderRow, /누적 공부 시간: 4시간 45분/);

  assert.match(myRow, /김도형/);
  assert.match(myRow, /\(나\)/);
  assert.match(myRow, /멤버/);
  assert.match(myRow, /획득 점수: 30점/);
  assert.match(myRow, /온라인/);
  assert.match(myRow, /최근 공부 시간: 0시간 0분/);
  assert.match(myRow, /누적 공부 시간: 10시간 35분/);

  assert.match(otherRow, /서연/);
  assert.match(otherRow, /획득 점수: 5점/);
  assert.match(otherRow, /최근 공부 시간: 0시간 0분/);
  assert.match(otherRow, /누적 공부 시간: 0시간 0분/);
});

test('일반 멤버에게는 점수 관리와 강제 퇴장 버튼이 보이지 않는다', async () => {
  const renderer = await renderPanel({ viewerId: MEMBER_ID });

  assert.equal(findButtonByText(renderer, '점수 관리'), null);
  assert.equal(findButtonByText(renderer, '강제 퇴장'), null);
});

test('방장에게도 점수 수정 버튼은 없고, 다른 멤버에게만 강제 퇴장이 보인다', async () => {
  const renderer = await renderPanel({ viewerId: LEADER_ID });

  assert.equal(findButtonByText(renderer, '점수 관리'), null);
  assert.equal(renderer.root.findAll((instance) => instance.type === 'input').length, 0);
  assert.equal(hasButtonIn(rowOf(renderer, LEADER_ID), '강제 퇴장'), false);
  assert.equal(hasButtonIn(rowOf(renderer, MEMBER_ID), '강제 퇴장'), true);
});

test('같은 userId 중복 행은 한 카드로만 보인다', async () => {
  const renderer = await renderPanel({
    viewerId: MEMBER_ID,
    members: [...SERVER_MEMBERS, { userId: LEADER_ID, displayName: '고병준', role: 'MEMBER', points: 0 }],
  });

  const leaderRows = renderer.root.findAll(
    (instance) => instance.type === 'li' && instance.props['data-member-id'] === String(LEADER_ID)
  );
  assert.equal(leaderRows.length, 1);
});
