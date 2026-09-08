package com.studybridge.api.util;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 사용자 노출 한국어 문장의 템플릿 조립 흔적을 제거하는 결정적 유틸(도메인 무관).
 *
 * <ul>
 *   <li>조사 보정 표기("기법을(를)", "모델이(가)", "노트은(는)")를 앞 글자의 받침으로 확정한다.</li>
 *   <li>불릿 마커("•", "·" 등)·"[오늘 목표]" 접두어·"(주차 흐름: …)" 같은 메타 괄호를 제거한다.</li>
 *   <li>문장 종결 보정: 서술형은 마침표, 의문형은 물음표로 끝나게 한다.</li>
 * </ul>
 * 조사가 필요한 문장을 새로 만들 때는 {@link #withJosa(String, String, String)}로 받침에 맞는 조사를 붙인다.
 */
public final class KoreanTextNormalizer {

    private KoreanTextNormalizer() {}

    private static final Pattern JOSA_MARKER = Pattern.compile(
            "(?<prev>[\\p{L}\\p{N})\\]”’\"'])\\s*(?<pair>을\\(를\\)|를\\(을\\)|이\\(가\\)|가\\(이\\)|은\\(는\\)|는\\(은\\)"
            + "|과\\(와\\)|와\\(과\\)|으로\\(로\\)|로\\(으로\\)|이\\(라\\)|아\\(야\\)|이나\\(나\\)|나\\(이나\\)|이라\\(라\\)|라\\(이라\\))");
    private static final Pattern META_PAREN = Pattern.compile(
            "\\s*[(（][^()（）]*(?:주차\\s*흐름|흐름\\s*[:：]|주차\\s*[:：]|메타|참고\\s*[:：])[^()（）]*[)）]");
    private static final Pattern WEEK_THEME = Pattern.compile(
            "\\s*[(（]\\s*주차\\s*흐름\\s*[:：]\\s*(?<theme>[^()（）]+?)\\s*[)）]");
    private static final Pattern TRAILING_PAREN_AFTER_SENTENCE = Pattern.compile("(?<=[.!?])\\s*[(（][^()（）]*[)）]");
    private static final Pattern TODAY_GOAL_PREFIX = Pattern.compile("\\[오늘\\s*목표\\]\\s*");
    private static final Pattern BULLET = Pattern.compile("(?:^|\\s)[•·▪‣∙◦▶►■□]+(?=\\s|$)|[•▪‣∙◦]");
    private static final Pattern MULTISPACE = Pattern.compile("[\\t ]{2,}");
    private static final Pattern SPACE_BEFORE_PUNCT = Pattern.compile("\\s+(?=[.,!?])");
    private static final Pattern EMPTY_PAREN = Pattern.compile("\\s*[(（]\\s*[)）]");
    private static final Pattern DECLARATIVE_END = Pattern.compile("[가-힣]$");
    private static final Pattern QUESTION_END = Pattern.compile("(?:가|까|나|지|요|냐|니)$");
    private static final Pattern DUP_JOSA = Pattern.compile("(?<=[가-힣])(을|를|이|가|은|는)\\1(?=\\s|$)");

    /** 불릿·"[오늘 목표]"·메타 괄호 제거 + 조사 확정 + 공백 정리(문장 종결은 건드리지 않는다). */
    public static String clean(String s) {
        if (s == null) return "";
        String out = TODAY_GOAL_PREFIX.matcher(s).replaceAll("");
        out = META_PAREN.matcher(out).replaceAll("");
        out = TRAILING_PAREN_AFTER_SENTENCE.matcher(out).replaceAll("");
        out = EMPTY_PAREN.matcher(out).replaceAll("");
        out = stripBullets(out);
        out = resolveJosa(out);
        out = DUP_JOSA.matcher(out).replaceAll("$1");
        out = MULTISPACE.matcher(out).replaceAll(" ");
        out = SPACE_BEFORE_PUNCT.matcher(out).replaceAll("");
        return out.trim();
    }

    /** 불릿 마커만 제거(줄 앞·단어 사이 모두). */
    public static String stripBullets(String s) {
        if (s == null) return "";
        return MULTISPACE.matcher(BULLET.matcher(s).replaceAll(" ")).replaceAll(" ").trim();
    }

    /** "(주차 흐름: X)" 를 분리한다. [0]=괄호를 뗀 본문, [1]=X(없으면 null). */
    public static String[] splitWeekTheme(String s) {
        if (s == null) return new String[]{"", null};
        Matcher m = WEEK_THEME.matcher(s);
        String theme = null;
        if (m.find()) theme = m.group("theme").trim();
        String body = WEEK_THEME.matcher(s).replaceAll("");
        return new String[]{body.trim(), theme == null || theme.isEmpty() ? null : theme};
    }

    /** "기법을(를)" → "기법을", "모델이(가)" → "모델이" 처럼 앞 글자 받침으로 조사를 확정한다. */
    public static String resolveJosa(String s) {
        if (s == null) return null;
        Matcher m = JOSA_MARKER.matcher(s);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String prev = m.group("prev");
            String pair = m.group("pair");
            String a = pair.substring(0, pair.indexOf('('));
            String b = pair.substring(pair.indexOf('(') + 1, pair.length() - 1);
            String chosen = josa(lastLetter(s, m.start("pair")), a, b);
            m.appendReplacement(sb, Matcher.quoteReplacement(prev + chosen));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    /** word 뒤에 받침 유무에 맞는 조사(withBatchim/withoutBatchim)를 붙인다. 한글·숫자로 끝나지 않으면 받침 없는 형태를 쓴다. */
    public static String withJosa(String word, String withBatchim, String withoutBatchim) {
        if (word == null || word.isEmpty()) return "";
        String w = word.trim();
        char last = w.charAt(w.length() - 1);
        if (!isHangul(last) && !Character.isDigit(last)) return w + withoutBatchim;
        return w + josa(last, withBatchim, withoutBatchim);
    }

    /** 서술형 문장 종결 보정: 한글로 끝나면 마침표를 붙인다. 이미 문장 부호로 끝나면 그대로. */
    public static String ensureSentenceEnd(String s) {
        if (s == null) return "";
        String t = s.trim();
        if (t.isEmpty()) return t;
        if (DECLARATIVE_END.matcher(t).find()) return t + ".";
        return t;
    }

    /** 의문문 종결 보정: "…무엇인가" → "…무엇인가?", "…인가." → "…인가?". */
    public static String ensureQuestionEnd(String s) {
        if (s == null) return "";
        String t = s.trim();
        if (t.isEmpty()) return t;
        if (t.endsWith("?") || t.endsWith("？")) return t;
        t = t.replaceAll("[.!。]+$", "").trim();
        if (QUESTION_END.matcher(t).find()) return t + "?";
        return t.endsWith("?") ? t : t + "?";
    }

    /** 문자열이 문장 부호(./!/?)로 끝나는지. */
    public static boolean endsWithPunctuation(String s) {
        return s != null && s.trim().matches(".*[.!?。？]$");
    }

    public static boolean isHangul(char c) { return c >= 0xAC00 && c <= 0xD7A3; }

    /** 받침 유무(ㄹ 받침 + "으로" 는 "로"). */
    public static String josa(char last, String withBatchim, String withoutBatchim) {
        if (isHangul(last)) {
            int jong = (last - 0xAC00) % 28;
            if (withBatchim.equals("으로") && jong == 8) return withoutBatchim;   // ㄹ 받침은 "로"
            return jong == 0 ? withoutBatchim : withBatchim;
        }
        if (Character.isDigit(last)) {
            // 숫자 읽기 기준 받침: 0(영) 1(일) 3(삼) 6(육) 7(칠) 8(팔)
            return "013678".indexOf(last) >= 0 ? withBatchim : withoutBatchim;
        }
        return withoutBatchim;
    }

    private static char lastLetter(String s, int beforeIndex) {
        for (int i = beforeIndex - 1; i >= 0; i--) {
            char c = s.charAt(i);
            if (!Character.isWhitespace(c)) return c;
        }
        return ' ';
    }
}
