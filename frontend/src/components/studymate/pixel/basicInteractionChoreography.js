// ─────────────────────────────────────────────────────────────────────────────
// 기본 모드(basic) 교수 상호작용 안무 정의 — "시각 표현용" 데이터/헬퍼만 둔다.
//   · 답변 데이터/SSE schema/채팅 메시지 배열과 절대 무관(presentation only).
//   · 백엔드가 professor_motion / agent_answer 같은 권위 있는 이벤트를 주면
//     아래 타임드 폴백(FALLBACK_PHASES)은 양보한다(StudyMate.sendMessage에서 게이팅).
//   · 여기서 상태(useState)를 들고 있지 않는다. 렌더는 PixelProfessorStage/Sprite가,
//     상태 보유/타이머는 StudyMate.jsx가 담당한다.
// ─────────────────────────────────────────────────────────────────────────────

// 짧은 인사/잡담 휴리스틱. true면 과한 피드백 구조(반박/검증)를 만들지 않는다.
export const isCasualShortInput = (message) => {
  const s = String(message || '').trim();
  return s.length <= 12 && /^(안녕|하이|ㅎㅇ|뭐야|왜|ㅇㅇ|그래|아니|오케이|ok|hello|hi)/i.test(s);
};

// 답변 본문 → 말풍선용 짧은 문구(기본 55자). 본문 전체를 말풍선에 넣지 않는다.
export const makeBubbleText = (content, max = 55) => {
  const s = String(content || '').replace(/\s+/g, ' ').trim();
  return s.length > max ? `${s.slice(0, max)}…` : s;
};

// bubble kind 별 자동 제거 시간(ms). 0이면 다음 단계가 덮어쓸 때까지 유지.
export const BUBBLE_TTL = {
  thinking: 0,
  answer: 5000,
  evidence: 5000,
  feedback: 6000,
  rebuttal: 6000,
  done: 1200,
};

// 완료 말풍선 제거 후 stage 안내문구를 idle로 되돌리기까지의 지연(ms).
export const COMPLETED_HOLD_MS = 1100;

// Phase A — 질문 전송 직후. 교수 3명 전체 thinking.
export const PHASE_A = {
  message: '교수님들이 질문을 읽고 있어요...',
  states: { theory: 'thinking', book: 'thinking', ai: 'thinking' },
  bubbles: {
    theory: { text: '핵심 개념을 파악 중입니다.', kind: 'thinking' },
    book: { text: '근거를 확인할 준비 중입니다.', kind: 'thinking' },
    ai: { text: '쉽게 설명할 방식을 생각 중입니다.', kind: 'thinking' },
  },
};

// Phase B~E — 타임드 폴백(SSE 실답변이 없을 때만 role 상태/말풍선을 진행).
//   at(ms): 질문 전송 시점 기준 상대 시각. message는 항상 진행(완료 전까지).
export const FALLBACK_PHASES = [
  {
    at: 750,
    message: '이론 교수님이 1차 구조를 잡고 있어요.',
    states: { theory: 'answering', book: 'thinking', ai: 'thinking' },
    bubbles: { theory: { text: '먼저 개념 구조를 잡겠습니다.', kind: 'answer' } },
  },
  {
    at: 1600,
    message: '문헌 교수님이 근거와 보완점을 확인하고 있어요.',
    states: { theory: 'validating', book: 'answering', ai: 'thinking' },
    bubbles: { book: { text: '근거가 필요한 부분을 보강하겠습니다.', kind: 'evidence' } },
  },
  {
    at: 2500,
    message: 'AI 교수님이 이해하기 쉽게 풀어쓰고 있어요.',
    states: { theory: 'thinking', book: 'validating', ai: 'answering' },
    bubbles: { ai: { text: '쉽게 말하면 이렇게 정리할 수 있어요.', kind: 'answer' } },
  },
  {
    at: 3500,
    message: '교수님들이 서로 답변을 검토하고 있어요.',
    states: { theory: 'peer_feedback', book: 'peer_feedback', ai: 'validating' },
    bubbles: {
      theory: { text: '논리 전제를 다시 확인해야 합니다.', kind: 'feedback', targetRole: 'ai' },
      book: { text: '근거가 약한 표현은 줄이는 게 좋습니다.', kind: 'feedback', targetRole: 'theory' },
      ai: { text: '표현을 더 쉽게 다듬겠습니다.', kind: 'feedback', targetRole: 'user' },
    },
  },
];

// Phase F — 완료. all_complete 직후 잠깐 보여주고 idle로 복귀(stage가 800ms 후 idle).
export const COMPLETED_PHASE = {
  message: '교수님들의 답변과 피드백이 정리됐어요.',
  bubbles: {
    theory: { text: '논리 검토 완료.', kind: 'done' },
    book: { text: '근거 점검 완료.', kind: 'done' },
    ai: { text: '쉬운 설명 정리 완료.', kind: 'done' },
  },
};

// 짧은 인사/잡담 전용 — AI 교수만 가볍게 응답. 반박/검증 단계 없음.
export const CASUAL_PHASE = {
  message: '교수님들이 인사에 답하고 있어요.',
  states: { theory: 'thinking', book: 'idle', ai: 'answering' },
  bubbles: {
    ai: { text: '안녕하세요. 바로 도와드릴게요.', kind: 'answer' },
    theory: { text: '대화 시작이군요.', kind: 'thinking' },
  },
};
