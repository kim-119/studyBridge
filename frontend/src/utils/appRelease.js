// /app 다운로드 페이지의 표시 정책(순수 함수 — node --test 로 검증).
//  · releaseNotes 는 GET /api/app/version 의 문자열 배열을 그대로 받는다. 원천은 S3 version.json 이고,
//    android-release.yml 은 android/release-notes.txt 가 없으면 "마지막 커밋 제목" 을 넣는다.
//  · 그래서 커밋/CI 형태의 개발용 문장은 사용자 업데이트 설명으로 보여 주지 않는다(패턴 분류로 판정, 특정 문장 하드코딩 없음).
//  · 문장을 새로 지어내거나 번역하지 않는다 — 남길지 숨길지만 결정한다.

export const RELEASE_NOTES_PLACEHOLDER = '업데이트 내역을 준비 중입니다.';

const MAX_NOTES = 8;
const MAX_NOTE_LENGTH = 240;
const MAX_TITLE_LENGTH = 30;

// Conventional Commits 헤더: "ci(android-release): …", "feat!: …", "fix: …"
const CONVENTIONAL_COMMIT = /^(feat|fix|chore|ci|cd|build|refactor|test|tests|docs|style|perf|revert|release|deps|hotfix|wip|ops)(\([^)]*\))?!?:/i;
// Git 이 만드는 자동 메시지: 머지/리버트/버전 범프
const VCS_GENERATED = /^(merge (pull request|branch|remote-tracking branch|tag)\b|revert\s+"|bump\s+(version|v?\d))/i;
// 커밋 트레일러와 CI 제어 마커
const COMMIT_TRAILER = /\b(signed-off-by|co-authored-by|change-id|reviewed-by):/i;
const CI_MARKER = /\[(skip ci|ci skip|no ci|skip actions)\]/i;
// 커밋 해시(숫자와 a-f 문자를 함께 포함한 7~40자리 hex 토큰)
const COMMIT_HASH = /\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b/i;
// 빌드·배포 파이프라인 내부 용어(사용자 기능 설명에는 나오지 않는 단어)
const PIPELINE_TERMS = /\b(ci\/cd|github actions?|workflows?|pipelines?|gradle|versioncode|keystore|apksigner|aapt2?|auto-publish(ing)?|auto-increment(ing)?)\b/i;
// 마크업처럼 보이는 문자열(정상 노트가 아님 — 렌더 자체는 React 가 이스케이프한다)
const MARKUP = /<\/?[a-z!][^>]*>/i;

// 제어문자(줄바꿈 포함)는 공백으로, 양방향 재정렬·폭 없는 문자는 제거(화면 깨짐/스푸핑 방지)
const CONTROL = /[\u0000-\u001F\u007F-\u009F]/g;
const INVISIBLE = /[\u200B-\u200F\u202A-\u202E\u2060-\u2069\uFEFF]/g;
// 작성자가 붙인 목록 기호/번호("- ", "• ", "1. ", "① ")는 화면이 번호를 매기므로 뗀다
const LEADING_BULLET = /^(?:[-*\u2022\u00B7\u25AA\u25E6\u2023]+|\d{1,2}[.)]|[\u2460-\u2473])\s*/;

export function isDeveloperNote(text) {
  return CONVENTIONAL_COMMIT.test(text)
    || VCS_GENERATED.test(text)
    || COMMIT_TRAILER.test(text)
    || CI_MARKER.test(text)
    || COMMIT_HASH.test(text)
    || PIPELINE_TERMS.test(text);
}

function cleanNote(value) {
  if (typeof value !== 'string') return '';
  const text = value.replace(INVISIBLE, '').replace(CONTROL, ' ').replace(/\s+/g, ' ').trim().replace(LEADING_BULLET, '').trim();
  if (text.length <= MAX_NOTE_LENGTH) return text;
  return `${text.slice(0, MAX_NOTE_LENGTH - 1).trimEnd()}…`;
}

// "화면공유 개선: PC에서 공유한 화면을 …" → { title, body }. 구분자가 없으면 본문만 있는 항목.
function splitTitle(text) {
  const idx = text.indexOf(': ');
  if (idx >= 2 && idx <= MAX_TITLE_LENGTH) {
    const title = text.slice(0, idx).trim();
    const body = text.slice(idx + 2).trim();
    if (title && body && !/https?:\/\//i.test(title)) return { title, body };
  }
  return { title: null, body: text };
}

/**
 * API releaseNotes → 화면에 보일 항목 배열 [{ title, body }].
 * 배열이 아니면(누락/null/문자열 이외) 빈 배열, 문자열 하나면 한 항목으로 취급한다(구버전 메타데이터 호환).
 */
export function toUserReleaseNotes(raw) {
  const list = typeof raw === 'string' ? [raw] : Array.isArray(raw) ? raw : [];
  const seen = new Set();
  const notes = [];
  for (const item of list) {
    const text = cleanNote(item);
    if (!text || MARKUP.test(text) || isDeveloperNote(text)) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    notes.push(splitTitle(text));
    if (notes.length >= MAX_NOTES) break;
  }
  return notes;
}

/** "2026-10-27T17:56:41+09:00" → "2026년 10월 27일" (서비스 기준 시간대 KST). 해석 불가면 null. */
export function formatReleaseDate(iso) {
  if (typeof iso !== 'string' || !iso.trim()) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric' });
}

/** 18019588 → "17.2 MB". 양의 정수가 아니면 null. */
export function formatFileSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return null;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** 다운로드 링크는 http(s) 절대/상대 경로만 허용한다(javascript: 등 스킴 차단). */
export function safeDownloadUrl(url) {
  if (typeof url !== 'string') return null;
  const u = url.trim();
  return /^https?:\/\//i.test(u) || /^\/(?!\/)/.test(u) ? u : null;
}
