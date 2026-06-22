// ─────────────────────────────────────────────────────────────────────────────
// 픽셀 교수 sprite 정의 — asset 경로 / frame map / 상태머신 / 배치.
//   · sprite sheet 규격: 1280x640, 8 col x 4 row, frame 160x160, row-major, 32 frames.
//   · 절대 도메인(https://www.studybridge.co.kr/...) 하드코딩 금지 → /assets 상대경로만 사용.
//   · 답변 데이터/SSE schema와 무관한 "시각 표현용" 정의만 둔다(visual layer).
// ─────────────────────────────────────────────────────────────────────────────

export const FRAME_SIZE = 160;
export const SHEET_W = 1280;
export const SHEET_H = 640;

export const CLASSROOM_BG = '/assets/pixel/backgrounds/classroom_pixel_background.png';

export const PROFESSOR_SPRITE_SHEETS = {
  theory: '/assets/pixel/professors/professor_theory_brown_sheet.png',
  book: '/assets/pixel/professors/professor_book_brown_sheet.png',
  ai: '/assets/pixel/professors/professor_ai_black_sheet.png',
};

// 8x4 frame map (row-major). row=세로(0~3), col=가로(0~7).
export const FRAME = {
  IDLE_NEUTRAL: { row: 0, col: 0 },
  IDLE_BLINK: { row: 0, col: 1 },
  IDLE_BREATHE: { row: 0, col: 2 },
  IDLE_ATTENTIVE: { row: 0, col: 3 },
  TALK_OPEN: { row: 0, col: 4 },
  TALK_HALF: { row: 0, col: 5 },
  TALK_GESTURE: { row: 0, col: 6 },
  TALK_EMPHASIS: { row: 0, col: 7 },

  WALK_1: { row: 1, col: 0 },
  WALK_2: { row: 1, col: 1 },
  WALK_3: { row: 1, col: 2 },
  WALK_4: { row: 1, col: 3 },
  WALK_5: { row: 1, col: 4 },
  WALK_6: { row: 1, col: 5 },
  WALK_7: { row: 1, col: 6 },
  WALK_8: { row: 1, col: 7 },

  THINK_1: { row: 2, col: 0 },
  THINK_2: { row: 2, col: 1 },
  THINK_3: { row: 2, col: 2 },
  THINK_4: { row: 2, col: 3 },
  EXPLAIN_1: { row: 2, col: 4 },
  EXPLAIN_2: { row: 2, col: 5 },
  EXPLAIN_3: { row: 2, col: 6 },
  EXPLAIN_4: { row: 2, col: 7 },

  SELECTED: { row: 3, col: 0 },
  SURPRISED: { row: 3, col: 1 },
  VALIDATING: { row: 3, col: 2 },
  PEER_FEEDBACK: { row: 3, col: 3 },
  APPROVAL: { row: 3, col: 4 },
  COMPLETED: { row: 3, col: 5 },
  RETURNING: { row: 3, col: 6 },
  FINAL_IDLE: { row: 3, col: 7 },
};

const F = FRAME;

// visual state → 프레임 시퀀스 + tick 간격(ms). interval=0 또는 frames<=1 이면 정지(단일 프레임).
//   transient(ms): completed/error 처럼 잠깐 보여준 뒤 idle 로 자동 복귀해야 하는 상태.
export const STATE_ANIM = {
  idle: { frames: [F.IDLE_NEUTRAL, F.IDLE_BREATHE, F.IDLE_ATTENTIVE], interval: 650 },
  hovered: { frames: [F.IDLE_ATTENTIVE], interval: 0 },
  selected: { frames: [F.SELECTED], interval: 0 },
  walking_to_question: { frames: [F.WALK_1, F.WALK_2, F.WALK_3, F.WALK_4, F.WALK_5, F.WALK_6, F.WALK_7, F.WALK_8], interval: 120 },
  thinking: { frames: [F.THINK_1, F.THINK_2, F.THINK_3, F.THINK_4], interval: 240 },
  answering: { frames: [F.TALK_OPEN, F.TALK_HALF, F.TALK_GESTURE, F.TALK_EMPHASIS], interval: 170 },
  validating: { frames: [F.VALIDATING, F.THINK_4], interval: 280 },
  peer_feedback: { frames: [F.PEER_FEEDBACK, F.EXPLAIN_2], interval: 300 },
  returning: { frames: [F.WALK_1, F.WALK_2, F.WALK_3, F.WALK_4, F.WALK_5, F.WALK_6, F.WALK_7, F.WALK_8], interval: 120 },
  completed: { frames: [F.APPROVAL], interval: 0, transient: 800 },
  error: { frames: [F.SURPRISED], interval: 0, transient: 800 },
};

export const getStateAnim = (state) => STATE_ANIM[state] || STATE_ANIM.idle;

// 한 프레임(row,col) → background-position px (음수). 전체 sheet가 아닌 한 칸만 crop.
export const framePosition = (frame) => {
  const f = frame || F.IDLE_NEUTRAL;
  return `${-f.col * FRAME_SIZE}px ${-f.row * FRAME_SIZE}px`;
};

// 교수 3인 배치(역할 고정). side = 좌/중/우 (action menu/hover label 위치에 재사용).
//   · book(문헌)=왼쪽, theory(이론)=중앙, ai(AI)=오른쪽.
//   · left(%) + bottom(px) 은 inline, scale 은 side 클래스(CSS)로 줘서 반응형 축소 가능.
export const PROFESSORS = [
  { role: 'book', name: '문헌 교수', tagline: '자료 · 근거 · 보관함', sheet: PROFESSOR_SPRITE_SHEETS.book, side: 'left', pos: { left: 22, bottom: 70 } },
  { role: 'theory', name: '이론 교수', tagline: '검증 · 논리 · 냉철', sheet: PROFESSOR_SPRITE_SHEETS.theory, side: 'center', pos: { left: 50, bottom: 75 } },
  { role: 'ai', name: 'AI 교수', tagline: '친절 · 창의 · 설명', sheet: PROFESSOR_SPRITE_SHEETS.ai, side: 'right', pos: { left: 78, bottom: 70 } },
];

export const ROLE_NAMES = { theory: '이론 교수', book: '문헌 교수', ai: 'AI 교수' };

// SSE agentIndex → 역할. 명시 메타데이터가 없을 때의 결정적 fallback(첫=theory, 둘=book, 셋=ai).
export const AGENT_INDEX_TO_ROLE = ['theory', 'book', 'ai'];
export const roleForAgentIndex = (idx) => AGENT_INDEX_TO_ROLE[Math.max(0, Number(idx) || 0) % 3];

// 역할 → 기존 후속질문 target key(agent1/2/3) 및 agents 배열 인덱스.
export const ROLE_TO_TARGET_KEY = { theory: 'agent1', book: 'agent2', ai: 'agent3' };
export const ROLE_TO_AGENT_INDEX = { theory: 0, book: 1, ai: 2 };

// "애니메이션 진행 중"으로 보는 상태(선택 포즈가 덮어쓰지 않게 구분).
export const ACTIVE_VISUAL_STATES = new Set([
  'walking_to_question', 'thinking', 'answering', 'validating', 'peer_feedback', 'returning',
]);
