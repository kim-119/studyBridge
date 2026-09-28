package com.studybridge.api.util;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * material_quizzes.quiz_data(AI07 원문 JSON, 정답 포함) 의 서버 전용 파서.
 *
 * <p>정답 키(answer/answerIndex/correctAnswer/correct_answer)는 여기서만 읽고, 브라우저로 나가는
 * public DTO 에는 절대 실리지 않는다. 문항/보기 id 는 quizId 와 저장 순서에서 결정적으로 만들어진다
 * ({@code q{quizId}-{n}}, {@code o{n}}) — 다른 퀴즈의 questionId 는 접두어가 달라 채점에서 거절된다.</p>
 */
public final class MaterialQuizContent {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private MaterialQuizContent() {}

    /** 서버 내부 문항(정답 포함). */
    public static final class InternalQuestion {
        private final int index;
        private final String questionId;
        private final String question;
        private final String questionType;
        private final String answerType;
        private final List<String> options;
        private final List<String> optionIds;   // AI07 optionIds(["A","B","C","D"]) 또는 생성값(o1..)
        private final Integer correctIndex;     // null = 정답 판독 불가(채점 불가 문항)
        private final String explanation;
        private final String difficulty;

        InternalQuestion(int index, String questionId, String question, String questionType, String answerType,
                         List<String> options, List<String> optionIds, Integer correctIndex, String explanation, String difficulty) {
            this.index = index;
            this.questionId = questionId;
            this.question = question;
            this.questionType = questionType;
            this.answerType = answerType;
            this.options = options;
            this.optionIds = optionIds;
            this.correctIndex = correctIndex;
            this.explanation = explanation;
            this.difficulty = difficulty;
        }

        public int getIndex() { return index; }
        public String getQuestionId() { return questionId; }
        public String getQuestion() { return question; }
        public String getQuestionType() { return questionType; }
        public String getAnswerType() { return answerType; }
        public List<String> getOptions() { return options; }
        public List<String> getOptionIds() { return optionIds; }
        public Integer getCorrectIndex() { return correctIndex; }
        public String getExplanation() { return explanation; }
        public String getDifficulty() { return difficulty; }
        public String getCorrectOptionId() { return isGradable() ? optionIds.get(correctIndex) : null; }
        /** optionId → 0-based index. 이 문항의 보기가 아니면 null. */
        public Integer indexOfOption(String optionId) {
            if (optionId == null) return null;
            int i = optionIds.indexOf(optionId.trim());
            return i < 0 ? null : i;
        }
        public boolean isGradable() {
            return correctIndex != null && correctIndex >= 0 && correctIndex < options.size() && optionIds.size() == options.size();
        }
    }

    public static String questionId(Long quizId, int index) {
        return "q" + (quizId == null ? 0 : quizId) + "-" + (index + 1);
    }

    public static String optionId(int optionIndex) {
        return "o" + (optionIndex + 1);
    }


    /** quizData → 내부 문항 목록. 파싱 실패/빈 값이면 빈 리스트(예외 없음). */
    public static List<InternalQuestion> parse(Long quizId, String quizData) {
        if (quizData == null || quizData.isBlank()) return Collections.emptyList();
        try {
            JsonNode root = MAPPER.readTree(quizData);
            JsonNode arr = null;
            if (root.isArray()) arr = root;
            else if (root.has("quizzes")) arr = root.get("quizzes");
            else if (root.has("questions")) arr = root.get("questions");
            else if (root.has("quizData") && root.get("quizData").isTextual()) {
                JsonNode inner = MAPPER.readTree(root.get("quizData").asText());
                arr = inner.isArray() ? inner : (inner.has("quizzes") ? inner.get("quizzes") : inner.get("questions"));
            }
            if (arr == null || !arr.isArray()) return Collections.emptyList();

            List<InternalQuestion> out = new ArrayList<>();
            int idx = 0;
            for (JsonNode node : arr) {
                if (node == null || !node.isObject()) continue;
                List<String> options = readOptions(node);
                List<String> optionIds = readOptionIds(node, options.size());
                Integer correct = readCorrectIndex(node, options, optionIds);
                String question = textOf(node, "question", textOf(node, "q", "Q" + (idx + 1) + ". 문제"));
                // 문항 id: AI07 questionId(q_*) 우선, 없으면 quizId 접두 생성값. 어느 쪽이든 다른 퀴즈의 id 는 소속 검증에서 거절된다.
                String qid = textOf(node, "questionId", null);
                if (qid == null || qid.isBlank()) qid = questionId(quizId, idx);
                out.add(new InternalQuestion(idx, qid, question, textOf(node, "questionType", null), textOf(node, "answerType", null),
                        options, optionIds, correct, textOf(node, "explanation", ""), textOf(node, "difficulty", null)));
                idx++;
            }
            return out;
        } catch (Exception e) {
            return Collections.emptyList();
        }
    }

    private static List<String> readOptions(JsonNode node) {
        JsonNode opts = node.has("options") ? node.get("options")
                : node.has("choices") ? node.get("choices")
                : node.get("answers");
        List<String> out = new ArrayList<>();
        if (opts != null && opts.isArray()) {
            for (JsonNode o : opts) {
                if (o.isTextual()) out.add(o.asText());
                else if (o.has("text")) out.add(o.get("text").asText());
                else if (o.has("content")) out.add(o.get("content").asText());
                else if (o.has("option")) out.add(o.get("option").asText());
                else out.add(o.asText());
            }
        }
        return out;
    }

    /** optionIds: AI07 값이 보기 수와 같으면 그대로, 아니면 o1..oN 생성. */
    private static List<String> readOptionIds(JsonNode node, int optionCount) {
        List<String> ids = new ArrayList<>();
        JsonNode raw = node.get("optionIds");
        if (raw != null && raw.isArray() && raw.size() == optionCount) {
            for (JsonNode o : raw) ids.add(o.asText());
            if (ids.stream().allMatch(x -> x != null && !x.isBlank()) && ids.stream().distinct().count() == ids.size()) return ids;
            ids.clear();
        }
        for (int i = 0; i < optionCount; i++) ids.add(optionId(i));
        return ids;
    }

    /**
     * 정답 인덱스. ReviewNoteService 와 같은 키 우선순위이지만, 어떤 키도 없으면 0 으로 위장하지 않고 null 을 돌려준다
     * (채점 불가 문항은 총점 분모에서 제외되고 응답에 gradable=false 로 드러난다). correctOptionIds 는 마지막 폴백.
     */
    private static Integer readCorrectIndex(JsonNode node, List<String> options, List<String> optionIds) {
        if (node.has("answerIndex") && node.get("answerIndex").isInt()) return node.get("answerIndex").asInt();
        for (String key : new String[] {"answer", "correctAnswer", "correct_answer", "correctIndex"}) {
            JsonNode v = node.get(key);
            if (v == null || v.isNull()) continue;
            if (v.isInt()) return v.asInt();
            if (v.isTextual()) {
                String s = v.asText().trim();
                if (options.contains(s)) return options.indexOf(s);
                // "2" 같은 숫자 문자열
                try { return Integer.parseInt(s); } catch (NumberFormatException ignore) { /* 계속 */ }
            }
        }
        JsonNode coi = node.get("correctOptionIds");
        if (coi != null && coi.isArray() && coi.size() == 1) {
            int i = optionIds.indexOf(coi.get(0).asText());
            if (i >= 0) return i;
        }
        return null;
    }

    private static String textOf(JsonNode node, String key, String dflt) {
        if (node.has(key) && !node.get(key).isNull()) return node.get(key).asText();
        return dflt;
    }
}
