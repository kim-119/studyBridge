import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_COVER_IMAGE_URL,
  VISIBILITY,
  addHashtag,
  buildConnectionData,
  countStudyDays,
  describeCardAction,
  describeConnection,
  describeMemberEvent,
  resolveMembership,
  selectVisibleGroups,
  splitChatHistory,
  toCreatePayload,
  validateCoverImageFile,
  validateCreateForm,
} from '../screens/groupstudy/groupStudyModel.js';

const VALID_FORM = {
  title: '알고리즘 스터디',
  tags: ['java', '코테'],
  description: '매주 백준 두 문제',
  startDate: '2026-10-01',
  endDate: '2026-12-31',
  capacity: 10,
  isPublic: false,
};

test('백엔드 CreateRequest 제약과 같은 기준으로 생성 폼을 검증한다', () => {
  assert.deepEqual(validateCreateForm(VALID_FORM), {});

  const errors = validateCreateForm({ ...VALID_FORM, title: ' ', description: '', startDate: '', capacity: 11 });
  assert.ok(errors.title);
  assert.ok(errors.description);
  assert.ok(errors.period);
  assert.match(errors.capacity, /최대 10명/);

  assert.match(validateCreateForm({ ...VALID_FORM, capacity: 1 }).capacity, /최소 2명/);
  assert.ok(validateCreateForm({ ...VALID_FORM, endDate: '2026-09-01' }).period);
});

test('생성 payload 는 필수 기간과 정수 정원, 쉼표 태그, 이미지 파일을 담는다', () => {
  const image = { name: 'cover.png' };
  const payload = toCreatePayload({ ...VALID_FORM, capacity: '4' }, image);

  assert.equal(payload.startDate, '2026-10-01');
  assert.equal(payload.endDate, '2026-12-31');
  assert.equal(payload.capacity, 4);
  assert.equal(payload.hashtags, 'java,코테');
  assert.equal(payload.isPublic, false);
  assert.equal(payload.image, image);
});

test('대표 이미지는 JPG/PNG/WEBP 5MB 이하만 허용한다', () => {
  assert.equal(validateCoverImageFile({ name: 'a.png', type: 'image/png', size: 1024 }), null);
  assert.equal(validateCoverImageFile({ name: 'a.WEBP', type: '', size: 1024 }), null);
  assert.match(validateCoverImageFile({ name: 'a.gif', type: 'image/gif', size: 1024 }), /JPG, PNG, WEBP/);
  assert.match(validateCoverImageFile({ name: 'a.jpg', type: 'image/jpeg', size: 6 * 1024 * 1024 }), /5MB/);
});

test('태그는 최대 3개까지 중복 없이 추가된다', () => {
  let tags = [];
  tags = addHashtag(tags, '#수다');
  tags = addHashtag(tags, '수다');
  tags = addHashtag(tags, '공부');
  tags = addHashtag(tags, '친목');
  tags = addHashtag(tags, '초과');
  assert.deepEqual(tags, ['수다', '공부', '친목']);
});

test('운영 기간 일수는 시작일과 종료일을 포함해 센다', () => {
  assert.equal(countStudyDays('2026-10-01', '2026-10-01'), 1);
  assert.equal(countStudyDays('2026-10-01', '2026-10-31'), 31);
  assert.equal(countStudyDays('2026-10-31', '2026-10-01'), null);
});

const GROUPS = [
  { id: 1, title: 'Java 알고리즘', hashtags: '#java #코테', isPublic: true, status: 'RECRUITING', currentCount: 5, capacity: 10, leaderId: 7 },
  { id: 2, title: '비밀 아지트', hashtags: '친목', isPublic: false, status: 'ACTIVE', currentCount: 10, capacity: 10, leaderId: 3 },
  { id: 3, title: '종료된 스터디', hashtags: '', isPublic: true, status: 'COMPLETED', currentCount: 2, capacity: 10 },
  { id: 4, title: '기계공학', hashtags: '열역학', isPublic: true, status: 'ACTIVE', currentCount: 10, capacity: 10, coverImageUrl: 'https://s3/cover.png' },
];

test('목록은 웹처럼 공개/비공개 탭과 진행 중 상태만 보여주고 최신순으로 정렬한다', () => {
  const publicCards = selectVisibleGroups(GROUPS, { userId: 7, visibility: VISIBILITY.PUBLIC, keyword: '' });
  assert.deepEqual(publicCards.map((card) => card.id), [4, 1]);

  const privateCards = selectVisibleGroups(GROUPS, { userId: 7, visibility: VISIBILITY.PRIVATE, keyword: '' });
  assert.deepEqual(privateCards.map((card) => card.id), [2]);
  assert.equal(privateCards[0].isPrivate, true);
});

test('검색은 제목 또는 태그로 걸러낸다', () => {
  const byTag = selectVisibleGroups(GROUPS, { userId: null, visibility: VISIBILITY.PUBLIC, keyword: '코테' });
  assert.deepEqual(byTag.map((card) => card.id), [1]);
});

test('커버 이미지가 없으면 웹 기본 이미지를 쓰고, 정원이 차면 마감 버튼을 보여준다', () => {
  const [full, mine] = selectVisibleGroups(GROUPS, { userId: 7, visibility: VISIBILITY.PUBLIC, keyword: '' });
  assert.equal(full.coverUrl, 'https://s3/cover.png');
  assert.equal(mine.coverUrl, DEFAULT_COVER_IMAGE_URL);
  assert.deepEqual(describeCardAction(full), { label: '정원 마감', disabled: true });
  assert.equal(describeCardAction(mine).label, '내 스터디');
});

test('멤버십은 방장, 가입 멤버, 비회원으로 구분한다', () => {
  const group = { leaderId: 7 };
  const members = [{ userId: 3 }];
  assert.equal(resolveMembership(group, members, '7'), 'leader');
  assert.equal(resolveMembership(group, members, '3'), 'member');
  assert.equal(resolveMembership(group, members, '9'), 'guest');
});

test('OpenVidu 연결 데이터는 웹과 같은 {userId, clientData} 형식이고 양방향으로 이름을 읽는다', () => {
  const data = JSON.parse(buildConnectionData('7', '김민서'));
  assert.deepEqual(data, { userId: '7', clientData: '김민서' });
  assert.deepEqual(describeConnection(data), { userId: '7', name: '김민서' });
  assert.equal(describeConnection({ name: '구버전' }).name, '구버전');
  assert.equal(describeConnection({}).name, null);
});

test('채팅 이력은 일반 채팅과 AI 대화로 나뉜다', () => {
  const { chat, ai } = splitChatHistory(
    [
      { id: 1, senderId: '7', senderName: '나', content: '안녕', isAi: false, isAiQuery: false },
      { id: 2, senderId: '7', senderName: '나', content: '질문', isAi: false, isAiQuery: true },
      { id: 3, senderId: 'ai', senderName: 'AI 튜터', content: '답변', isAi: true, isAiQuery: false },
    ],
    '7'
  );

  assert.deepEqual(chat.map((message) => message.content), ['안녕']);
  assert.deepEqual(ai.map((message) => [message.content, message.isUser]), [
    ['질문', true],
    ['답변', false],
  ]);
});

test('강퇴 이벤트가 나를 가리키면 방을 떠나고, 다른 사람이면 타일만 지운다', () => {
  assert.equal(describeMemberEvent({ type: 'PARTICIPANT_KICKED', targetUserId: 7 }, '7').kind, 'self-removed');
  assert.match(describeMemberEvent({ type: 'PARTICIPANT_KICKED', targetUserId: 7 }, '7').message, /강제 퇴장/);
  assert.deepEqual(describeMemberEvent({ type: 'PARTICIPANT_LEFT', targetUserId: 3 }, '7'), {
    kind: 'other-removed',
    targetUserId: 3,
  });
  assert.equal(describeMemberEvent({ type: 'MEMBER_JOINED', targetUserId: 3 }, '7').kind, 'ignore');
});
