package com.studybridge.api.service.recommendation;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 실제 교재 텍스트(PDF 추출본)에서 확인 가능한 장(chapter) 목차와, 계획 문장의 장 번호 참조를 다룬다.
 *
 * <p>"확인된 목차" 의 기준(형태 규칙만, 도메인 문자열 없음):</p>
 * <ul>
 *   <li>"목차/차례/Contents" 제목 뒤 구간의 "N장 제목" / "제N장 제목" / "Chapter N 제목" / "N. 제목 ...쪽번호" 줄, 또는</li>
 *   <li>본문 전체의 "제N장 제목" / "Chapter N 제목" 머리글.</li>
 *   <li>서로 다른 장 번호가 2개 이상이고 1~2장부터 시작해야 verified=true. 그렇지 않으면 목차로 인정하지 않는다.</li>
 * </ul>
 * 목차가 확인되지 않으면 다음 장의 <b>제목</b>을 만들어 내지 않는다 — 호출자는 verificationRequired 로 표시한다.
 */
public final class TextbookToc {

    public record Entry(int number, String title) {}

    private final List<Entry> entries;
    private final boolean verified;

    private TextbookToc(List<Entry> entries, boolean verified) {
        this.entries = List.copyOf(entries);
        this.verified = verified;
    }

    public static TextbookToc none() {
        return new TextbookToc(List.of(), false);
    }

    public List<Entry> entries() { return entries; }

    public boolean verified() { return verified; }

    public Optional<Entry> chapter(int number) {
        return entries.stream().filter(e -> e.number() == number).findFirst();
    }

    /** 목차상 마지막 장 번호(목차 미확인이면 empty). */
    public Optional<Integer> lastChapter() {
        return verified ? entries.stream().map(Entry::number).max(Integer::compare) : Optional.empty();
    }

    /**
     * AI 가 제시한 장 제목이 확인된 목차와 일치하는지(공백·구두점 무시, 포함 관계 허용).
     * 목차 미확인이면 항상 false.
     */
    public boolean matchesTitle(int number, String title) {
        if (!verified || title == null || title.isBlank()) return false;
        return chapter(number).map(e -> {
            String a = norm(e.title());
            String b = norm(title);
            return !a.isEmpty() && !b.isEmpty() && (a.equals(b) || a.contains(b) || b.contains(a));
        }).orElse(false);
    }

    // ───────────────────────── 추출 ─────────────────────────

    private static final Pattern TOC_HEADING = Pattern.compile("^\\s*(목\\s*차|차\\s*례|contents|table of contents)\\s*$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern KO_CHAPTER = Pattern.compile("^\\s*(?:제\\s*)?(\\d{1,2})\\s*장[\\s.:·\\-]+(.{2,60}?)\\s*(?:\\.{2,}\\s*)?(?:\\d{1,4})?\\s*$");
    private static final Pattern KO_CHAPTER_STRICT = Pattern.compile("^\\s*제\\s*(\\d{1,2})\\s*장[\\s.:·\\-]+(.{2,60}?)\\s*$");
    private static final Pattern EN_CHAPTER = Pattern.compile("^\\s*chapter\\s+(\\d{1,2})[\\s.:\\-]+(.{2,60}?)\\s*(?:\\.{2,}\\s*)?(?:\\d{1,4})?\\s*$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern NUMBERED_WITH_PAGE = Pattern.compile("^\\s*(\\d{1,2})\\.\\s+([^\\d].{1,58}?)\\s*(?:\\.{2,}|\\s{2,}|·{2,})\\s*\\d{1,4}\\s*$");
    private static final int TOC_WINDOW_LINES = 80;

    public static TextbookToc extract(String text) {
        if (text == null || text.isBlank()) return none();
        String[] lines = text.split("\\r?\\n");
        Map<Integer, String> found = new LinkedHashMap<>();

        // 1) "목차" 구간
        for (int i = 0; i < lines.length; i++) {
            if (!TOC_HEADING.matcher(lines[i]).matches()) continue;
            for (int j = i + 1; j < Math.min(lines.length, i + 1 + TOC_WINDOW_LINES); j++) {
                String l = lines[j];
                Matcher m = KO_CHAPTER.matcher(l);
                if (!m.matches()) m = EN_CHAPTER.matcher(l);
                if (!m.matches()) m = NUMBERED_WITH_PAGE.matcher(l);
                if (m.matches()) put(found, m.group(1), m.group(2));
            }
            if (found.size() >= 2) break;
        }
        // 2) 본문 머리글("제N장", "Chapter N")
        if (found.size() < 2) {
            for (String l : lines) {
                Matcher m = KO_CHAPTER_STRICT.matcher(l);
                if (!m.matches()) m = EN_CHAPTER.matcher(l);
                if (m.matches()) put(found, m.group(1), m.group(2));
            }
        }
        List<Entry> entries = new ArrayList<>();
        found.forEach((n, t) -> entries.add(new Entry(n, t)));
        entries.sort((a, b) -> Integer.compare(a.number(), b.number()));
        boolean verified = entries.size() >= 2 && entries.get(0).number() <= 2;
        return new TextbookToc(entries, verified);
    }

    private static void put(Map<Integer, String> found, String num, String title) {
        try {
            int n = Integer.parseInt(num);
            String t = title == null ? "" : title.replaceAll("[.·]{2,}.*$", "").trim();
            if (n <= 0 || t.length() < 2) return;
            found.putIfAbsent(n, t);
        } catch (NumberFormatException ignored) {
            // 숫자 아님 → 무시
        }
    }

    // ───────────────────────── 계획 문장의 장 참조 ─────────────────────────

    /** "선형대수 2장 학습하기" → (prefix="선형대수", number=2). */
    public record ChapterRef(String prefix, int number) {}

    private static final Pattern REF = Pattern.compile("(?:제\\s*)?(\\d{1,2})\\s*장|\\bchapter\\s*(\\d{1,2})\\b|\\bch\\.?\\s*(\\d{1,2})\\b",
            Pattern.CASE_INSENSITIVE);

    public static Optional<ChapterRef> chapterRef(String text) {
        if (text == null) return Optional.empty();
        Matcher m = REF.matcher(text);
        if (!m.find()) return Optional.empty();
        String g = m.group(1) != null ? m.group(1) : m.group(2) != null ? m.group(2) : m.group(3);
        String prefix = text.substring(0, m.start()).replaceAll("^\\[[^\\]]*\\]\\s*", "").trim();
        try {
            return Optional.of(new ChapterRef(prefix, Integer.parseInt(g)));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    static String norm(String s) {
        return s == null ? "" : s.toLowerCase(Locale.ROOT).replaceAll("[\\s\\p{Punct}·‧∙]", "");
    }
}
