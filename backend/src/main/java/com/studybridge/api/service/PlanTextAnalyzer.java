package com.studybridge.api.service;

import lombok.AllArgsConstructor;
import lombok.Getter;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * PDF/플래너 텍스트를 chunk → 문장 → 행동 단위로 분해하는 결정적(deterministic) 분석기.
 *
 * 핵심 규칙 (LLM 불필요, 규칙 기반):
 *  1) 코드/패키지/URL/email/파일명/버전·소수 토큰을 placeholder 로 보호한 뒤 문장 분리 → 복원.
 *     예) com.example.coroutinepractice.data.dto, build.gradle.kts, MainActivity.kt,
 *         https://example.com, test@example.com, 1.5, v2.0 는 온점이 있어도 절대 끊지 않는다.
 *  2) PDF 줄바꿈으로 깨진 한글/코드 토큰을 정규화 단계에서 다시 붙인다.
 *  3) 문장 끝(. ? ! / 다. / 줄바꿈 / bullet) 기준으로 분리하고, 너무 짧은/의미 없는 조각은 제거·병합.
 *  4) 긴 문장은 한국어 연결어미(하고/하며/한 뒤/한 후) 기준으로 행동 단위로 추가 분해.
 *
 * 주의: 정규식의 \w/[A-Za-z_] 는 ASCII 전용(UNICODE_CHARACTER_CLASS 미사용)이라 한글에 매칭되지 않는다.
 */
@Component
public class PlanTextAnalyzer {

    // 보호 토큰 placeholder — 사설 영역(Private Use Area) 문자라 본문에 등장하지 않고 온점/공백도 포함하지 않는다.
    private static final String PH_OPEN = "";
    private static final String PH_CLOSE = "";

    // 순서 중요: URL/email 먼저(내부에 . / @ 포함) → 점으로 연결된 식별자(패키지/클래스/파일명) → 버전/소수.
    private static final Pattern P_URL = Pattern.compile("https?://[^\\s)\\]]+");
    private static final Pattern P_EMAIL = Pattern.compile("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}");
    // 점으로 연결된 ASCII 식별자: com.example..., java.lang.String, build.gradle.kts, MainActivity.kt
    private static final Pattern P_DOTTED = Pattern.compile("[A-Za-z_][A-Za-z0-9_$]*(?:\\.[A-Za-z_$][A-Za-z0-9_$]*)+");
    // 버전/소수: 1.5, v2.0, 1.2.3
    private static final Pattern P_VERSION = Pattern.compile("\\bv?\\d+(?:\\.\\d+)+\\b");

    private static final Pattern[] PROTECT = { P_URL, P_EMAIL, P_DOTTED, P_VERSION };

    // 문장 분리: 문장부호(. ? !) 뒤에 공백이 오는 지점.
    private static final Pattern SENTENCE_SPLIT = Pattern.compile("(?<=[.!?])\\s+");
    // 줄 머리의 목록 마커: "1. ", "2) ", "- ", "* ", "• "
    private static final Pattern LIST_MARKER = Pattern.compile("^\\s*(?:\\d+[.)]|[-*•·▪◦])\\s+");
    // 한국어 연결어미 기준 행동 분해
    private static final Pattern ACTION_SPLIT = Pattern.compile("(?<=하고)\\s+|(?<=하며)\\s+|(?<=한 뒤)\\s+|(?<=한 후)\\s+|(?<=한 다음)\\s+");
    private static final String[] TRAILING_CONNECTIVES = { "한 다음", "한 뒤", "한 후", "하고", "하며" };

    @Getter
    @AllArgsConstructor
    public static class SourceText {
        private final String sourceType;   // PDF | PLANNER | ROADMAP
        private final Integer pageNumber;  // nullable
        private final String text;
    }

    @Getter
    @AllArgsConstructor
    public static class ExtractedItem {
        private final String type;         // SENTENCE | ACTION
        private final String text;
        private final String sourceText;
        private final String sourceType;
        private final Integer pageNumber;
        private final int chunkIndex;
    }

    @Getter
    @AllArgsConstructor
    public static class Result {
        private final List<ExtractedItem> items;
        private final int chunkCount;
        private final int sentenceCount;
    }

    /** 여러 소스 텍스트를 받아 문장/행동 단위 항목으로 분해한다. */
    public Result extract(List<SourceText> sources) {
        List<ExtractedItem> items = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        int chunkSeq = 0;
        int sentenceCount = 0;

        for (SourceText src : sources) {
            if (src.getText() == null || src.getText().isBlank()) continue;

            Map<String, String> store = new HashMap<>();
            int[] counter = { 0 };
            String normalized = normalize(src.getText());
            String protectedText = protect(normalized, store, counter);

            String[] chunks = protectedText.split("\\n{2,}");
            for (String rawChunk : chunks) {
                if (rawChunk == null || rawChunk.isBlank()) continue;
                int chunkIndex = chunkSeq;
                boolean chunkProducedItem = false;

                for (String sentenceProtected : splitSentencesProtected(rawChunk)) {
                    String sentence = restore(sentenceProtected, store).trim();
                    if (isJunk(sentence)) continue;
                    sentenceCount++;

                    List<String> actions = splitActions(sentence);
                    boolean multi = actions.size() > 1;
                    for (String action : actions) {
                        String clean = cleanItemText(action);
                        if (isJunk(clean)) continue;
                        String key = dedupKey(clean);
                        if (seen.contains(key)) continue;
                        seen.add(key);
                        items.add(new ExtractedItem(
                                multi ? "ACTION" : "SENTENCE",
                                clean,
                                sentence,
                                src.getSourceType(),
                                src.getPageNumber(),
                                chunkIndex
                        ));
                        chunkProducedItem = true;
                        if (items.size() >= 200) break;
                    }
                    if (items.size() >= 200) break;
                }
                if (chunkProducedItem) chunkSeq++;
                if (items.size() >= 200) break;
            }
            if (items.size() >= 200) break;
        }
        int totalChunks = (int) items.stream().map(ExtractedItem::getChunkIndex).distinct().count();
        return new Result(items, totalChunks, sentenceCount);
    }

    // ---------------- 정규화 ----------------
    String normalize(String raw) {
        String t = raw.replace("\r\n", "\n").replace("\r", "\n");
        // 한글 단어 중간 줄바꿈 복원: "테스트하\n기" → "테스트하기"
        t = t.replaceAll("(?<=[가-힣])[ \t]*\n[ \t]*(?=[가-힣])", "");
        // 코드/식별자 중간 줄바꿈 복원: "com.example\n.data" → "com.example.data"
        t = t.replaceAll("(?<=[A-Za-z0-9_.])\n(?=[A-Za-z0-9_])", "");
        // 다중 공백 정리
        t = t.replaceAll("[ \t]{2,}", " ");
        // 단독 페이지 번호 줄 제거
        t = t.replaceAll("(?m)^\\s*\\d{1,4}\\s*$", "");
        // 3줄 이상 연속 빈 줄을 2줄로
        t = t.replaceAll("\n{3,}", "\n\n");
        return t.trim();
    }

    // ---------------- 코드 토큰 보호/복원 ----------------
    private String protect(String text, Map<String, String> store, int[] counter) {
        String t = text;
        for (Pattern p : PROTECT) {
            Matcher m = p.matcher(t);
            StringBuffer sb = new StringBuffer();
            while (m.find()) {
                String token = m.group();
                String ph = PH_OPEN + counter[0]++ + PH_CLOSE;
                store.put(ph, token);
                m.appendReplacement(sb, Matcher.quoteReplacement(ph));
            }
            m.appendTail(sb);
            t = sb.toString();
        }
        return t;
    }

    private String restore(String text, Map<String, String> store) {
        String t = text;
        // placeholder 가 중첩 보호된 경우를 대비해 반복 복원
        for (int i = 0; i < 4 && t.contains(PH_OPEN); i++) {
            for (Map.Entry<String, String> e : store.entrySet()) {
                t = t.replace(e.getKey(), e.getValue());
            }
        }
        return t;
    }

    // ---------------- 문장 분리 (보호된 텍스트 기준) ----------------
    private List<String> splitSentencesProtected(String chunk) {
        List<String> out = new ArrayList<>();
        for (String line : chunk.split("\n")) {
            String stripped = LIST_MARKER.matcher(line).replaceFirst("").trim();
            if (stripped.isEmpty()) continue;
            for (String part : SENTENCE_SPLIT.split(stripped)) {
                if (!part.isBlank()) out.add(part.trim());
            }
        }
        return out;
    }

    // ---------------- 행동 단위 분해 ----------------
    private List<String> splitActions(String sentence) {
        List<String> out = new ArrayList<>();
        if (sentence.length() <= 24) {
            out.add(sentence);
            return out;
        }
        String[] parts = ACTION_SPLIT.split(sentence);
        if (parts.length <= 1) {
            out.add(sentence);
            return out;
        }
        for (String p : parts) {
            String piece = p.trim();
            if (piece.isEmpty()) continue;
            // 비종결 조각 끝의 연결어미 제거: "...의존성을 분리하고" → "...의존성을 분리"
            for (String c : TRAILING_CONNECTIVES) {
                if (piece.endsWith(c)) { piece = piece.substring(0, piece.length() - c.length()).trim(); break; }
            }
            if (!piece.isEmpty()) out.add(piece);
        }
        return out.isEmpty() ? List.of(sentence) : out;
    }

    // ---------------- 항목 텍스트 정리 ----------------
    private String cleanItemText(String text) {
        String t = text.trim();
        t = t.replaceAll("[:;]\\s*$", "").trim();   // 후행 콜론/세미콜론 제거(heading 형태)
        t = t.replaceAll(",\\s*$", "").trim();      // 후행 쉼표 제거
        return t;
    }

    // ---------------- 잡음 판별 ----------------
    private boolean isJunk(String text) {
        if (text == null) return true;
        String t = text.trim();
        if (t.isEmpty()) return true;
        if (t.matches("^\\[.{1,20}\\]$")) return true;            // "[할 일]" 등 헤더
        if (t.matches("^[\\s\\d\\p{Punct}]+$")) return true;      // 숫자/문장부호/공백만
        if (containsCodeToken(t)) return false;                   // 코드 토큰 포함이면 짧아도 유지
        return t.replaceAll("\\s", "").length() < 4;              // 너무 짧은 조각
    }

    private boolean containsCodeToken(String t) {
        return P_DOTTED.matcher(t).find()
                || P_URL.matcher(t).find()
                || P_EMAIL.matcher(t).find()
                || P_VERSION.matcher(t).find();
    }

    private String dedupKey(String t) {
        return t.replaceAll("\\s", "").toLowerCase();
    }
}
