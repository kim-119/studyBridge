// 사용자 UI 에 내보내는 오류 문구 중립화 — 모델명/URL/스택/내부 예외/컨텍스트 크기 같은 운영 metadata 를 노출하지 않는다(§23/§31).
const LEAK_RE = /(https?:\/\/|localhost|127\.0\.0\.1|traceback|exception|stack|ollama|qwen|llama|gpt-|num_ctx|token limit|context length|errno|econn|timeout of \d+|at [a-z_$][\w$]*\s*\(|\.py:\d+|\.java:\d+|null pointer|nullpointer)/i;
const RETRYABLE_CODES = new Set(['AI_UPSTREAM_UNAVAILABLE', 'AI_TOTAL_TIMEOUT', 'AI_STREAM_INTERNAL', 'LLM_TIMEOUT', 'LLM_CONNECTION', 'TURN_TIMEOUT', 'STREAM_ERROR', 'AGENT_ANSWER_MISSING']);

export const DEFAULT_AGENT_ERROR = '이 교수의 답변을 받지 못했어요. 다시 시도해 주세요.';
export const DEFAULT_STREAM_ERROR = 'AI 응답 생성 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.';

export function neutralizeErrorText(text, fallback = DEFAULT_STREAM_ERROR) {
  const s = String(text || '').trim();
  if (!s) return fallback;
  if (s.length > 240) return fallback;
  if (LEAK_RE.test(s)) return fallback;
  return s;
}

// 사용자 UX 에 반영하는 것은 degraded / retryable / failureCode 범주 정도만.
export function classifyFailure(data) {
  const code = String((data && (data.failureCode || data.code)) || '').toUpperCase();
  const retryable = data && typeof data.retryable === 'boolean' ? data.retryable : (code ? RETRYABLE_CODES.has(code) : true);
  const degraded = !!(data && data.degraded);
  let category = 'unknown';
  if (/TIMEOUT/.test(code)) category = 'timeout';
  else if (/UNAVAILABLE|CONNECTION|UPSTREAM/.test(code)) category = 'unavailable';
  else if (/CONTRACT|REJECTED|UNSUPPORTED|NOT_FOUND|NON_LEARNING/.test(code)) category = 'rejected';
  else if (code) category = 'generation';
  return { code: code || null, retryable, degraded, category };
}
