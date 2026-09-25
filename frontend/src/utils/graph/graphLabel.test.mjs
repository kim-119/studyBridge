// graphLabel 유틸 회귀 테스트(grapheme 단위 처리). 실행: node src/utils/graph/graphLabel.test.mjs
import {
  splitByGrapheme, countGraphemes, truncateByGrapheme, normalizeGraphLabel,
  getDisplayLabel, getTooltipLabel, getLabelVisibilityLevel, labelLimitForType,
} from './graphLabel.js';

let passed = 0; let failed = 0;
function ok(name, cond) {
  if (cond) { passed += 1; } else { failed += 1; console.error('  ✗', name); }
}
function eq(name, a, b) { ok(`${name} (got ${JSON.stringify(a)})`, a === b); }

// 한글 음절 = 1 grapheme.
eq('한글 분리 길이', splitByGrapheme('한글').length, 2);
eq('가나다 카운트', countGraphemes('가나다'), 3);
eq('빈문자 분리', splitByGrapheme('').length, 0);

// 절단: maxChars 초과 시 … 부착, 글자 보존.
eq('한글 절단', truncateByGrapheme('가나다라마', 3), '가나다…');
eq('짧으면 그대로', truncateByGrapheme('가나', 5), '가나');

// 이모지(ZWJ 결합) = 1 grapheme (Intl.Segmenter 환경 기준). 폴백이면 codepoint 분리되어 >1 일 수 있음.
const family = '👨‍👩‍👧';
ok('이모지 가족 1 grapheme(or fallback>=1)', countGraphemes(family) >= 1);
ok('이모지 절단 비파괴', truncateByGrapheme(`${family}가나`, 1).length > 0);

// 조합/이모지 섞여도 깨진 surrogate 가 남지 않음(끝이 lone surrogate 가 아님).
const cut = truncateByGrapheme('a👩‍🚀b', 2);
ok('절단 결과에 lone surrogate 없음', !/[\uD800-\uDBFF]$/.test(cut.replace('…', '')));

// 정규화: 개행/연속 공백 → 단일 공백 + trim.
eq('정규화 공백', normalizeGraphLabel('a\n  b \t c '), 'a b c');

// getDisplayLabel: 타입 한도 적용(concept=12) + 정규화.
const longConcept = getDisplayLabel('아주아주아주아주아주아주아주아주긴개념이름', { type: 'concept' });
ok('concept 표시 길이 <= 13(절단+…)', countGraphemes(longConcept) <= 13);
eq('maxChars 직접 지정', getDisplayLabel('가나다라마바', { maxChars: 2 }), '가나…');
eq('빈 입력 표시', getDisplayLabel('   ', { type: 'answer' }), '');

// 타입 한도 매핑.
eq('question 한도', labelLimitForType('question'), 22);
eq('알수없는 타입 default', labelLimitForType('zzz'), 12);

// 툴팁: 절단 안 함(상한 120 내).
eq('툴팁 전체 보존', getTooltipLabel('질문 전체 내용입니다'), '질문 전체 내용입니다');

// LOD 가시성.
ok('질문은 항상', getLabelVisibilityLevel(0.2, 0, 'question') === true);
ok('선택은 항상', getLabelVisibilityLevel(0.2, 0, 'concept', true) === true);
ok('저줌 저중요 답변 숨김', getLabelVisibilityLevel(0.4, 0.1, 'answer') === false);
ok('저줌 고중요 답변 표시', getLabelVisibilityLevel(0.4, 0.9, 'answer') === true);
ok('중줌 교수 표시', getLabelVisibilityLevel(0.7, 0, 'agent') === true);
ok('고줌 전체 표시', getLabelVisibilityLevel(1.5, 0, 'tag') === true);

console.log(`\ngraphLabel 테스트: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
