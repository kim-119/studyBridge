/**
 * 학습 항목 노이즈 방어 (표시 전 2차 방어).
 * AI07/Spring을 거쳐도 이미 저장된 나쁜 데이터(표지 날짜·교수명·코스 제목 등)가 화면에 다시 보이는 것을 막는다.
 * 백엔드 LearningContentSanitizer 와 동일한 정책의 프론트 미러. 1차 방어는 Spring 저장 로직이다.
 *
 *   cleanLearningText("2026.04 조수연 Activity 생명주기") -> "Activity 생명주기"
 *   cleanLearningText("08. View Model")                   -> "View Model"
 *   isLearningNoise("2026.04 조수연")  -> true
 *   isLearningNoise("2026")            -> true
 */

const DATE_CORE = '20\\d{2}(?:\\s*[.\\-/]\\s*\\d{1,2}){0,2}';
const LEADING_SLIDE_NO = /^\s*\d{1,3}\s*[.)]\s+(?=\S)/;
// 토큰 경계로 끝나는 날짜 + (선택) 한글 이름 딱 한 토큰. 인명만 제거하고 내용어는 보존.
const LEADING_META = new RegExp('^\\s*' + DATE_CORE + '(?=\\s|$)(?:\\s+[가-힣]{2,4}(?=\\s|$))?\\s*');
const DATE_ONLY = new RegExp('^\\s*' + DATE_CORE + '\\s*$');
const DATE_AND_NAME_ONLY = new RegExp('^\\s*' + DATE_CORE + '(?:\\s+[가-힣]{2,4})+\\s*$');
const DIGITS_PUNCT_ONLY = /^[\d\s.,\-/_:;()[\]]+$/;
const TRAILING_YEAR = /\s*20\d{2}\s*$/;
// 표지/푸터형 코스 제목: 공백+연도로 끝나는 구. 자료 제목을 몰라도 노이즈로 본다. 예) "Modern Android Development 2026"
const ENDS_WITH_YEAR = /\s20\d{2}\s*$/;

export function cleanLearningText(raw) {
  if (raw == null) return '';
  let s = String(raw).trim();
  if (!s) return '';
  for (let i = 0; i < 2; i++) {
    const before = s;
    s = s.replace(LEADING_SLIDE_NO, '');
    s = s.replace(LEADING_META, '');
    s = s.trim();
    if (s === before) break;
  }
  return s.replace(/[\t ]{2,}/g, ' ').trim();
}

function normalizeTitle(s) {
  return String(s || '').trim().replace(TRAILING_YEAR, '').replace(/[\t ]{2,}/g, ' ').trim().toLowerCase();
}

export function isLearningNoise(raw, courseTitle = null) {
  if (raw == null) return true;
  const c = cleanLearningText(raw);
  if (!c || c.length < 2) return true;
  if (DATE_ONLY.test(c)) return true;
  if (DATE_AND_NAME_ONLY.test(c)) return true;
  if (DIGITS_PUNCT_ONLY.test(c)) return true;
  if (ENDS_WITH_YEAR.test(c)) return true; // "Modern Android Development 2026" 류 표지 제목
  if (courseTitle) {
    const a = normalizeTitle(c);
    const b = normalizeTitle(courseTitle);
    if (a && a === b) return true;
  }
  return false;
}

/** 정제 결과가 유효하면 그 값, 노이즈면 null. */
export function cleanLearningOrNull(raw, courseTitle = null) {
  return isLearningNoise(raw, courseTitle) ? null : cleanLearningText(raw);
}

/** 리스트 정제: 노이즈 제거 + 중복(대소문자 무시) 제거. */
export function filterLearningList(arr, courseTitle = null) {
  const out = [];
  const seen = new Set();
  (Array.isArray(arr) ? arr : []).forEach((item) => {
    if (isLearningNoise(item, courseTitle)) return;
    const c = cleanLearningText(item);
    const key = c.toLowerCase();
    if (!seen.has(key)) { seen.add(key); out.push(c); }
  });
  return out;
}
