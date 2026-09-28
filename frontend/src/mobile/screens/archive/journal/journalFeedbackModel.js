import { sanitizeList, sanitizeMarkdownText } from '../../../../utils/markdown.js';

export const FEEDBACK_SECTIONS = [
  { key: 'strengths', label: '장점' },
  { key: 'recommendations', label: '권장사항' },
  { key: 'concerns', label: '우려사항 / 비판적 개선점' },
  { key: 'nextActions', label: '다음 행동' },
];

const MIN_ITEMS_PER_SECTION = 8;

function parseJson(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function isStructuredFeedback(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  return Boolean(value.strengths || value.recommendations || value.concerns || value.summary || value.feedback_balance);
}

function plainFeedbackLines(raw, parsed) {
  const text = Array.isArray(parsed) ? parsed.map(String).join('\n') : String(raw);
  return sanitizeMarkdownText(text)
    .split(/\n+/)
    .map((line) => line.replace(/^\s*\d+[.)]\s*/, '').trim())
    .filter(Boolean);
}

export function parseJournalFeedback(raw) {
  if (!raw) return { structured: null, lines: [] };

  const parsed = typeof raw === 'string' ? parseJson(raw) : raw;
  if (isStructuredFeedback(parsed)) {
    return {
      structured: {
        summary: sanitizeMarkdownText(parsed.summary || ''),
        strengths: sanitizeList(parsed.strengths),
        recommendations: sanitizeList(parsed.recommendations),
        concerns: sanitizeList(parsed.concerns),
        nextActions: sanitizeList(parsed.next_actions || parsed.nextActions),
      },
      lines: [],
    };
  }

  return { structured: null, lines: plainFeedbackLines(raw, parsed) };
}

export function feedbackQualityWarning(structured) {
  if (!structured) return null;

  const hasOnlyStrengths =
    structured.strengths.length > 0 && structured.recommendations.length === 0 && structured.concerns.length === 0;
  if (hasOnlyStrengths) {
    return 'AI 피드백이 장점 위주로 생성되었습니다. 권장사항과 우려사항을 포함해 다시 생성해 주세요.';
  }

  const isInsufficient = ['strengths', 'recommendations', 'concerns'].some(
    (key) => structured[key].length < MIN_ITEMS_PER_SECTION
  );
  return isInsufficient ? 'AI 피드백이 충분하지 않습니다. 다시 생성해 주세요.' : null;
}
