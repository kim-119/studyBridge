import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CARD_TARGET,
  buildJoinRequest,
  describeCardAction,
  describeGuestJoin,
  needsMembershipCheck,
  toCreatePayload,
  toGroupCard,
  validateCreateForm,
} from '../screens/groupstudy/groupStudyModel.js';

const LEADER_ID = 1;
const MEMBER_ID = 2;

const FULL_GROUP = {
  id: 11,
  title: '재무관리',
  isPublic: true,
  leaderId: LEADER_ID,
  currentCount: 10,
  capacity: 10,
  status: 'RECRUITING',
  studyType: 'GENERAL',
};

const VALID_FORM = {
  title: '알고리즘 스터디',
  tags: ['java'],
  description: '매주 백준 두 문제',
  startDate: '2026-10-01',
  endDate: '2026-12-31',
  capacity: 10,
  isPublic: true,
  studyType: 'CAM',
  targetStudyMinutes: 300,
  joinQuestionEnabled: true,
  joinQuestion: '  목표가 무엇인가요?  ',
  nicknameRuleEnabled: false,
  nicknameRule: '무시되어야 하는 문구',
};

test('카드는 서버 studyType을 그대로 쓰고, 값이 없으면 서버 기본값인 GENERAL로 본다', () => {
  assert.equal(toGroupCard(FULL_GROUP, MEMBER_ID).studyType, 'GENERAL');
  assert.equal(toGroupCard({ ...FULL_GROUP, studyType: 'CAM' }, MEMBER_ID).studyType, 'CAM');
  assert.equal(toGroupCard({ ...FULL_GROUP, studyType: undefined, hashtags: '캠스터디' }, MEMBER_ID).studyType, 'GENERAL');
});

test('정원이 찬 방도 가입 회원에게는 스터디룸 입장을 보여준다', () => {
  const card = toGroupCard(FULL_GROUP, MEMBER_ID);
  assert.deepEqual(describeCardAction(card, 'member'), { label: '스터디룸 입장', disabled: false, target: CARD_TARGET.ROOM });
});

test('정원이 찬 방에서 비회원에게만 정원 마감을 보여준다', () => {
  const card = toGroupCard(FULL_GROUP, 9);
  assert.deepEqual(describeCardAction(card, 'guest'), { label: '정원 마감', disabled: true, target: CARD_TARGET.DETAIL });
});

test('가입 여부를 아직 모르면 막지 않고 상세 화면에서 확인하게 한다', () => {
  const card = toGroupCard(FULL_GROUP, 9);
  assert.deepEqual(describeCardAction(card, undefined), { label: '상세 보기', disabled: false, target: CARD_TARGET.DETAIL });
});

test('방장 카드는 정원과 관계없이 내 스터디로 연다', () => {
  const card = toGroupCard(FULL_GROUP, LEADER_ID);
  assert.deepEqual(describeCardAction(card, 'guest'), { label: '내 스터디', disabled: false, target: CARD_TARGET.DETAIL });
});

test('비공개방 비회원에게는 서버 정책대로 초대 전용임을 알린다', () => {
  const card = toGroupCard({ ...FULL_GROUP, isPublic: false, currentCount: 3 }, 9);
  assert.deepEqual(describeCardAction(card, 'guest'), { label: '초대 전용', disabled: false, target: CARD_TARGET.DETAIL });
});

test('공개방 비회원은 참여하기로 상세 화면을 연다', () => {
  const card = toGroupCard({ ...FULL_GROUP, currentCount: 3 }, 9);
  assert.deepEqual(describeCardAction(card, 'guest'), { label: '참여하기', disabled: false, target: CARD_TARGET.DETAIL });
});

test('가입 여부 확인은 방장이 아닌 사용자의 만석 카드에만 필요하다', () => {
  assert.equal(needsMembershipCheck(toGroupCard(FULL_GROUP, MEMBER_ID)), true);
  assert.equal(needsMembershipCheck(toGroupCard(FULL_GROUP, LEADER_ID)), false);
  assert.equal(needsMembershipCheck(toGroupCard({ ...FULL_GROUP, currentCount: 3 }, MEMBER_ID)), false);
});

test('비회원 가입 화면 상태는 정원·공개 여부·질문·닉네임 정책을 구분한다', () => {
  assert.deepEqual(describeGuestJoin(FULL_GROUP), { mode: 'full' });
  assert.deepEqual(describeGuestJoin({ ...FULL_GROUP, currentCount: 3, isPublic: false }), { mode: 'inviteOnly' });
  assert.deepEqual(
    describeGuestJoin({
      ...FULL_GROUP,
      currentCount: 3,
      joinQuestionEnabled: true,
      joinQuestion: '목표는?',
      nicknameRuleEnabled: true,
      nicknameRule: '학교/학년/이름',
    }),
    { mode: 'open', joinQuestion: '목표는?', nicknameRule: '학교/학년/이름' }
  );
  assert.deepEqual(describeGuestJoin({ ...FULL_GROUP, currentCount: 3 }), { mode: 'open', joinQuestion: null, nicknameRule: null });
});

test('가입 요청은 켜진 정책의 답변과 닉네임만 담고, 빠지면 서버로 보내기 전에 막는다', () => {
  const group = { ...FULL_GROUP, currentCount: 3, joinQuestionEnabled: true, nicknameRuleEnabled: true };

  assert.deepEqual(buildJoinRequest(group, { joinAnswer: '', nickname: '도형' }), {
    error: '가입 질문에 대한 답변을 입력해주세요.',
  });
  assert.deepEqual(buildJoinRequest(group, { joinAnswer: ' 합격 ', nickname: ' 도형 ' }), {
    payload: { introduction: '공개 스터디 바로 참가', joinAnswer: '합격', nickname: '도형' },
  });
  assert.deepEqual(buildJoinRequest({ ...FULL_GROUP, currentCount: 3 }, { joinAnswer: '무시', nickname: '무시' }), {
    payload: { introduction: '공개 스터디 바로 참가' },
  });
});

test('생성 요청에 웹과 같은 운영 정책 필드를 담고, 꺼진 설정의 문구는 보내지 않는다', () => {
  const payload = toCreatePayload(VALID_FORM, null);

  assert.equal(payload.studyType, 'CAM');
  assert.equal(payload.targetStudyMinutes, 300);
  assert.equal(payload.joinQuestionEnabled, true);
  assert.equal(payload.joinQuestion, '목표가 무엇인가요?');
  assert.equal(payload.nicknameRuleEnabled, false);
  assert.equal('nicknameRule' in payload, false);
});

test('생성 폼은 서버와 같은 운영 정책 범위를 먼저 검사한다', () => {
  assert.deepEqual(validateCreateForm(VALID_FORM), {});
  assert.equal(
    validateCreateForm({ ...VALID_FORM, targetStudyMinutes: 200 }).settings,
    '하루 목표 공부시간은 4시간~10시간 중에서 선택해주세요.'
  );
  assert.equal(
    validateCreateForm({ ...VALID_FORM, joinQuestion: '   ' }).settings,
    '가입 질문을 사용하려면 질문 내용을 입력해주세요.'
  );
});
