import test from 'node:test';
import assert from 'node:assert/strict';
import { AGENT_COLOR_PALETTE } from '../../utils/agentColor.js';
import {
  UNASSIGNED_AGENT_KEY,
  agentPaletteForName,
  agentPaletteForSlot,
  groupAnswersByAgent,
  identityOfMessage,
  identityOfStage,
  latestTurnAnswerEntries,
  resolveAnswerAgent,
} from '../screens/studymate/agentAnswers.js';

const roomAgents = [
  { id: 11, name: '이론 교수', role: '정확한 개념 설명자' },
  { id: 12, name: '문헌 교수', role: '쉬운 설명 튜터' },
  { id: 13, name: 'AI 교수', role: '비판적 학습 코치' },
];

function answer(id, agent, content, extra = {}) {
  return { id, sender: 'AI', senderName: agent.name, agentId: agent.id, content, parentId: 'q2', ...extra };
}

test('방 교수는 방 배열 순서대로 서로 다른 색을 받는다', () => {
  const palettes = roomAgents.map((agent) => resolveAnswerAgent(identityOfMessage(answer(agent.id, agent, 'x')), roomAgents).palette);
  assert.deepEqual(palettes, [AGENT_COLOR_PALETTE[0], AGENT_COLOR_PALETTE[1], AGENT_COLOR_PALETTE[2]]);
  assert.equal(new Set(palettes.map((palette) => palette.border)).size, 3);
});

test('같은 교수는 agentId, 이름, 슬롯 어느 경로로 와도 같은 색과 키를 받는다', () => {
  const byId = resolveAnswerAgent({ agentId: '12' }, roomAgents);
  const byName = resolveAnswerAgent({ agentName: '문헌 교수' }, roomAgents);
  const bySlot = resolveAnswerAgent({ agentSlot: 1 }, roomAgents);
  assert.equal(byId.key, 'agent-12');
  assert.equal(byName.key, byId.key);
  assert.equal(bySlot.key, byId.key);
  assert.equal(byName.palette, byId.palette);
  assert.equal(byId.name, '문헌 교수');
  assert.equal(byId.roleText, '쉬운 설명 튜터');
});

test('슬롯 색은 팔레트 길이를 넘어가면 순환한다', () => {
  assert.equal(agentPaletteForSlot(AGENT_COLOR_PALETTE.length), AGENT_COLOR_PALETTE[0]);
  assert.equal(agentPaletteForSlot(-3), AGENT_COLOR_PALETTE[0]);
});

test('방에 없는 에이전트는 이름 해시로 결정적인 색을 받는다', () => {
  const first = resolveAnswerAgent({ agentName: '게스트 교수' }, roomAgents);
  const second = resolveAnswerAgent({ agentName: '게스트 교수' }, roomAgents);
  assert.equal(first.slot, -1);
  assert.equal(first.key, 'name-게스트 교수');
  assert.equal(first.palette, agentPaletteForName('게스트 교수'));
  assert.equal(second.palette, first.palette);
});

test('식별 정보가 전혀 없으면 에이전트로 취급하지 않는다', () => {
  assert.equal(resolveAnswerAgent({}, roomAgents), null);
  assert.equal(resolveAnswerAgent(identityOfStage({ stageType: 'TOPIC' }), roomAgents), null);
});

test('토론 단계의 1-based agentIndex 는 방 교수로 해석된다', () => {
  const agent = resolveAnswerAgent(identityOfStage({ agentIndex: 3, stageType: 'REBUTTAL' }), roomAgents);
  assert.equal(agent.key, 'agent-13');
  assert.equal(agent.palette, AGENT_COLOR_PALETTE[2]);
});

test('세 교수가 답하면 세 그룹이 첫 등장 순서대로 만들어진다', () => {
  const messages = [
    { id: 'q1', sender: 'USER', content: '이전 질문' },
    answer('old', roomAgents[0], '이전 답변', { parentId: 'q1' }),
    { id: 'q2', sender: 'USER', content: '새 질문' },
    answer('a2', roomAgents[1], '문헌 답변'),
    answer('a1', roomAgents[0], '이론 답변'),
    answer('a3', roomAgents[2], 'AI 답변'),
    answer('a1b', roomAgents[0], '이론 보충', { actType: 'REACTION' }),
  ];
  const groups = groupAnswersByAgent(latestTurnAnswerEntries(messages), roomAgents);
  assert.deepEqual(groups.map((group) => group.key), ['agent-12', 'agent-11', 'agent-13']);
  assert.deepEqual(groups[1].entries.map((entry) => entry.content), ['이론 답변', '이론 보충']);
  assert.equal(new Set(groups.map((group) => group.agent.palette.border)).size, 3);
});

test('구조화 턴의 단계는 단계별 에이전트로 묶이고 식별 불가 단계는 공통 그룹에 남는다', () => {
  const messages = [
    { id: 'q2', sender: 'USER', content: '토론 주제' },
    {
      id: 'q2::debate',
      sender: 'AI',
      turnKind: 'debate',
      stages: [
        { stageType: 'TOPIC', title: '논제', content: '논제 내용' },
        { stageType: 'OPENING_STATEMENT', title: '찬성측 입론', agentId: 11, agentName: '이론 교수', content: '찬성' },
        { stageType: 'OPENING_STATEMENT', title: '반대측 입론', agentId: 12, agentName: '문헌 교수', content: '반대' },
      ],
    },
  ];
  const groups = groupAnswersByAgent(latestTurnAnswerEntries(messages), roomAgents);
  assert.deepEqual(groups.map((group) => group.key), [UNASSIGNED_AGENT_KEY, 'agent-11', 'agent-12']);
  assert.equal(groups[0].agent, null);
});

test('최근 턴 답변에서 알림 메시지와 빈 답변은 제외된다', () => {
  const messages = [
    { id: 'q2', sender: 'USER', content: '질문' },
    { id: 'n1', sender: 'AI', senderName: '안내', content: '연결 중', isNotice: true },
    answer('empty', roomAgents[0], '   '),
    answer('a2', roomAgents[1], '> 💬 보충·반박\n\n본문'),
  ];
  const entries = latestTurnAnswerEntries(messages);
  assert.deepEqual(entries.map((entry) => entry.content), ['본문']);
});

test('토론 최종 결론(합의)은 특정 에이전트로 귀속하지 않는다', async () => {
  const { identityOfStage, identityOfMessage, isConsensusSpeech, resolveAnswerAgent } = await import('../screens/studymate/agentAnswers.js');
  const roomAgents = [{ agentId: 1, name: '김교수' }];

  assert.equal(isConsensusSpeech({ stageType: 'DEBATE_FINAL_CONCLUSION', agentName: '김교수' }), true);
  assert.equal(isConsensusSpeech({ speechType: 'FINAL_CONCLUSION' }), true);
  assert.equal(isConsensusSpeech({ agentId: 'debate-consensus', agentName: '최종 결론 (합의)' }), true);
  assert.equal(isConsensusSpeech({ stageType: 'OPENING', agentId: 1 }), false);
  assert.equal(resolveAnswerAgent(identityOfStage({ stageType: 'DEBATE_FINAL_CONCLUSION', agentId: 1, agentName: '김교수' }), roomAgents), null);
  assert.equal(resolveAnswerAgent(identityOfMessage({ agentId: 'debate-consensus', senderName: '최종 결론 (합의)' }), roomAgents), null);
});
