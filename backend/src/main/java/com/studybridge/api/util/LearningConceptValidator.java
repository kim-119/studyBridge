package com.studybridge.api.util;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "개념명(명사구)"과 "문장/예제/코드 조각"을 구분하는 결정적 검증기.
 *
 * <p>배경: AI07 로드맵 생성기는 PDF 본문 문장("주택면적은독립변수이고", "관측된데이터를통해…추정하는것")을
 * core_concepts 로 흘리고, 그 조각을 task 제목/objective 템플릿에 그대로 끼워 넣는다.
 * {@link LearningContentSanitizer}는 표지/날짜/교수명 메타데이터만 걸러내므로 이런 문장형 항목은 통과했다.
 * 이 클래스는 특정 도메인 문자열이 아니라 <b>형태적 신호</b>(서술어 어미·조사 밀도·길이·코드 기호·문장 부호·
 * task 와의 중복)로 판단해, 다른 예제 데이터에서도 동일하게 동작한다.
 *
 * <ul>
 *   <li>{@link #isConceptLike(String)}: 선행 개념/핵심 개념으로 쓸 수 있는 짧은 명사구인가.
 *   <li>{@link #split(Collection)}: 허용/거부 목록으로 분리.
 *   <li>{@link #scrub(String, Collection, String)}: 거부된 조각이 섞인 문장에서 조각을 주제어로 치환.
 *   <li>{@link #isNearDuplicate(String, String)}: task 제목·플래너 원문과 사실상 동일한지.
 *   <li>{@link #isRelated(String, Collection)}: 주제어/과목과 어휘적으로 연관되는지(폴백 선행개념 선별용).
 * </ul>
 */
public final class LearningConceptValidator {

    private LearningConceptValidator() {}

    /** 개념명 최대 길이(공백 제거 기준). 한국어 명사구는 보통 15자 이내, 영문 포함 여유. */
    public static final int MAX_CONCEPT_LENGTH = 40;
    /** 공백 없는 한글 연속 구간이 이 길이를 넘고 문법 신호가 하나라도 있으면 문장으로 본다. */
    private static final int LONG_HANGUL_RUN = 18;
    /** 공백으로 나뉜 토큰이 이 개수 이상이면 문장으로 본다. */
    private static final int MAX_WORDS = 5;

    // 문장 종결/연결 어미(끝부분). 명사로 끝나는 개념명("람다", "화면", "결과")을 오탐하지 않도록 어간 조건을 둔다.
    private static final Pattern PREDICATE_ENDING = Pattern.compile(
            "(?:(?:이|하|되|있|없|않|같|많|르|크|작|좋|겠|었|았|였|된|한|인|온|운|는|린|난)다"
            + "|(?:이|하|되|있|없|않|가|오|나|지)고"
            + "|(?:이|하|되|있|없)며"
            + "|(?:하|되|이|라|다|있|없|으)면"
            + "|(?:하|되)면서"
            + "|(?:하는|되는|있는|없는|않는|않은)것"
            + "|것|것들"
            + "|하기|되기|니다|세요|보세요|십시오|까|죠|네요|때문에|때문"
            + "|(?:을|를|은|는|에|에서|으로|까지|부터|처럼|보다|에게|한테|이란|란|이라고|라고|라도|이라도)"
            + ")$");

    // 문장 내부 조사(한글 사이에 낀 경우만 센다). 개념명에도 1개 정도는 흔함("모델의 성능", "독립변수와 종속변수").
    private static final Pattern INNER_PARTICLE = Pattern.compile(
            "(?<=[가-힣)\\p{Alnum}])(?:을|를|은|는|이|가|의|에|에서|로|으로|와|과|도|만|까지|부터|처럼|보다|에게)(?=[가-힣])");

    // 문장 내부 용언/관형형/연결형(도메인 무관한 문법 어휘). 하나만 있어도 문장성이 강하다.
    private static final Pattern INNER_VERB_FORM = Pattern.compile(
            "(?:하는|되는|있는|없는|않는|않은|하여|되어|해서|통해|따라|위해|대한|대해|가진|좋은|나쁜|높은|낮은|같은|많은|적은"
            + "|이용해|사용해|수록|하면|되면|라면|다면|이고|하고|되고|이며|하며|되며|중요한|필요한|가능한|다양한|유사한|불가능한"
            + "|간단한|복잡한|이라고|라고|했|됐|였|았|었|중에서|에서의|에대한|로부터|으로써|에의해|에따라|에따른|에대해)");

    // 코드/식 조각 신호
    private static final Pattern CODE_LIKE = Pattern.compile(
            "[=;{}\\[\\]<>]|\\w+_\\w*\\(|\\b(?:import|from|def|return|print|self|class)\\b");

    // 문장 부호로 끝남(마침표/물음표/느낌표/말줄임/콜론/쉼표)
    private static final Pattern SENTENCE_PUNCT_END = Pattern.compile("[.?!…:,]\\s*$");
    // 기호로 시작("~ 사이의값", "• 개념")
    private static final Pattern SYMBOL_START = Pattern.compile("^[^\\p{L}\\p{N}(\\[\"'“‘]");
    private static final Pattern GENERIC_DA_ENDING = Pattern.compile("[가-힣]다$");
    private static final Pattern PAREN_GROUP = Pattern.compile("\\(([^()]*)\\)");
    private static final Pattern HANGUL_RUN = Pattern.compile("[가-힣]+");
    private static final Pattern NON_WORD = Pattern.compile("[^\\p{L}\\p{N}]+");
    private static final Pattern ROADMAP_PREFIX = Pattern.compile("^\\s*\\[로드맵\\s+\\d+주차\\s+\\d+일\\]\\s*");
    private static final Pattern DAY_PREFIX = Pattern.compile("^\\s*\\d+\\s*일차\\s*[:\\-–~]?\\s*");
    private static final Pattern BULLET = Pattern.compile("\\s*[•·▪‣∙]\\s*");
    private static final Pattern MULTISPACE = Pattern.compile("[\\t ]{2,}");

    /** 허용(concept)·거부(fragment) 목록. 순서는 입력 순서를 유지하고 중복은 제거한다. */
    public record Split(List<String> accepted, List<String> rejected) {
        public boolean hasRejected() { return !rejected.isEmpty(); }
    }

    /**
     * 짧은 명사구(개념명)로 볼 수 있으면 true. 문장·설명문·예제 문장·코드 조각·task 문장은 false.
     * 도메인 단어 필터가 아니라 형태 신호만 사용한다.
     */
    public static boolean isConceptLike(String raw) {
        if (raw == null) return false;
        String s = LearningContentSanitizer.clean(raw);
        if (s.length() < 2) return false;
        if (SYMBOL_START.matcher(s).find()) return false;
        if (SENTENCE_PUNCT_END.matcher(s).find()) return false;
        if (CODE_LIKE.matcher(s).find()) return false;        // 식/코드 조각("pred = pipe.predict(X_test)")
        if (!balancedParens(s)) return false;                 // 잘린 코드/문장("accuracy_score(y_test")
        String compact = s.replace(" ", "");
        if (compact.length() > MAX_CONCEPT_LENGTH) return false;
        String[] words = s.trim().split("\\s+");
        if (words.length > MAX_WORDS) return false;
        for (String seg : segments(compact)) {
            if (PREDICATE_ENDING.matcher(seg).find()) return false;
            if (seg.length() >= 4 && GENERIC_DA_ENDING.matcher(seg).find()) return false;   // "…낮다", "…크다" 류 서술 종결
        }
        for (String w : words) if (w.length() >= 3 && PREDICATE_ENDING.matcher(w).find()) return false;
        int particles = count(INNER_PARTICLE, compact);
        int verbForms = count(INNER_VERB_FORM, compact);
        int grammarScore = particles + 2 * verbForms;
        if (grammarScore >= 3) return false;
        int longestRun = longestHangulRun(compact);
        if (longestRun > LONG_HANGUL_RUN && grammarScore >= 1) return false;
        return true;
    }

    /** 개념명 후보 목록을 허용/거부로 분리(정제·중복 제거 포함). */
    public static Split split(Collection<String> candidates) {
        List<String> ok = new ArrayList<>(), bad = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        if (candidates == null) return new Split(ok, bad);
        for (String c : candidates) {
            if (c == null || c.isBlank()) continue;
            String cleaned = LearningContentSanitizer.clean(c);
            if (cleaned.isEmpty() || !seen.add(normalize(cleaned))) continue;
            (isConceptLike(cleaned) ? ok : bad).add(cleaned);
        }
        return new Split(ok, bad);
    }

    /**
     * 문장 안에 섞인 거부 조각을 주제어로 치환한다(긴 조각부터). 조각 앞의 불릿("• ")도 함께 정리한다.
     * 조각이 없거나 replacement 가 비면 공백 정리만 수행한다.
     * 예) scrub("선형회귀의 • 관측된…추정하는것을(를) 코드 흐름 추적", ["관측된…추정하는것"], "고급 회귀 기법")
     *     = "선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적"
     */
    public static String scrub(String text, Collection<String> fragments, String replacement) {
        if (text == null) return null;
        String out = text;
        if (fragments != null && replacement != null && !replacement.isBlank()) {
            List<String> sorted = new ArrayList<>();
            for (String f : fragments) if (f != null && f.trim().length() >= 2) sorted.add(f.trim());
            sorted.sort(Comparator.comparingInt(String::length).reversed());
            for (String f : sorted) {
                // 조각 바로 앞 불릿/공백까지 한 덩어리로 치환해 "선형회귀의 • X" → "선형회귀의 고급 회귀 기법".
                // 조각은 공백 유무와 무관하게 매칭한다("데이터를서로…묶는것" ↔ "데이터를 서로 … 묶는 것").
                Pattern p = Pattern.compile("(?:\\s*[•·▪‣∙]\\s*|\\s*)" + lenient(f));
                Matcher m = p.matcher(out);
                StringBuilder sb = new StringBuilder();
                while (m.find()) {
                    // 앞 글자가 있으면(문자·숫자·콜론 등) 한 칸 띄우고, 문장 시작이나 여는 괄호/따옴표 뒤면 바로 붙인다.
                    boolean afterWord = m.start() > 0 && !Character.isWhitespace(out.charAt(m.start() - 1))
                            && "([{\"'“‘".indexOf(out.charAt(m.start() - 1)) < 0;
                    m.appendReplacement(sb, Matcher.quoteReplacement((afterWord ? " " : "") + replacement.trim()));
                }
                m.appendTail(sb);
                out = sb.toString();
            }
        }
        out = BULLET.matcher(out).replaceAll(" ");
        out = MULTISPACE.matcher(out).replaceAll(" ").trim();
        return out;
    }

    /** 조각을 공백 삽입에 무관하게 찾는 정규식 조각(문자마다 \\s* 허용). */
    static String lenient(String fragment) {
        StringBuilder sb = new StringBuilder();
        String compact = fragment.replaceAll("\\s+", "");
        for (int i = 0; i < compact.length(); i++) {
            if (i > 0) sb.append("\\s*");
            sb.append(Pattern.quote(String.valueOf(compact.charAt(i))));
        }
        return sb.toString();
    }

    /** 문장에 조각(공백 무시)이 들어 있는지. */
    public static boolean containsFragment(String text, String fragment) {
        if (text == null || fragment == null || fragment.isBlank()) return false;
        return Pattern.compile(lenient(fragment)).matcher(text).find();
    }

    /** 두 문자열이 사실상 동일(정규화 후 같거나, 짧은 쪽이 긴 쪽의 80% 이상을 차지하며 포함)하면 true. */
    public static boolean isNearDuplicate(String a, String b) {
        String x = normalize(a), y = normalize(b);
        if (x.isEmpty() || y.isEmpty()) return false;
        if (x.equals(y)) return true;
        String shortS = x.length() <= y.length() ? x : y, longS = x.length() <= y.length() ? y : x;
        return longS.contains(shortS) && shortS.length() >= Math.ceil(longS.length() * 0.8);
    }

    /** candidate 가 texts 중 하나와 사실상 동일하면 true. */
    public static boolean duplicatesAny(String candidate, Collection<String> texts) {
        if (texts == null) return false;
        for (String t : texts) if (isNearDuplicate(candidate, t)) return true;
        return false;
    }

    /**
     * 개념명이 anchors(주제어·과목·오늘의 개념)와 의미 있는 토큰(한글 2자+/영문 3자+)을 공유하면 true.
     * 폴백 선행개념을 "이전에 배운 개념" 중에서 고를 때 사용한다. 도메인 사전 없이 어휘 겹침만 본다.
     */
    public static boolean isRelated(String concept, Collection<String> anchors) {
        if (concept == null || anchors == null) return false;
        String c = normalize(concept);
        if (c.isEmpty()) return false;
        for (String a : anchors) {
            for (String tok : tokens(a)) if (c.contains(tok)) return true;
            String an = normalize(a);
            if (!an.isEmpty() && (an.contains(c) || c.contains(an))) return true;
        }
        return false;
    }

    // 학습 범주를 구분하지 못하는 일반 학술어(도메인 개념이 아닌 구조어). 범주 연관 판정에서 제외한다.
    private static final Set<String> GENERIC_WORDS = Set.of(
            "기법", "방법", "개념", "기초", "기본", "심화", "고급", "입문", "활용", "응용", "실습", "예제", "원리", "구조",
            "이해", "정리", "학습", "복습", "소개", "개요", "종류", "특징", "비교", "설계", "구현", "분석", "점검", "최종",
            "시험", "준비", "마무리", "정의", "핵심", "요약", "총정리", "실전", "문제", "풀이", "이론", "과정", "단계");

    /**
     * 개념이 day 정체성(anchors: 주제어·과목·이미 연관된 개념)과 <b>학습 범주</b>를 공유하는지.
     * 일반 학술어("기법", "개념", "분석" …)를 뺀 뒤, 전체 포함 / 어절 일치 / 한글 2-gram(복합명사 형태소 근사) 겹침으로 판단한다.
     * 예) "회귀계수" ~ "선형회귀"(회귀) ✓, "K-평균 군집화" ~ "고급 회귀 기법" ✗(기법은 일반어).
     */
    public static boolean isLexicallyRelated(String concept, Collection<String> anchors) {
        if (concept == null || anchors == null) return false;
        String c = normalize(concept);
        if (c.isEmpty()) return false;
        Set<String> cGrams = contentGrams(concept);
        for (String a : anchors) {
            String an = normalize(a);
            if (an.isEmpty()) continue;
            if (an.contains(c) || c.contains(an)) return true;
            Set<String> aGrams = contentGrams(a);
            for (String g : cGrams) if (aGrams.contains(g)) return true;
        }
        return false;
    }

    /** 일반 학술어를 뺀 내용 어절의 한글 2-gram + 영문/숫자 어절(3자 이상) 집합. */
    static Set<String> contentGrams(String s) {
        Set<String> out = new HashSet<>();
        if (s == null) return out;
        for (String w : NON_WORD.split(s)) {
            String t = w.toLowerCase(Locale.ROOT);
            if (t.isEmpty() || GENERIC_WORDS.contains(t)) continue;
            // 어절 끝에 붙은 일반어("회귀기법" → "회귀")는 떼고 본다.
            for (String g : GENERIC_WORDS) if (t.length() > g.length() && t.endsWith(g)) { t = t.substring(0, t.length() - g.length()); break; }
            boolean hangul = t.chars().anyMatch(ch -> ch >= 0xAC00 && ch <= 0xD7A3);
            if (hangul) {
                if (t.length() == 1) continue;
                for (int i = 0; i + 2 <= t.length(); i++) {
                    String g = t.substring(i, i + 2);
                    if (!GENERIC_WORDS.contains(g)) out.add(g);
                }
            } else if (t.length() >= 3) out.add(t);
        }
        return out;
    }

    /** 플래너/로드맵 제목에서 "[로드맵 N주차 M일]"·"N일차" 접두어를 뗀 주제어. */
    public static String topicOf(String title) {
        if (title == null) return "";
        String t = ROADMAP_PREFIX.matcher(title).replaceFirst("");
        t = DAY_PREFIX.matcher(t).replaceFirst("");
        return MULTISPACE.matcher(t).replaceAll(" ").trim();
    }

    /** 비교용 정규화: 공백/기호 제거 + 소문자. */
    public static String normalize(String s) {
        return s == null ? "" : NON_WORD.matcher(s).replaceAll("").toLowerCase(Locale.ROOT);
    }

    /** anchors 에서 의미 토큰 추출(한글 2자 이상 어절·영문 3자 이상 단어). "고급 회귀 기법" → [고급, 회귀, 기법]. */
    static List<String> tokens(String s) {
        List<String> out = new ArrayList<>();
        if (s == null) return out;
        for (String w : NON_WORD.split(s)) {
            String t = w.toLowerCase(Locale.ROOT);
            if (t.isEmpty()) continue;
            boolean hangul = t.chars().anyMatch(ch -> ch >= 0xAC00 && ch <= 0xD7A3);
            if ((hangul && t.length() >= 2) || (!hangul && t.length() >= 3)) out.add(t);
        }
        return out;
    }

    /** 검사 단위: 전체, 괄호를 뗀 본문, 각 괄호 내부("(FN이크다)" 같은 괄호 속 서술도 잡는다). */
    private static List<String> segments(String compact) {
        List<String> out = new ArrayList<>();
        out.add(compact);
        Matcher m = PAREN_GROUP.matcher(compact);
        while (m.find()) if (!m.group(1).isBlank()) out.add(m.group(1).trim());
        String stripped = PAREN_GROUP.matcher(compact).replaceAll("").trim();
        if (!stripped.isEmpty() && !stripped.equals(compact)) out.add(stripped);
        return out;
    }

    private static boolean balancedParens(String s) {
        int depth = 0;
        for (char ch : s.toCharArray()) {
            if (ch == '(') depth++;
            else if (ch == ')') { depth--; if (depth < 0) return false; }
        }
        return depth == 0;
    }

    private static int count(Pattern p, String s) { int n = 0; Matcher m = p.matcher(s); while (m.find()) n++; return n; }

    private static int longestHangulRun(String s) {
        int best = 0; Matcher m = HANGUL_RUN.matcher(s);
        while (m.find()) best = Math.max(best, m.end() - m.start());
        return best;
    }
}
