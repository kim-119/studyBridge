package com.studybridge.api.util;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 로드맵 day(→ 플래너 content/tmi) 의 사용자 노출 문장을 "의미 단위"로 재구성하는 결정적 정규화기.
 *
 * <p>AI07 로드맵 생성기는 PDF 본문 문장("관측된데이터를통해…추정하는것")을 core_concepts 로 흘리고,
 * 그 문자열을 objective/task/복습 질문/체크포인트/산출물 템플릿("{concept}을(를) … 중심으로 학습한다",
 * "{subject}에서 • {concept}을(를) 사용하는 이유는?")에 그대로 끼워 넣는다. 결과는 띄어쓰기 없는 설명문이
 * 개념명 자리에 들어간 깨진 문장, 조사 보정 표기, 불릿, 서로 다른 학습 범주(회귀/분류/클러스터링)의 혼합이다.
 *
 * <p>원칙(도메인 문자열 하드코딩 없음)
 * <ol>
 *   <li><b>개념 정규화</b>: core_concepts 는 {@link LearningConceptValidator#isConceptLike(String)} 형태 검증을
 *       통과한 명사구만 남기고, 설명문 조각은 거부한다. 개념은 day 의 실제 주제(title)·objective 의 대상구
 *       ("{subject}의 {concept}")에서 구조적으로 얻는다.</li>
 *   <li><b>범주 검증</b>: 형태는 개념이어도 day 의 정체성(주제어·과목)과 어휘적으로 이어지지 않는 개념은
 *       무관한 범주로 보고 제외한다(연관 개념을 통한 전이 허용). 그 개념으로 만든 문장은 day 주제어로 재구성한다.</li>
 *   <li><b>문장 재구성</b>: 거부/무관 조각은 주제어로 치환하고, 조사 보정 표기는 받침으로 확정하며, 불릿·메타 괄호를
 *       제거하고, 서술문은 마침표·의문문은 물음표로 완결한다. "(주차 흐름: X)" 는 별도의 완결 문장으로 옮긴다.</li>
 * </ol>
 */
public final class LearningDayNormalizer {

    private LearningDayNormalizer() {}

    /** 로드맵 day 원본(메타데이터 노이즈 정제 후). tasks 는 "제목: 설명" 또는 제목만. */
    public record DayInput(String title, String subject, String objective, List<String> tasks,
                           List<String> coreConcepts, List<String> reviewQuestions, String checkpoint, String deliverable) {}

    /** 정규화 결과. rejectedFragments/unrelatedConcepts 는 로그·통계용. */
    public record DayContent(String topic, String subject, String objective, String weekTheme, List<String> tasks,
                             List<String> concepts, List<String> reviewQuestions, String checkpoint, String deliverable,
                             List<String> rejectedFragments, List<String> unrelatedConcepts) {
        public boolean hasRewrites() { return !rejectedFragments.isEmpty() || !unrelatedConcepts.isEmpty(); }
    }

    /** 로드맵 objective 템플릿: "[X의] Y을/를 Z 중심으로 학습한다" → 대상구 X의 Y. */
    private static final Pattern GOAL_TEMPLATE = Pattern.compile(
            "^(?<object>.+?)(?:을|를|을\\(를\\)|를\\(을\\))\\s+(?<method>.+?)\\s*(?:중심으로|위주로)\\s*(?:학습|공부|정리|연습|익히)[가-힣]*[.!]?$");
    private static final Pattern POSSESSIVE_SPLIT = Pattern.compile("(?<=[가-힣\\p{Alnum})])의\\s+");
    private static final Pattern OR_SPLIT = Pattern.compile("\\s+또는\\s+");
    private static final int MAX_CONCEPTS = 6;
    private static final String DEFAULT_TOPIC = "학습 계획";

    public static DayContent normalize(DayInput in) {
        Objects.requireNonNull(in, "in");
        String topic = LearningConceptValidator.topicOf(KoreanTextNormalizer.clean(in.title()));
        if (topic.isBlank()) topic = DEFAULT_TOPIC;
        String subject = subjectOf(in.subject());

        // 1) 개념 형태 검증(빈 슬롯 흔적으로 남은 끝 조사 "MVVM 1의" 는 뗀다)
        List<String> candidates = new ArrayList<>();
        for (String c : safe(in.coreConcepts())) candidates.add(stripTrailingPossessive(c));
        LearningConceptValidator.Split split = LearningConceptValidator.split(candidates);
        List<String> fragments = new ArrayList<>(split.rejected());

        // 주제어의 개념형("선형회귀란?" → "선형회귀"). 치환어는 개념형 주제어 → 과목명 → 주제어 순.
        String topicConcept = topicConcept(topic);
        String replacement = topicConcept != null ? topicConcept : subject != null ? subject : topic;

        // 2) objective 대상구에서 구조적으로 개념 후보 추출("선형회귀의 고급 회귀 기법" → 선형회귀, 고급 회귀 기법)
        String[] objParts = KoreanTextNormalizer.splitWeekTheme(safeStr(in.objective()));
        String objectiveBody = LearningConceptValidator.scrub(objParts[0], fragments, replacement);
        List<String> objectiveConcepts = objectiveConcepts(objectiveBody);

        // 3) 범주 검증. day 정체성 = 주제어·과목·objective 대상구. 설명문 조각이 섞인 목록은 PDF 본문에서 긁어온
        //    것이라 신뢰하지 않으므로, 정체성과 어휘적으로 이어지는 개념만 남긴다(연관 개념을 통한 전이 허용).
        //    조각이 없는(생성기가 개념만 낸) 목록은 그대로 신뢰한다 — 어휘 겹침만으로 정당한 개념을 버리지 않기 위해서다.
        List<String> anchors = new ArrayList<>();
        anchors.add(topic);
        if (topicConcept != null) anchors.add(topicConcept);
        if (subject != null) anchors.add(subject);
        anchors.addAll(objectiveConcepts);
        List<String> unrelated = new ArrayList<>();
        if (!fragments.isEmpty()) {
            List<String> related = relatedClosure(split.accepted(), anchors);
            for (String c : split.accepted()) if (!containsNormalized(related, c)) unrelated.add(c);
        }

        List<String> replacements = new ArrayList<>(fragments);
        replacements.addAll(unrelated);

        // 4) 최종 개념 목록: 주제어 → objective 대상구 개념 → 나머지 연관 개념
        List<String> concepts = new ArrayList<>();
        if (topicConcept != null) concepts.add(topicConcept);
        for (String c : objectiveConcepts) addConcept(concepts, c);
        for (String c : split.accepted()) if (!containsNormalized(unrelated, c)) addConcept(concepts, c);
        if (concepts.size() > MAX_CONCEPTS) concepts = new ArrayList<>(concepts.subList(0, MAX_CONCEPTS));

        // 5) 문장 재구성
        String objective = KoreanTextNormalizer.ensureSentenceEnd(rewrite(objectiveBody, replacements, replacement));
        if (objective.isBlank()) objective = replacement + "의 핵심 원리를 이해한다.";
        String weekTheme = objParts[1] == null ? null : KoreanTextNormalizer.clean(objParts[1]);
        if (weekTheme != null && weekTheme.isBlank()) weekTheme = null;
        if (weekTheme != null) objective = objective + " 이번 주는 " + weekTheme + " 단계이다.";

        List<String> tasks = new ArrayList<>();
        for (String t : safe(in.tasks())) {
            String r = rewrite(t, replacements, replacement);
            if (r.isBlank()) continue;
            if (r.contains(": ")) r = KoreanTextNormalizer.ensureSentenceEnd(r);
            addUnique(tasks, r);
        }

        List<String> questions = new ArrayList<>();
        for (String q : safe(in.reviewQuestions())) {
            String r = rewrite(q, replacements, replacement);
            if (r.isBlank()) continue;
            addUnique(questions, KoreanTextNormalizer.ensureQuestionEnd(r));
        }

        String checkpoint = rewrite(safeStr(in.checkpoint()), replacements, replacement);
        if (!checkpoint.isBlank()) checkpoint = KoreanTextNormalizer.ensureSentenceEnd(checkpoint);

        String deliverable = dedupeAlternatives(rewrite(safeStr(in.deliverable()), replacements, replacement));
        if (!deliverable.isBlank() && deliverable.matches(".*[가-힣]다$")) deliverable = deliverable + ".";

        return new DayContent(topic, subject, objective, weekTheme, tasks, concepts, questions, checkpoint, deliverable,
                List.copyOf(fragments), List.copyOf(unrelated));
    }

    /** 문장 재구성 한 단위: 조각/무관 개념 → 치환어, 빈 개념 슬롯 채움, 불릿·메타 괄호 제거, 조사 확정, 공백 정리. */
    public static String rewrite(String text, Collection<String> replacements, String replacement) {
        if (text == null) return "";
        String s = LearningConceptValidator.scrub(text, replacements, replacement);
        s = fillEmptyConceptSlots(s, replacement);
        return KoreanTextNormalizer.clean(s);
    }

    // 개념 슬롯이 빈 문자열로 채워진 템플릿 흔적: "구조 비교: 을(를) 대체…", "MVVM 1의를 …", "MVVM 1에서를 …", "의 핵심을 …"
    private static final Pattern ORPHAN_JOSA_PAIR = Pattern.compile(
            "(?<=^|[:\\s(（])(?=(?:을\\(를\\)|를\\(을\\)|이\\(가\\)|가\\(이\\)|은\\(는\\)|는\\(은\\)|과\\(와\\)|와\\(과\\)|으로\\(로\\)|로\\(으로\\))(?:\\s|$))");
    // "MVVM 1의를": 비한글 글자 뒤의 관형격 '의' + 조사(한글 뒤 '의'는 "정의가/논의를" 처럼 단어 일부일 수 있어 제외).
    // "MVVM 1에서를": '에서/에게' 뒤에 목적격·주격이 바로 오는 경우("에서는" 은 정상 문장이므로 제외).
    private static final Pattern PARTICLE_THEN_BARE_JOSA = Pattern.compile(
            "(?:(?<=[\\p{Alnum})])(?<![가-힣])(?<lead>의)(?<josa>을|를|이|가|은|는)"
            + "|(?<=[가-힣\\p{Alnum})])(?<lead2>에서|에게)(?<josa2>을|를|이|가))(?=\\s|$)");
    private static final Pattern ORPHAN_POSSESSIVE = Pattern.compile("(?<=^|[:\\s(（])의(?=\\s)");

    /** 빈 개념 슬롯을 치환어로 채운다(조사는 보정 표기로 바꿔 두고 이후 clean 이 받침으로 확정). */
    static String fillEmptyConceptSlots(String s, String replacement) {
        if (s == null || replacement == null || replacement.isBlank()) return s == null ? "" : s;
        String r = replacement.trim();
        String out = ORPHAN_JOSA_PAIR.matcher(s).replaceAll(Matcher.quoteReplacement(r));
        Matcher m = PARTICLE_THEN_BARE_JOSA.matcher(out);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String lead = m.group("lead") != null ? m.group("lead") : m.group("lead2");
            String josa = m.group("josa") != null ? m.group("josa") : m.group("josa2");
            String pair = switch (josa) {
                case "을", "를" -> "을(를)"; case "이", "가" -> "이(가)"; default -> "은(는)";
            };
            m.appendReplacement(sb, Matcher.quoteReplacement(lead + " " + r + pair));
        }
        m.appendTail(sb);
        out = sb.toString();
        out = ORPHAN_POSSESSIVE.matcher(out).replaceAll(Matcher.quoteReplacement(r + "의"));
        return out;
    }

    /** objective 대상구("X의 Y을 Z 중심으로 학습한다")에서 개념 형태의 항목만 추출. 템플릿이 아니면 빈 목록. */
    static List<String> objectiveConcepts(String objectiveBody) {
        List<String> out = new ArrayList<>();
        if (objectiveBody == null) return out;
        String s = KoreanTextNormalizer.clean(objectiveBody);
        Matcher m = GOAL_TEMPLATE.matcher(s);
        if (!m.matches()) return out;
        for (String part : POSSESSIVE_SPLIT.split(m.group("object").trim())) {
            String p = stripTrailingPossessive(part);
            if (!p.isEmpty() && LearningConceptValidator.isConceptLike(p)) addUnique(out, p);
        }
        return out;
    }

    /** anchors 와 어휘적으로 이어지는 개념의 전이 폐쇄(연관 개념을 통해 이어지면 포함). */
    static List<String> relatedClosure(List<String> pool, List<String> anchors) {
        List<String> related = new ArrayList<>();
        List<String> seeds = new ArrayList<>(anchors);
        boolean changed = true;
        while (changed) {
            changed = false;
            for (String c : pool) {
                if (containsNormalized(related, c)) continue;
                if (LearningConceptValidator.isLexicallyRelated(c, seeds) || LearningConceptValidator.duplicatesAny(c, seeds)) {
                    related.add(c); seeds.add(c); changed = true;
                }
            }
        }
        return related;
    }

    /**
     * "MVVM 1의", "API의" 처럼 한글이 아닌 글자 뒤에 붙은 채 남은 관형격 조사를 뗀다(빈 개념 슬롯 템플릿 흔적).
     * 한글 뒤의 "의"("정의", "논의", "회귀 문제 정의")는 단어의 일부일 수 있어 건드리지 않는다.
     */
    static String stripTrailingPossessive(String s) {
        if (s == null) return "";
        return s.trim().replaceAll("(?<=[\\p{Alnum})])(?<![가-힣])의$", "").trim();
    }

    /** 주제어의 개념형: 끝 문장 부호·"이란/란" 을 뗀 형태가 개념명이면 그것, 아니면 null. */
    static String topicConcept(String topic) {
        if (topic == null) return null;
        String t = topic.trim().replaceAll("[?？!.。]+$", "").trim();
        t = t.replaceAll("(?<=[가-힣])(이란|란)$", "").trim();
        if (t.isEmpty()) return null;
        return LearningConceptValidator.isConceptLike(t) ? t : null;
    }

    private static String subjectOf(String subject) {
        if (subject == null || subject.isBlank()) return null;
        String s = KoreanTextNormalizer.clean(LearningContentSanitizer.clean(subject));
        return s.isBlank() ? null : s;
    }

    /** "X 정리 노트 또는 X 비교 표" 처럼 치환 후 같은 대안이 반복되면 하나만 남긴다. */
    static String dedupeAlternatives(String s) {
        if (s == null || !s.contains(" 또는 ")) return s == null ? "" : s;
        List<String> parts = new ArrayList<>();
        for (String p : OR_SPLIT.split(s)) addUnique(parts, p.trim());
        return String.join(" 또는 ", parts);
    }

    private static void addConcept(List<String> concepts, String c) {
        for (String e : concepts) if (LearningConceptValidator.isNearDuplicate(e, c)) return;
        concepts.add(c);
    }

    private static void addUnique(List<String> list, String v) {
        if (v == null || v.isBlank()) return;
        if (!containsNormalized(list, v)) list.add(v.trim());
    }

    private static boolean containsNormalized(List<String> list, String v) {
        String n = LearningConceptValidator.normalize(v);
        for (String e : list) if (LearningConceptValidator.normalize(e).equals(n)) return true;
        return false;
    }

    private static List<String> safe(List<String> l) { return l == null ? List.of() : l; }
    private static String safeStr(String s) { return s == null ? "" : s; }
}
