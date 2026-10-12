package com.studybridge.api.service.recommendation;

import com.studybridge.api.service.recommendation.RecommendationCandidate.Evidence;
import com.studybridge.api.service.recommendation.TextbookToc.ChapterRef;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static com.studybridge.api.service.recommendation.RecommendationCandidate.*;

/**
 * 사용자 플래너 — Learning Task 추천(결정적 규칙). "현재 계획에서 다음에 수행할 구체적 학습 과제" 를 고른다.
 *
 * <ul>
 *   <li><b>계획 입력은 완료 기록이 아니다.</b> "선형대수 2장 학습하기" 라는 문장은 할 일이다. 완료 여부는 체크리스트
 *       (plan_analysis_item.completed) 이행 기록으로만 판단한다. 완료 기록이 없으면 다음 장 대신 현재 장을 다지는 과제를 낸다.</li>
 *   <li>다음 장: 교재 목차가 확인되면 실제 장 제목을 쓰고, 확인되지 않으면 장 번호만 쓰고 verificationRequired=true.
 *       목차에 없는 장(마지막 장 다음)은 추천하지 않는다.</li>
 *   <li>퀴즈 점수·오답노트가 있으면 취약 개념 보완/오답 복습을, 점수가 높으면 응용을 낸다. 점수가 없으면 숙련도를 추정하지 않는다.</li>
 *   <li>이미 다음 일정에 같은 장이 계획되어 있으면 다음 장 후보를 내지 않는다(일정 중복 방지).</li>
 * </ul>
 */
public final class UserPlannerTaskRecommender {

    public static final int HIGH_SCORE = 80;
    public static final int LOW_SCORE = 60;
    static final int MAX_WRONG_NOTES = 2;

    public record Textbook(Long materialId, String title, TextbookToc toc) {}

    public record NoteRef(Long id, String title) {}

    public record Context(Long plannerId, String title, String subject, String content, LocalDate plannerDate,
                          int checklistTotal, int checklistCompleted, Integer focusMinutes,
                          Textbook textbook, Long latestQuizId, Integer latestQuizScore,
                          List<NoteRef> wrongNotes, List<String> upcomingPlanTexts) {
        boolean completed() { return checklistTotal > 0 && checklistCompleted == checklistTotal; }
    }

    public record Output(List<RecommendationCandidate> candidates, String status, String note) {}

    public static final String STATUS_OK = "OK";
    public static final String STATUS_NO_DATA = "NO_DATA";

    private UserPlannerTaskRecommender() {}

    public static Output recommend(Context c) {
        String planText = join(c.title(), c.content());
        Optional<ChapterRef> ref = TextbookToc.chapterRef(planText);
        String unit = unitLabel(c, ref.orElse(null));
        if (unit == null) {
            return new Output(List.of(), STATUS_NO_DATA, "계획에 과목·내용이 없어 다음 과제를 정할 근거가 없습니다.");
        }
        Evidence plannerEv = new Evidence("PLANNER", String.valueOf(c.plannerId()), c.title());
        String progress = c.checklistTotal() == 0 ? "체크리스트 없음" : "체크리스트 " + c.checklistCompleted() + "/" + c.checklistTotal();
        Evidence progressEv = new Evidence("PLAN_ANALYSIS", String.valueOf(c.plannerId()), progress);
        List<RecommendationCandidate> out = new ArrayList<>();

        if (!c.completed()) {
            String why = "현재 계획의 학습 완료 기록이 없습니다(" + progress + "). 계획 문장은 완료로 보지 않으므로 다음 장보다 현재 범위를 먼저 다집니다.";
            out.add(rule(CONCEPT_REVIEW, unit + " 핵심 개념 정리", why, "cur:" + key(ref), List.of(plannerEv, progressEv), false, null));
            out.add(rule(PRACTICE, unit + " 연습문제 풀이", "개념 정리 직후 문제를 풀어 이해 여부를 확인합니다.",
                    "cur-practice:" + key(ref), List.of(plannerEv, progressEv), false, null));
        } else {
            nextChapter(c, ref.orElse(null), plannerEv, progressEv).ifPresent(out::add);
            if (c.latestQuizScore() == null) {
                out.add(rule(PRACTICE, unit + " 확인 퀴즈 풀기",
                        "체크리스트는 완료했지만 이해도(숙련도) 측정 기록이 없습니다. 완료와 숙련은 별개이므로 퀴즈로 확인합니다.",
                        "verify:" + key(ref), List.of(plannerEv, progressEv), false, null));
            } else if (c.latestQuizScore() >= HIGH_SCORE) {
                out.add(rule(APPLICATION, unit + " 응용·실습 과제",
                        "최근 퀴즈 " + c.latestQuizScore() + "점으로 기본 이해가 확인되어 응용 단계로 확장합니다.",
                        "apply:" + key(ref), List.of(plannerEv, quizEv(c)), false, null));
            }
        }

        if (c.latestQuizScore() != null && c.latestQuizScore() < LOW_SCORE && (c.wrongNotes() == null || c.wrongNotes().isEmpty())) {
            out.add(rule(PREREQUISITE_GAP, unit + " 취약 개념 보완",
                    "최근 퀴즈 " + c.latestQuizScore() + "점 — 다음 내용으로 넘어가기 전에 틀린 개념의 선행 내용을 보완합니다.",
                    "gap:" + key(ref), List.of(plannerEv, quizEv(c)), false, null));
        }
        if (c.wrongNotes() != null) {
            c.wrongNotes().stream().limit(MAX_WRONG_NOTES).forEach(n -> out.add(rule(WRONG_ANSWER_REVIEW,
                    "오답 복습: " + trim(n.title(), 60),
                    "이 교재로 푼 퀴즈의 오답노트가 남아 있습니다. 틀린 문항을 다시 풀어 개념을 바로잡습니다.",
                    "note:" + n.id(), List.of(new Evidence("REVIEW_NOTE", String.valueOf(n.id()), n.title())), false, null)));
        }
        return new Output(out, STATUS_OK, null);
    }

    /** 완료된 장의 다음 장. 목차 확인 시 실제 제목, 미확인 시 번호만 + 검증 필요. 이미 계획된 장이면 생략. */
    static Optional<RecommendationCandidate> nextChapter(Context c, ChapterRef ref, Evidence plannerEv, Evidence progressEv) {
        if (ref == null) return Optional.empty();
        int next = ref.number() + 1;
        if (alreadyPlanned(c.upcomingPlanTexts(), next)) return Optional.empty();
        String prefix = ref.prefix().isBlank() ? nz(c.subject()) : ref.prefix();
        String head = (prefix.isBlank() ? "" : prefix + " ") + next + "장";
        TextbookToc toc = c.textbook() == null ? null : c.textbook().toc();
        String why = ref.number() + "장의 체크리스트를 모두 완료했습니다.";
        if (toc != null && toc.verified()) {
            Optional<TextbookToc.Entry> e = toc.chapter(next);
            if (e.isEmpty()) {
                // 목차상 다음 장이 없다(마지막 장) → 다음 장을 만들어 내지 않는다.
                return Optional.empty();
            }
            Evidence tocEv = new Evidence("TOC", c.textbook().materialId() + ":" + next, next + "장 " + e.get().title());
            return Optional.of(rule(NEXT_CHAPTER, head + " " + e.get().title() + " 학습",
                    why + " 교재 목차에서 확인된 다음 장입니다.", "ch" + next, List.of(plannerEv, progressEv, tocEv), false, null));
        }
        String note = c.textbook() == null
                ? "연결된 교재가 없어 " + next + "장의 존재와 제목을 확인하지 못했습니다. 교재 목차를 확인한 뒤 승인하세요."
                : "교재에서 목차를 확인하지 못해 " + next + "장의 제목은 표시하지 않습니다. 목차를 확인한 뒤 승인하세요.";
        return Optional.of(rule(NEXT_CHAPTER, head + " 학습", why, "ch" + next, List.of(plannerEv, progressEv), true, note));
    }

    static boolean alreadyPlanned(List<String> upcoming, int chapter) {
        if (upcoming == null) return false;
        for (String t : upcoming) {
            Optional<ChapterRef> r = TextbookToc.chapterRef(t);
            if (r.isPresent() && r.get().number() == chapter) return true;
        }
        return false;
    }

    /** "선형대수 2장" 처럼 장 참조가 있으면 그 단위, 없으면 과목 → 계획 제목. 둘 다 의미 없으면 null. */
    static String unitLabel(Context c, ChapterRef ref) {
        if (ref != null) {
            String prefix = ref.prefix().isBlank() ? nz(c.subject()) : ref.prefix();
            return ((prefix.isBlank() ? "" : prefix + " ") + ref.number() + "장").trim();
        }
        if (!nz(c.subject()).isBlank()) return c.subject().trim();
        String t = nz(c.title()).replaceAll("^\\[[^\\]]*\\]\\s*", "").trim();
        if (t.isBlank() || t.equals("공부 플래너")) return null;
        return trim(t.replaceAll("\\s*(학습|공부)\\s*(하기|한다|할 것)?$", ""), 40);
    }

    private static Evidence quizEv(Context c) {
        return new Evidence("QUIZ", String.valueOf(c.latestQuizId()), "최근 퀴즈 " + c.latestQuizScore() + "점");
    }

    private static String key(Optional<ChapterRef> ref) {
        return ref.map(r -> "ch" + r.number()).orElse("plan");
    }

    private static String key(ChapterRef ref) {
        return ref == null ? "plan" : "ch" + ref.number();
    }

    private static String join(String a, String b) {
        return (nz(a) + " " + nz(b)).trim();
    }

    private static String nz(String s) {
        return s == null ? "" : s;
    }

    static String trim(String s, int max) {
        if (s == null) return "";
        String t = s.trim();
        return t.length() <= max ? t : t.substring(0, max - 1) + "…";
    }
}
