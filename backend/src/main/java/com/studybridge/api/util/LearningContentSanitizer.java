package com.studybridge.api.util;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 로드맵/플래너 학습 항목에서 PDF 메타데이터 노이즈(표지 날짜·교수명·강의자명·코스 제목·페이지 번호 등)를
 * 제거/거부하기 위한 결정적(deterministic) 유틸. AI07(원격, 수정 불가)이 노이즈를 흘려도
 * Spring 저장 직전에 1차 방어한다(React는 2차 방어).
 *
 * <p>정책
 * <ul>
 *   <li>clean(): 선행 슬라이드 번호("08. ")·선행 날짜/이름 메타데이터("2026.04 조수연 ")를 제거하고 공백 정리.
 *   <li>isNoise(): 정제 후에도 날짜 단독/날짜+이름/코스 제목 단독/숫자·기호뿐/2자 미만이면 노이즈로 거부.
 * </ul>
 *
 * <p>예시
 * <pre>
 *   clean("2026.04 조수연 Activity 생명주기") = "Activity 생명주기"
 *   clean("08. View Model")                  = "View Model"
 *   isNoise("2026.04 조수연")                  = true   (날짜+이름만 → 거부)
 *   isNoise("2026")                           = true   (날짜 단독 → 거부)
 *   isNoise("Modern Android Development 2026", "Modern Android Development 2026") = true (코스 제목 단독 → 거부)
 * </pre>
 *
 * <p>한계: 날짜와 인접하지 않은 "맨 이름 단독"(예: 앞뒤 날짜 없는 "조수연")은 임의 인명을 일반 개념어
 * (함수/변수 등)와 구분할 수 없어 보수적으로 통과시킨다. 실제 보고된 노이즈는 모두 날짜+이름/코스제목
 * 형태라 이 휴리스틱으로 커버된다.
 */
public final class LearningContentSanitizer {

    private LearningContentSanitizer() {}

    // 날짜 토큰: 2000~2099 + 선택적 .월.일 (구분자 . - /)
    private static final String DATE_CORE = "20\\d{2}(?:\\s*[.\\-/]\\s*\\d{1,2}){0,2}";

    // 선행 슬라이드/페이지 번호: "08. ", "3) " (뒤에 공백+내용이 와야 제거)
    private static final Pattern LEADING_SLIDE_NO =
            Pattern.compile("^\\s*\\d{1,3}\\s*[.)]\\s+(?=\\S)");

    // 선행 메타데이터: 토큰 경계로 끝나는 날짜 + (선택) 한글 이름 "딱 한 토큰". 그 뒤 공백까지 제거.
    // - 날짜는 (?=\\s|$)로 토큰 경계 확인 → "2026년..."의 "2026"은 날짜로 보지 않는다.
    // - 한국어 인명은 보통 공백으로 끊긴 단일 토큰(예: 조수연)이라 1개만 제거 → 내용어("예외 처리")는 보존.
    private static final Pattern LEADING_META =
            Pattern.compile("^\\s*" + DATE_CORE + "(?=\\s|$)(?:\\s+[가-힣]{2,4}(?=\\s|$))?\\s*");

    // 전체가 날짜 단독: "2026", "2026.04", "2026-04-01"
    private static final Pattern DATE_ONLY =
            Pattern.compile("^\\s*" + DATE_CORE + "\\s*$");

    // 전체가 날짜 + 이름(들): "2026.04 조수연"
    private static final Pattern DATE_AND_NAME_ONLY =
            Pattern.compile("^\\s*" + DATE_CORE + "(?:\\s+[가-힣]{2,4})+\\s*$");

    // 숫자/기호/공백뿐
    private static final Pattern DIGITS_PUNCT_ONLY =
            Pattern.compile("^[\\d\\s.,\\-/_:;()\\[\\]]+$");

    // 끝에 붙은 연도(코스 제목 비교용으로 제거): "... 2026"
    private static final Pattern TRAILING_YEAR =
            Pattern.compile("\\s*20\\d{2}\\s*$");

    // 표지/푸터형 코스 제목: 단독 연도 토큰(공백+20xx)으로 끝나는 구. 자료 제목을 몰라도 노이즈로 본다.
    // 예) "Modern Android Development 2026" (자료 제목이 "안드로이드"여도 매칭됨). find()로 검사.
    private static final Pattern ENDS_WITH_YEAR =
            Pattern.compile("\\s20\\d{2}\\s*$");

    private static final Pattern MULTISPACE = Pattern.compile("[\\t ]{2,}");

    /** 선행 슬라이드 번호 + 선행 날짜/이름 메타데이터를 제거하고 공백 정리한 학습 텍스트를 반환. */
    public static String clean(String raw) {
        if (raw == null) return "";
        String s = raw.trim();
        if (s.isEmpty()) return "";
        // 두 번까지 반복 제거(예: "08. 2026.04 조수연 ...")
        for (int i = 0; i < 2; i++) {
            String before = s;
            s = LEADING_SLIDE_NO.matcher(s).replaceFirst("");
            s = LEADING_META.matcher(s).replaceFirst("");
            s = s.trim();
            if (s.equals(before)) break;
        }
        s = MULTISPACE.matcher(s).replaceAll(" ").trim();
        return s;
    }

    /**
     * 정제 후에도 학습 항목으로 부적합(메타데이터 노이즈)이면 true.
     * @param courseTitle 자료/코스 제목(있으면 동일 문자열 단독 사용을 노이즈로 간주). null 허용.
     */
    public static boolean isNoise(String raw, String courseTitle) {
        if (raw == null) return true;
        String c = clean(raw);
        if (c.isEmpty()) return true;
        if (c.length() < 2) return true;
        if (DATE_ONLY.matcher(c).matches()) return true;
        if (DATE_AND_NAME_ONLY.matcher(c).matches()) return true;
        if (DIGITS_PUNCT_ONLY.matcher(c).matches()) return true;
        if (ENDS_WITH_YEAR.matcher(c).find()) return true;   // "Modern Android Development 2026" 류 표지 제목
        if (isCourseTitle(c, courseTitle)) return true;
        return false;
    }

    /** 정제 결과가 유효하면 그 값을, 노이즈면 null 을 반환(호출부에서 fallback 으로 대체). */
    public static String cleanOrNull(String raw, String courseTitle) {
        return isNoise(raw, courseTitle) ? null : clean(raw);
    }

    /** 리스트의 각 항목을 정제하고 노이즈/중복(대소문자 무시)을 제거. null 입력 시 빈 리스트. */
    public static List<String> cleanList(List<String> in, String courseTitle) {
        List<String> out = new ArrayList<>();
        if (in == null) return out;
        Set<String> seen = new LinkedHashSet<>();
        for (String item : in) {
            if (isNoise(item, courseTitle)) continue;
            String c = clean(item);
            String key = c.toLowerCase();
            if (seen.add(key)) out.add(c);
        }
        return out;
    }

    /** 텍스트(정제본)가 코스 제목과 (끝 연도를 무시하고) 동일하면 true. */
    private static boolean isCourseTitle(String cleaned, String courseTitle) {
        if (courseTitle == null || courseTitle.isBlank()) return false;
        String a = normalizeTitle(cleaned);
        String b = normalizeTitle(courseTitle);
        return !a.isEmpty() && a.equals(b);
    }

    private static String normalizeTitle(String s) {
        String t = TRAILING_YEAR.matcher(s.trim()).replaceAll("").trim();
        t = MULTISPACE.matcher(t).replaceAll(" ");
        return t.toLowerCase();
    }
}
