import { useCallback, useEffect, useRef, useState } from 'react';

// ─────────────────────────────────────────────────────────────────────────────
// 1분 단위 학습 흐름 요약 — 새 질문/답변이 있을 때만, 1분에 한 번 이하로 생성.
//   · LLM/API 호출 없음(frontend deterministic summarizer).
//   · 기존 SSE stream을 추가로 열지 않고, 답변 배열에 섞지 않는다(presentation only).
//   · refs는 이 훅을 호출하는 컴포넌트에 귀속 → 탭 전환으로 stage가 unmount돼도
//     훅을 부모(StudyMate)에서 호출하면 dedupe 상태가 유지되어 같은 요약이 반복되지 않는다.
// ─────────────────────────────────────────────────────────────────────────────

export const RECAP_MIN_INTERVAL_MS = 60 * 1000;

const PRIORITY_MARKERS = ['결론', '핵심', '추천', '정리', '따라서'];

// markdown/code/URL/로그성 잡음 제거 + 공백 정리.
function cleanText(input) {
  let t = String(input || '');
  t = t.replace(/```[\s\S]*?```/g, ' ');          // 코드 블록
  t = t.replace(/`[^`]*`/g, ' ');                  // 인라인 코드
  t = t.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ');     // 이미지
  t = t.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');   // 링크 → 텍스트만
  t = t.replace(/https?:\/\/\S+/g, ' ');           // URL
  t = t.replace(/^\s{0,3}([>#]+|[-*+]\s|\d+\.\s)/gm, ' '); // md 줄머리(인용/헤더/리스트)
  t = t.replace(/[*_~`#>|]/g, ' ');                // 잔여 md 토큰
  t = t.replace(/\s+/g, ' ').trim();               // 연속 공백
  return t;
}

// 문장 분리(한국어 종결부 고려, lookbehind 미사용으로 구버전 호환). 로그성 초장문은 제외.
function splitSentences(text) {
  return String(text || '')
    .split(/[\n.!?。…]+/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 4 && s.length <= 240);
}

function truncate(text, max) {
  const t = String(text || '').trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max).trim()}…`;
}

// 답변 핵심 한 문장: 우선 마커 포함 문장 → 없으면 첫 의미 문장.
function pickCore(answer, max) {
  const clean = cleanText(answer);
  const sentences = splitSentences(clean);
  if (sentences.length === 0) return truncate(clean, max);
  const prioritized = sentences.find((s) => PRIORITY_MARKERS.some((m) => s.includes(m)));
  return truncate(prioritized || sentences[0], max);
}

// 요약 대상 교수 추론(스펙 규칙).
export function inferRecapProfessor(question, answer) {
  const text = `${question || ''} ${answer || ''}`;
  if (/근거|자료|문헌|출처|보관함|PDF|논문|레퍼런스/.test(text)) return 'book';
  if (/검증|오류|논리|반박|냉철|정확|비판|테스트/.test(text)) return 'theory';
  return 'ai';
}

export function summarizeTurn(question, answer) {
  return {
    question: truncate(cleanText(question), 80),
    answer: pickCore(answer, 120),
    role: inferRecapProfessor(question, answer),
  };
}

// 문자열 → 안정적 해시(중복 콘텐츠 판별용).
function hashString(str) {
  let h = 0;
  const s = String(str || '');
  for (let i = 0; i < s.length; i += 1) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return String(h >>> 0);
}

// trigger: 스트림이 "완료될 때마다" 증가하는 값(예: 완료 타임스탬프).
//   · trigger 변화가 있을 때만 평가 → 과거 히스토리 로드만으로는 요약이 뜨지 않는다(QA #16).
//   · question/answer 는 trigger 시점의 최신 값을 closure로 읽는다.
export function useMinuteRecap({ question, answer, trigger }) {
  const [recap, setRecap] = useState(null);
  const lastKeyRef = useRef(null);
  const lastTimeRef = useRef(0);
  const lastTriggerRef = useRef(0);

  useEffect(() => {
    if (!trigger || trigger === lastTriggerRef.current) return; // 완료 이벤트가 있을 때만
    lastTriggerRef.current = trigger;
    const q = String(question || '').trim();
    const a = String(answer || '').trim();
    if (!q || !a) return;

    const key = hashString(`${q}${a}`);
    if (key === lastKeyRef.current) return; // 같은 질문/답변 → 새로 만들지 않음

    const now = Date.now();
    if (lastTimeRef.current && now - lastTimeRef.current < RECAP_MIN_INTERVAL_MS) {
      // 새 내용이지만 1분 이내 → 표시 생략(키만 소비해 1분에 한 번 이하 보장).
      lastKeyRef.current = key;
      return;
    }
    lastKeyRef.current = key;
    lastTimeRef.current = now;
    setRecap({ id: key, ...summarizeTurn(q, a) });
    // question/answer는 trigger 시점의 최신값을 closure로 사용(의도적 deps 제외).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);

  const dismissRecap = useCallback(() => setRecap(null), []);
  return { recap, dismissRecap };
}
