import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyMateType,
  buildCanonicalAgentPayload,
  buildCreateRoomPayload,
  findInvalidInstruction,
  makeDefaultAgents,
  mapPresetAgentToDraft,
  normalizeKnowledgeLevel,
  roomLimitForRole,
  suggestMateName,
} from '../screens/studymate/agentDrafts.js';
import { ROOM_PRESETS_BY_MODE } from '../screens/studymate/roomPresets.js';

test('기본 방은 기본 유형 3명으로 시작한다', () => {
  const drafts = makeDefaultAgents();
  assert.deepEqual(drafts.map((draft) => draft.agentPreset), ['정확 설명형', '쉬운 튜터형', '비판 코치형']);
  assert.deepEqual(drafts.map((draft) => draft.name), ['개념 정리 교수', '쉬운 풀이 튜터', '논점 검증 코치']);
});

test('방 생성 payload 는 모드별 설정만 싣고 에이전트를 정규화한다', () => {
  const payload = buildCreateRoomPayload({
    roomName: '  ',
    learningMode: 'debate',
    agentDrafts: makeDefaultAgents(),
    debateConfig: { debateStrength: 'deep' },
    socraticConfig: { questionIntensity: 'gentle', hintPolicy: 'step' },
    simulationConfig: { scenarioType: 'project' },
  });

  assert.equal(payload.roomName, '스터디 브릿지');
  assert.equal(payload.learningMode, 'debate');
  assert.deepEqual(payload.debateConfig, { debateStrength: 'deep' });
  assert.equal(payload.socraticConfig, null);
  assert.equal(payload.simulationConfig, null);
  assert.equal(payload.agents.length, 3);
});

test('에이전트 payload 는 웹과 같은 canonical 필드를 만든다', () => {
  const agent = buildCanonicalAgentPayload(mapPresetAgentToDraft(ROOM_PRESETS_BY_MODE.socratic[0].agents[1]));

  assert.equal(agent.name, '오개념 점검자');
  assert.equal(agent.personality, '솔직함');
  assert.equal(agent.personalityStyle, 'honest');
  assert.equal(typeof agent.temperature, 'number');
  assert.equal(agent.knowledgeLevel, 'MASTER');
  assert.equal(agent.knowledge_level, 'MASTER');
  assert.equal(agent.knowledgeLevelLabel, '석사 수준');
  assert.match(agent.persona, /^\[지식수준: MASTER\] \[성격: 솔직함\] /);
});

test('유형 선택은 사용자가 고친 이름을 덮어쓰지 않는다', () => {
  const drafts = makeDefaultAgents();
  drafts[0] = { ...drafts[0], name: '내 교수', nameEdited: true };

  const updated = applyMateType(drafts, 0, '냉철 분석형');
  assert.equal(updated[0].name, '내 교수');
  assert.equal(updated[0].personality, '냉소적');

  const renamed = applyMateType(makeDefaultAgents(), 2, '쉬운 튜터형');
  assert.equal(renamed[2].name, '친절한 개념 선생');
});

test('이름 후보가 모두 쓰이면 번호를 붙인다', () => {
  assert.equal(suggestMateName('냉철 분석형', ['냉철 분석관', '핵심 진단가', '구조 분석가']), '냉철 분석관 2');
});

test('추가 요청은 비우거나 5자 이상이어야 한다', () => {
  assert.equal(findInvalidInstruction([{ customInstruction: '' }, { customInstruction: '다섯 글자 이상' }]), undefined);
  assert.ok(findInvalidInstruction([{ customInstruction: '짧음' }]));
});

test('학습자 수준 입력은 enum 으로 정규화한다', () => {
  assert.equal(normalizeKnowledgeLevel('박사 수준'), 'DOCTOR');
  assert.equal(normalizeKnowledgeLevel('expert'), 'EXPERT');
  assert.equal(normalizeKnowledgeLevel(''), 'BACHELOR');
});

test('방 생성 한도는 역할별로 다르다', () => {
  assert.equal(roomLimitForRole('PREMIUM'), 10);
  assert.equal(roomLimitForRole(' admin '), 10);
  assert.equal(roomLimitForRole('USER'), 3);
  assert.equal(roomLimitForRole(undefined), 3);
});

test('모드별 추천 방 설정은 5개씩이다', () => {
  assert.equal(ROOM_PRESETS_BY_MODE.socratic.length, 5);
  assert.equal(ROOM_PRESETS_BY_MODE.debate.length, 5);
  assert.equal(ROOM_PRESETS_BY_MODE.simulation.length, 5);
});
