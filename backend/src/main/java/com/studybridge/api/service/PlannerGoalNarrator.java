package com.studybridge.api.service;

import com.studybridge.api.dto.PlannerSemanticDTO.Level;
import com.studybridge.api.dto.PlannerSemanticDTO.Request;
import com.studybridge.api.dto.PlannerSemanticDTO.Task;
import com.studybridge.api.dto.PlannerSemanticDTO.TaskType;
import com.studybridge.api.util.KoreanTextNormalizer;
import com.studybridge.api.util.LearningConceptValidator;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * AI 계획 분석의 사용자 노출 문장(목표 정합성 summary / 계획 summary / task 정합성 reason) 생성기.
 *
 * <p>배경: learningGoal 은 로드맵 objective 템플릿("선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다.
 * (주차 흐름: 복습과 시험 대비)")이 그대로 들어오는 경우가 많다. 이 원문을 고정 문구와 문자열 결합하면
 * "…학습한다. (…) 이해와 연결되어 있습니다." 같은 깨진 문장이 된다.
 *
 * <p>원칙
 * <ul>
 *   <li>learningGoal 원문을 문장에 결합하지 않는다. 목표에서 <b>의미 요소</b>(학습 방식)만 뽑고, 활동 유형(tasks)과
 *       주제어(topic)로 완결된 문장을 새로 만든다.</li>
 *   <li>조사 보정 표기("을(를)", "이(가)" 등)는 앞 글자의 받침으로 확정해 노출하지 않는다.</li>
 *   <li>"(주차 흐름: …)" 같은 메타 괄호, 문장 중간 말줄임("…")은 노출하지 않는다.</li>
 *   <li>AI07 산문도 같은 검사를 거쳐, 목표 원문이 그대로 들어 있거나 문장이 완결되지 않으면 생성 문장으로 대체한다.</li>
 *   <li>결과는 1~2개의 완결 문장(2문장 초과 시 문장 경계에서만 자른다).</li>
 * </ul>
 */
final class PlannerGoalNarrator {

    private PlannerGoalNarrator() {}

    /** 로드맵 objective 템플릿: "[X의] Y을/를 Z 중심으로 학습한다" → 학습 방식 Z 를 추출한다. */
    private static final Pattern GOAL_TEMPLATE = Pattern.compile(
            "^(?<object>.+?)(?:을|를)\\s+(?<method>.+?)\\s*(?:중심으로|위주로)\\s*(?:학습|공부|정리|연습|익히)[가-힣]*[.!]?$");
    private static final Pattern ELLIPSIS = Pattern.compile("…|\\.{3,}|‥");
    private static final Pattern SENTENCE_END = Pattern.compile("(?<=[.!?])\\s+");
    private static final Pattern COMPLETE_SENTENCE = Pattern.compile("(?:[가-힣][.!?]|[다요죠까][.!?]?|[.!?])$");

    private static final Map<TaskType, String> ACTIVITY_LABEL = Map.of(
            TaskType.CONCEPT, "개념 이해", TaskType.PRACTICE, "실습", TaskType.ANALYSIS, "결과 분석",
            TaskType.COMPARISON, "개념 비교", TaskType.REVIEW, "복습과 정리", TaskType.OUTPUT, "산출물 정리");
    private static final int MAX_FOCUS_ITEMS = 3;

    // ---------------- 생성 ----------------

    /** 목표 정합성 summary: 활동 구성(주제어·학습 방식·활동 유형)과 정합성 수준으로 완결 문장을 만든다. */
    static String alignmentSummary(Request req, List<Task> tasks, Level level) {
        String focus = focusPhrase(req, tasks);
        String subject = subject(req);
        StringBuilder sb = new StringBuilder("현재 학습 활동은 ");
        if (focus != null) {
            if (subject != null) sb.append(subject).append("의 ");
            sb.append(withJosa(focus, "을", "를")).append(" 중심으로 구성되어 있어 ");
        } else if (subject != null) {
            sb.append(withJosa(subject, "을", "를")).append(" 다루도록 구성되어 있어 ");
        } else {
            sb.append("오늘의 학습 목표에 맞춰 구성되어 있어 ");
        }
        Level lv = level == null ? Level.MEDIUM : level;
        switch (lv) {
            case HIGH -> sb.append("학습 목표와 전반적으로 잘 연결되어 있습니다.");
            case LOW -> sb.append("학습 목표와의 연결이 약한 편입니다. 목표에 직접 닿는 활동을 보강하는 것이 좋습니다.");
            default -> sb.append("학습 목표와 대체로 잘 연결되어 있습니다.");
        }
        return sb.toString();
    }

    /** 계획 summary 폴백: 활동 수·목표 시간·초점을 한 문장으로. 제목은 따옴표 안에 그대로 두고 목표 원문은 쓰지 않는다. */
    static String planSummary(Request req, List<Task> tasks, int totalMinutes) {
        String focus = focusPhrase(req, tasks);
        String subject = subject(req);
        int n = tasks == null ? 0 : tasks.size();
        String title = req.getTitle() == null || req.getTitle().isBlank() ? "오늘" : "‘" + req.getTitle().trim() + "’";
        StringBuilder sb = new StringBuilder();
        sb.append(title).append(" 학습은 ").append(n).append("개의 활동으로 구성되어 있으며, 총 ")
          .append(totalMinutes).append("분을 목표로 ");
        if (focus != null) {
            if (subject != null) sb.append(subject).append("의 ");
            sb.append(focus).append("에 초점을 둡니다.");
        } else if (subject != null) {
            sb.append(subject).append(" 학습에 초점을 둡니다.");
        } else {
            sb.append("오늘의 학습 목표에 초점을 둡니다.");
        }
        return sb.toString();
    }

    /** task 정합성 reason 폴백: 유형·주제어·수준으로 완결 문장을 만든다(목표 원문·제목 결합 없음). */
    static String taskAlignmentReason(Request req, TaskType type, Level level) {
        String label = ACTIVITY_LABEL.getOrDefault(type, "학습");
        String subject = subject(req);
        String target = subject != null ? subject + "에 대한 학습 목표" : "오늘의 학습 목표";
        Level lv = level == null ? Level.MEDIUM : level;
        return switch (lv) {
            case HIGH -> label + " 유형의 활동으로, " + target + "와 직접 연결됩니다.";
            case LOW -> label + " 유형의 활동으로, " + target + "와는 간접적으로만 연결됩니다.";
            default -> label + " 유형의 활동으로, " + target + "를 뒷받침합니다.";
        };
    }

    // ---------------- AI 산문 검사/정리 ----------------

    /**
     * AI07 산문을 사용자 노출용으로 정리한다. 통과하지 못하면 null(호출자는 생성 문장으로 대체).
     * 거부 조건: 비어 있음 / 말줄임 잘림 / 문장 미완결 / 학습 목표 원문이 그대로 결합됨.
     */
    static String sanitizeAiProse(String raw, String learningGoal) {
        if (raw == null || raw.isBlank()) return null;
        String s = clean(raw);
        if (s.isEmpty() || ELLIPSIS.matcher(s).find()) return null;
        if (embedsGoal(s, learningGoal)) return null;
        s = firstSentences(s, 2);
        if (!COMPLETE_SENTENCE.matcher(s).find()) return null;
        return s;
    }

    /** 메타 괄호·불릿·"[오늘 목표]" 제거 + 조사 보정 표기 확정 + 공백 정리({@link KoreanTextNormalizer#clean}). */
    static String clean(String s) { return KoreanTextNormalizer.clean(s); }

    /** "기법을(를)" → "기법을" 처럼 앞 글자 받침으로 조사를 확정한다({@link KoreanTextNormalizer#resolveJosa}). */
    static String resolveJosa(String s) { return KoreanTextNormalizer.resolveJosa(s); }

    /** word 뒤에 받침에 맞는 조사를 붙인다. 한글로 끝나지 않으면 조사를 생략한다(문장 생성용). */
    static String withJosa(String word, String withBatchim, String withoutBatchim) {
        if (word == null || word.isEmpty()) return "";
        char last = word.charAt(word.length() - 1);
        if (!KoreanTextNormalizer.isHangul(last)) return word;
        return word + KoreanTextNormalizer.josa(last, withBatchim, withoutBatchim);
    }

    // ---------------- 내부 ----------------

    /** 활동 초점 구: 개념 이해(있을 때) → 목표의 학습 방식 → 나머지 활동 유형 순, 최대 3개, "A, B, C" 결합. */
    private static String focusPhrase(Request req, List<Task> tasks) {
        List<String> items = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        List<Task> ts = tasks == null ? List.of() : tasks;
        boolean hasConcept = ts.stream().anyMatch(t -> t.getType() == TaskType.CONCEPT);
        if (hasConcept) add(items, seen, ACTIVITY_LABEL.get(TaskType.CONCEPT));
        String method = goalMethod(req.getLearningGoal());
        if (method != null) add(items, seen, method);
        for (Task t : ts) {
            if (t.getType() == null || t.getType() == TaskType.CONCEPT) continue;
            add(items, seen, ACTIVITY_LABEL.get(t.getType()));
        }
        if (items.isEmpty()) return null;
        if (items.size() > MAX_FOCUS_ITEMS) items = new ArrayList<>(items.subList(0, MAX_FOCUS_ITEMS));
        if (items.size() == 1) return items.get(0);
        if (items.size() == 2) return withJosa(items.get(0), "과", "와") + " " + items.get(1);
        return String.join(", ", items);
    }

    private static void add(List<String> items, Set<String> seen, String v) {
        if (v == null || v.isBlank()) return;
        String key = LearningConceptValidator.normalize(v);
        for (String s : seen) if (s.contains(key) || key.contains(s)) return;
        seen.add(key);
        items.add(v.trim());
    }

    /** 목표 문장에서 학습 방식("코드 흐름 추적")만 추출. 템플릿이 아니거나 개념명 형태가 아니면 null. */
    static String goalMethod(String learningGoal) {
        if (learningGoal == null || learningGoal.isBlank()) return null;
        String g = clean(learningGoal);
        Matcher m = GOAL_TEMPLATE.matcher(g);
        if (!m.matches()) return null;
        String method = m.group("method").trim();
        return LearningConceptValidator.isConceptLike(method) ? method : null;
    }

    /** 문장의 주제어: topic → 제목의 주제어 → null. 문장형이면 쓰지 않는다. */
    private static String subject(Request req) {
        String topic = req.getTopic() == null || req.getTopic().isBlank()
                ? LearningConceptValidator.topicOf(req.getTitle()) : req.getTopic().trim();
        if (topic == null || topic.isBlank()) return null;
        return LearningConceptValidator.isConceptLike(topic) ? topic : null;
    }

    /** AI 산문에 목표 원문(정리 후 10자 이상)이 그대로 들어 있으면 문자열 결합으로 본다. */
    private static boolean embedsGoal(String prose, String learningGoal) {
        if (learningGoal == null) return false;
        String goal = LearningConceptValidator.normalize(clean(learningGoal));
        if (goal.length() < 10) return false;
        String p = LearningConceptValidator.normalize(prose);
        if (p.contains(goal)) return true;
        // 종결 어미만 바뀐 경우("…학습한다" ↔ "…학습하는")도 원문 결합으로 본다.
        String stem = goal.replaceAll("(한다|합니다|하기|하는|이다|입니다)$", "");
        return stem.length() >= 10 && p.contains(stem);
    }

    /** 앞에서부터 최대 n 개의 완결 문장만 남긴다(문장 경계에서만 자른다). */
    static String firstSentences(String s, int n) {
        String[] parts = SENTENCE_END.split(s.trim());
        if (parts.length <= n) return s.trim();
        return String.join(" ", Arrays.copyOfRange(parts, 0, n)).trim();
    }
}
