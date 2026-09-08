package com.studybridge.api.service;

import com.studybridge.api.entity.Planner;
import com.studybridge.api.util.LearningDayNormalizer;
import com.studybridge.api.util.LearningDayNormalizer.DayContent;
import com.studybridge.api.util.LearningDayNormalizer.DayInput;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 로드맵 기반 플래너의 content/tmi 텍스트 형식(조립·파싱)의 단일 진실 지점.
 *
 * <pre>
 * content: [오늘 목표] {objective}\n\n[할 일]\n1. {task}\n2. {task}
 * tmi    : 핵심 개념: a, b\n복습 질문:\n- q1\n- q2\n체크포인트: {checkpoint}\n산출물: {deliverable}
 * </pre>
 * 저장 전에는 {@link LearningDayNormalizer} 를 거친 {@link DayContent} 만 조립하고, 기존 저장본(PDF·backfill)은
 * {@link #parse}로 구조화한 뒤 다시 정규화한다. 태그가 없는 자유 입력(사용자 플래너)은 parse 가 null 을 돌려준다.
 */
final class PlannerDayContent {

    private PlannerDayContent() {}

    static final String GOAL_TAG = "[오늘 목표]";
    static final String TASK_TAG = "[할 일]";
    static final String CONCEPT_TAG = "핵심 개념:";
    static final String QUESTION_TAG = "복습 질문:";
    static final String CHECKPOINT_TAG = "체크포인트:";
    static final String DELIVERABLE_TAG = "산출물:";

    private static final Pattern NUMBERED = Pattern.compile("^\\s*\\d+\\s*[.)]\\s*(.*)$");
    private static final Pattern DASHED = Pattern.compile("^\\s*[-–•·]\\s*(.*)$");

    /** 저장본을 구조화한 결과(정규화 전). extraMemo 는 태그에 속하지 않은 메모 줄. */
    record Sections(String objective, List<String> tasks, List<String> concepts, List<String> questions,
                    String checkpoint, String deliverable, List<String> extraMemo) {
        boolean isEmpty() {
            return objective.isBlank() && tasks.isEmpty() && concepts.isEmpty() && questions.isEmpty()
                    && checkpoint.isBlank() && deliverable.isBlank();
        }
    }

    static String composeContent(DayContent c) {
        StringBuilder sb = new StringBuilder();
        if (!c.objective().isBlank()) sb.append(GOAL_TAG).append(' ').append(c.objective()).append("\n\n");
        if (!c.tasks().isEmpty()) {
            sb.append(TASK_TAG).append('\n');
            for (int i = 0; i < c.tasks().size(); i++) sb.append(i + 1).append(". ").append(c.tasks().get(i)).append('\n');
        }
        return sb.toString().trim();
    }

    static String composeTmi(DayContent c) { return composeTmi(c, List.of()); }

    static String composeTmi(DayContent c, List<String> extraMemo) {
        StringBuilder sb = new StringBuilder();
        if (!c.concepts().isEmpty()) sb.append(CONCEPT_TAG).append(' ').append(String.join(", ", c.concepts())).append('\n');
        if (!c.reviewQuestions().isEmpty()) {
            sb.append(QUESTION_TAG).append('\n');
            for (String q : c.reviewQuestions()) sb.append("- ").append(q).append('\n');
        }
        if (!c.checkpoint().isBlank()) sb.append(CHECKPOINT_TAG).append(' ').append(c.checkpoint()).append('\n');
        if (!c.deliverable().isBlank()) sb.append(DELIVERABLE_TAG).append(' ').append(c.deliverable()).append('\n');
        for (String m : extraMemo) if (m != null && !m.isBlank()) sb.append(m.trim()).append('\n');
        return sb.toString().trim();
    }

    /** content/tmi 를 구조화한다. 로드맵 형식 태그가 하나도 없으면 null(자유 입력 플래너). */
    static Sections parse(String content, String tmi) {
        String c = content == null ? "" : content;
        String t = tmi == null ? "" : tmi;
        boolean tagged = c.contains(GOAL_TAG) || c.contains(TASK_TAG) || t.contains(CONCEPT_TAG)
                || t.contains(QUESTION_TAG) || t.contains(CHECKPOINT_TAG) || t.contains(DELIVERABLE_TAG);
        if (!tagged) return null;

        StringBuilder objective = new StringBuilder();
        List<String> tasks = new ArrayList<>();
        String mode = "goal";
        for (String raw : c.split("\\R")) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            if (line.startsWith(TASK_TAG)) { mode = "task"; line = line.substring(TASK_TAG.length()).trim(); if (line.isEmpty()) continue; }
            if (line.startsWith(GOAL_TAG)) { mode = "goal"; line = line.substring(GOAL_TAG.length()).trim(); if (line.isEmpty()) continue; }
            if (mode.equals("task")) {
                Matcher m = NUMBERED.matcher(line);
                String item = m.matches() ? m.group(1).trim() : line;
                if (!item.isEmpty()) tasks.add(item);
            } else {
                if (objective.length() > 0) objective.append(' ');
                objective.append(line);
            }
        }

        List<String> concepts = new ArrayList<>();
        List<String> questions = new ArrayList<>();
        List<String> extra = new ArrayList<>();
        StringBuilder checkpoint = new StringBuilder(), deliverable = new StringBuilder();
        String tmode = "memo";
        for (String raw : t.split("\\R")) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            if (line.startsWith(CONCEPT_TAG)) {
                tmode = "memo";
                for (String x : line.substring(CONCEPT_TAG.length()).split(",")) if (!x.isBlank()) concepts.add(x.trim());
                continue;
            }
            if (line.startsWith(QUESTION_TAG)) {
                tmode = "question";
                String rest = line.substring(QUESTION_TAG.length()).trim();
                if (!rest.isEmpty()) questions.add(stripDash(rest));
                continue;
            }
            if (line.startsWith(CHECKPOINT_TAG)) { tmode = "checkpoint"; append(checkpoint, line.substring(CHECKPOINT_TAG.length())); continue; }
            if (line.startsWith(DELIVERABLE_TAG)) { tmode = "deliverable"; append(deliverable, line.substring(DELIVERABLE_TAG.length())); continue; }
            switch (tmode) {
                case "question" -> {
                    Matcher m = DASHED.matcher(line);
                    if (m.matches()) questions.add(m.group(1).trim());
                    else if (!questions.isEmpty()) questions.set(questions.size() - 1, questions.get(questions.size() - 1) + " " + line);
                    else questions.add(line);
                }
                case "checkpoint" -> append(checkpoint, line);
                case "deliverable" -> append(deliverable, line);
                default -> extra.add(line);
            }
        }
        return new Sections(objective.toString().trim(), tasks, concepts, questions,
                checkpoint.toString().trim(), deliverable.toString().trim(), extra);
    }

    /** 저장된 플래너를 구조화 → 정규화. 로드맵 형식이 아니거나 비어 있으면 null. */
    static DayContent normalizeStored(Planner p) {
        Sections s = parse(p.getContent(), p.getTmi());
        if (s == null || s.isEmpty()) return null;
        return LearningDayNormalizer.normalize(new DayInput(p.getTitle(), p.getSubject(), s.objective(), s.tasks(),
                s.concepts(), s.questions(), s.checkpoint(), s.deliverable()));
    }

    private static String stripDash(String s) { Matcher m = DASHED.matcher(s); return m.matches() ? m.group(1).trim() : s.trim(); }

    private static void append(StringBuilder sb, String s) {
        String v = s == null ? "" : s.trim();
        if (v.isEmpty()) return;
        if (sb.length() > 0) sb.append(' ');
        sb.append(v);
    }
}
