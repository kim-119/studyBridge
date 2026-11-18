package com.studybridge.api.service.recommendation;

import com.studybridge.api.service.recommendation.RecommendationCandidate.Evidence;

import java.util.ArrayList;
import java.util.List;

import static com.studybridge.api.service.recommendation.RecommendationCandidate.*;

/**
 * 문서 기반(Document-based) 추천 — 원본 플래너가 없는 학습자료(PDF, 플래너가 삭제된 PLANNER 보관 자료, 학습일지).
 *
 * <p>문서의 개념 복습·실습(퀴즈)·심화·오답 복습만 다룬다. 로드맵 단계나 "N주차 M일" 처럼 확인되지 않은 진도 단계로
 * 표현하지 않는다(유형 접두어 DOCUMENT_*, 제목에 "문서 기반" 출처 표기는 UI 가 담당).</p>
 */
public final class DocumentRecommender {

    static final int MAX_CONCEPTS = 3;

    public record StudyNote(List<String> keywords, List<String> coreContents, List<String> studyPoints, List<String> studyQuestions) {}

    public record Context(Long materialId, String title, String materialType, List<String> keywords, StudyNote studyNote,
                          Long latestQuizId, Integer latestQuizScore, int quizCount,
                          List<UserPlannerTaskRecommender.NoteRef> wrongNotes, String userNextPlan) {}

    public record Output(List<RecommendationCandidate> candidates, String status, String note) {}

    private DocumentRecommender() {}

    public static Output recommend(Context c) {
        List<RecommendationCandidate> out = new ArrayList<>();
        Evidence docEv = new Evidence("MATERIAL", String.valueOf(c.materialId()), c.title());
        String label = UserPlannerTaskRecommender.trim(c.title() == null ? "이 문서" : c.title(), 40);

        List<String> concepts = concepts(c);
        if (!concepts.isEmpty()) {
            boolean fromNote = c.studyNote() != null && !isEmpty(c.studyNote().keywords());
            Evidence ev = fromNote ? new Evidence("STUDY_NOTE", String.valueOf(c.materialId()), "AI 핵심 요약 노트 키워드")
                    : new Evidence("MATERIAL_KEYWORDS", String.valueOf(c.materialId()), "자료 키워드");
            out.add(rule(DOCUMENT_CONCEPT_REVIEW, "핵심 개념 복습: " + String.join(", ", concepts),
                    "문서에서 추출된 핵심 개념을 스스로 설명할 수 있는지 점검합니다.",
                    "concepts", List.of(docEv, ev), false, null));
        }

        if (c.quizCount() == 0) {
            out.add(rule(DOCUMENT_PRACTICE, label + " 확인 퀴즈 풀기",
                    "이 문서로 푼 퀴즈 기록이 없어 이해도를 알 수 없습니다. 퀴즈로 먼저 확인합니다.",
                    "quiz:first", List.of(docEv), false, null));
        } else if (c.latestQuizScore() != null && c.latestQuizScore() < UserPlannerTaskRecommender.HIGH_SCORE) {
            out.add(rule(DOCUMENT_REVIEW, label + " 퀴즈 다시 풀기",
                    "최근 퀴즈 " + c.latestQuizScore() + "점 — 틀린 부분을 복습한 뒤 다시 풀어 이해를 확인합니다.",
                    "quiz:retry:" + c.latestQuizId(), List.of(docEv, new Evidence("QUIZ", String.valueOf(c.latestQuizId()), c.latestQuizScore() + "점")),
                    false, null));
        } else if (c.latestQuizScore() != null) {
            String point = c.studyNote() == null || isEmpty(c.studyNote().studyPoints()) ? null : c.studyNote().studyPoints().get(0);
            out.add(rule(DOCUMENT_DEEP_DIVE, point != null ? "심화 학습: " + UserPlannerTaskRecommender.trim(point, 80) : label + " 심화·응용 학습",
                    "최근 퀴즈 " + c.latestQuizScore() + "점으로 기본 이해가 확인되어 심화 내용으로 확장합니다.",
                    "deep", List.of(docEv, new Evidence("QUIZ", String.valueOf(c.latestQuizId()), c.latestQuizScore() + "점")), false, null));
        }

        if (c.studyNote() != null && !isEmpty(c.studyNote().studyQuestions())) {
            String q = c.studyNote().studyQuestions().get(0);
            out.add(rule(DOCUMENT_PRACTICE, "학습 질문에 답해보기: " + UserPlannerTaskRecommender.trim(q, 80),
                    "문서 분석에서 나온 학습 질문에 직접 답하며 이해를 검증합니다.",
                    "question:0", List.of(docEv, new Evidence("STUDY_NOTE", String.valueOf(c.materialId()), "학습 질문")), false, null));
        }

        if (c.wrongNotes() != null) {
            c.wrongNotes().stream().limit(UserPlannerTaskRecommender.MAX_WRONG_NOTES).forEach(n -> out.add(rule(WRONG_ANSWER_REVIEW,
                    "오답 복습: " + UserPlannerTaskRecommender.trim(n.title(), 60),
                    "이 문서로 푼 퀴즈의 오답노트입니다.", "note:" + n.id(),
                    List.of(new Evidence("REVIEW_NOTE", String.valueOf(n.id()), n.title())), false, null)));
        }

        if (c.userNextPlan() != null && !c.userNextPlan().isBlank()) {
            out.add(rule(DOCUMENT_REVIEW, "학습일지의 다음 계획: " + UserPlannerTaskRecommender.trim(c.userNextPlan(), 80),
                    "학습일지에 직접 적은 다음 계획입니다. 계획은 아직 완료되지 않은 할 일로 다룹니다.",
                    "next-plan", List.of(docEv), false, null));
        }

        if (out.isEmpty()) {
            return new Output(out, "NO_DATA", "문서에서 추천 근거(개념·퀴즈·오답)를 찾지 못했습니다. AI 핵심 요약 노트나 퀴즈를 먼저 만들어 주세요.");
        }
        return new Output(out, "OK", null);
    }

    static List<String> concepts(Context c) {
        List<String> src = c.studyNote() != null && !isEmpty(c.studyNote().keywords()) ? c.studyNote().keywords() : c.keywords();
        List<String> out = new ArrayList<>();
        if (src == null) return out;
        for (String k : src) {
            if (k == null) continue;
            String t = k.trim();
            if (t.length() < 2 || t.length() > 30 || out.contains(t)) continue;
            out.add(t);
            if (out.size() >= MAX_CONCEPTS) break;
        }
        return out;
    }

    private static boolean isEmpty(List<?> l) {
        return l == null || l.isEmpty();
    }
}
