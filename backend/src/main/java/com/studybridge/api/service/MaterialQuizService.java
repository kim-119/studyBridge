package com.studybridge.api.service;

import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.service.MaterialQuizScoreService.StoredScore;
import com.studybridge.api.util.MaterialQuizContent;
import com.studybridge.api.util.MaterialQuizContent.InternalQuestion;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Set;

/**
 * 자료 퀴즈(MaterialQuiz) 공개 DTO 변환 + 서버 채점 + 점수 조회 + 삭제.
 *
 * <p>보안 원칙: 브라우저는 점수를 결정하지 않는다. 답안(questionId/selectedOptionId)만 받아
 * DB 의 authoritative 정답 키(quiz_data)로 채점하고 Redis 에 저장한다. 정답은 제출 결과에서만 공개된다.</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class MaterialQuizService {

    private final MaterialRepository materialRepository;
    private final MaterialQuizRepository quizRepository;
    private final MaterialQuizScoreService scoreService;

    // ── 공개 DTO ────────────────────────────────────────────────────────────

    /** quizData → 정답 없는 공개 문항 목록. */
    public static List<QuizDTO.PublicQuestion> toPublicQuestions(Long quizId, String quizData) {
        List<QuizDTO.PublicQuestion> out = new ArrayList<>();
        for (InternalQuestion q : MaterialQuizContent.parse(quizId, quizData)) {
            List<QuizDTO.PublicOption> options = new ArrayList<>();
            for (int i = 0; i < q.getOptions().size(); i++) {
                options.add(QuizDTO.PublicOption.builder()
                        .optionId(i < q.getOptionIds().size() ? q.getOptionIds().get(i) : MaterialQuizContent.optionId(i))
                        .text(q.getOptions().get(i))
                        .build());
            }
            out.add(QuizDTO.PublicQuestion.builder()
                    .questionId(q.getQuestionId())
                    .index(q.getIndex())
                    .question(q.getQuestion())
                    .questionType(q.getQuestionType())
                    .answerType(q.getAnswerType())
                    .options(options)
                    .difficulty(q.getDifficulty())
                    .gradable(q.isGradable())
                    .build());
        }
        return out;
    }

    // ── 채점 ────────────────────────────────────────────────────────────────

    /**
     * 서버 채점. 흐름: 사용자(JWT) → 퀴즈 조회 → materialId 소속 검증 → 소유자 검증 → 정답 키 조회 → 문항별 채점
     * → score → Redis 저장 → 결과 반환. 알 수 없는 questionId(다른 퀴즈 접두어 포함)/optionId 는 400.
     */
    @Transactional
    public QuizDTO.ResultResponse submit(Long userId, Long materialId, Long quizId, QuizDTO.SubmitRequest request) {
        MaterialQuiz quiz = loadOwnedQuiz(userId, materialId, quizId);
        List<InternalQuestion> questions = MaterialQuizContent.parse(quiz.getQuizId(), quiz.getQuizData());
        if (questions.isEmpty()) {
            throw new IllegalStateException("이 퀴즈에는 채점할 문항이 없습니다.");
        }

        Map<String, InternalQuestion> byId = new LinkedHashMap<>();
        for (InternalQuestion q : questions) byId.put(q.getQuestionId(), q);

        Map<String, String> selected = new LinkedHashMap<>();
        List<QuizDTO.SubmittedAnswer> answers = request == null || request.getAnswers() == null
                ? List.of() : request.getAnswers();
        Set<String> seen = new HashSet<>();
        for (QuizDTO.SubmittedAnswer a : answers) {
            if (a == null || a.getQuestionId() == null) continue;
            InternalQuestion q = byId.get(a.getQuestionId().trim());
            if (q == null) {
                throw new IllegalArgumentException("이 퀴즈에 속하지 않는 문항입니다: " + a.getQuestionId());
            }
            if (!seen.add(q.getQuestionId())) {
                throw new IllegalArgumentException("같은 문항에 답안이 두 번 제출되었습니다: " + a.getQuestionId());
            }
            List<String> picked = a.effectiveOptionIds();
            if (picked.isEmpty()) continue; // 미응답
            if (picked.size() > 1) {
                throw new IllegalArgumentException("단일 선택 문항에 보기 여러 개가 제출되었습니다: " + a.getQuestionId());
            }
            String opt = picked.get(0);
            Integer optIdx = q.indexOfOption(opt);
            if (optIdx == null) {
                throw new IllegalArgumentException("유효하지 않은 보기입니다: " + a.getQuestionId() + "/" + opt);
            }
            selected.put(q.getQuestionId(), q.getOptionIds().get(optIdx));
        }

        StoredScore previous = scoreService.find(quiz.getQuizId(), userId);
        int attempt = previous != null && previous.getAttempt() != null ? previous.getAttempt() + 1 : 1;
        QuizDTO.ResultResponse result = grade(quiz, userId, questions, selected, attempt, LocalDateTime.now());

        StoredScore stored = StoredScore.builder()
                .quizId(quiz.getQuizId())
                .userId(userId)
                .score(result.getScore())
                .correctCount(result.getCorrectCount())
                .totalQuestions(result.getTotalQuestions())
                .answeredCount(result.getAnsweredCount())
                .attempt(attempt)
                .submittedAt(result.getSubmittedAt())
                .selected(selected)
                .build();
        result.setPersisted(scoreService.save(stored));
        log.info("[QUIZ_SCORE] quizId={} userId={} score={} correct={}/{} attempt={} persisted={}",
                quiz.getQuizId(), userId, result.getScore(), result.getCorrectCount(), result.getTotalQuestions(),
                attempt, result.getPersisted());
        return result;
    }

    /** 최근 채점 결과(Redis 의 선택 답안을 DB 정답 키로 재채점해 결과 생성). 없으면 404. */
    public QuizDTO.ResultResponse latestResult(Long userId, Long materialId, Long quizId) {
        MaterialQuiz quiz = loadOwnedQuiz(userId, materialId, quizId);
        QuizDTO.ResultResponse r = latestResultOrNull(quiz, userId);
        if (r == null) throw new NoSuchElementException("아직 제출한 답안이 없습니다.");
        return r;
    }

    /** 목록 응답에 붙일 최근 결과(없으면 null, Redis 장애도 null). */
    public QuizDTO.ResultResponse latestResultOrNull(MaterialQuiz quiz, Long userId) {
        StoredScore s = scoreService.find(quiz.getQuizId(), userId);
        if (s == null) return null;
        List<InternalQuestion> questions = MaterialQuizContent.parse(quiz.getQuizId(), quiz.getQuizData());
        QuizDTO.ResultResponse r = grade(quiz, userId, questions,
                s.getSelected() == null ? Map.of() : s.getSelected(),
                s.getAttempt() == null ? 1 : s.getAttempt(), s.getSubmittedAt());
        r.setPersisted(true);
        return r;
    }

    /** 점수 = round(correct / gradableTotal * 100). gradableTotal = 0 → 0. */
    static int computeScore(int correct, int total) {
        if (total <= 0) return 0;
        return (int) Math.round(correct * 100.0 / total);
    }

    private QuizDTO.ResultResponse grade(MaterialQuiz quiz, Long userId, List<InternalQuestion> questions,
                                         Map<String, String> selected, int attempt, LocalDateTime submittedAt) {
        int total = 0;
        int correct = 0;
        int answered = 0;
        List<QuizDTO.QuestionResult> results = new ArrayList<>();
        for (InternalQuestion q : questions) {
            String sel = selected.get(q.getQuestionId());
            boolean isAnswered = sel != null;
            boolean gradable = q.isGradable();
            Boolean isCorrect = null;
            if (gradable) {
                total++;
                if (isAnswered) {
                    answered++;
                    isCorrect = sel.equals(q.getCorrectOptionId());
                    if (isCorrect) correct++;
                } else {
                    isCorrect = false;
                }
            }
            results.add(QuizDTO.QuestionResult.builder()
                    .questionId(q.getQuestionId())
                    .index(q.getIndex())
                    .answered(isAnswered)
                    .correct(isCorrect)
                    .gradable(gradable)
                    .selectedOptionIds(sel == null ? new ArrayList<>() : new ArrayList<>(List.of(sel)))
                    .correctOptionIds(gradable ? new ArrayList<>(List.of(q.getCorrectOptionId())) : new ArrayList<>())
                    .explanation(q.getExplanation())
                    .build());
        }
        return QuizDTO.ResultResponse.builder()
                .quizId(quiz.getQuizId())
                .materialId(quiz.getMaterial() != null ? quiz.getMaterial().getMaterialId() : null)
                .userId(userId)
                .score(computeScore(correct, total))
                .correctCount(correct)
                .totalQuestions(total)
                .answeredCount(answered)
                .attempt(attempt)
                .submittedAt(submittedAt)
                .results(results)
                .build();
    }

    // ── 삭제 ────────────────────────────────────────────────────────────────

    /** 자료 소유자만 퀴즈 개별 삭제. DB 삭제(문항은 quiz_data 컬럼) 후 Redis 점수 키 DEL. */
    @Transactional
    public void delete(Long userId, Long materialId, Long quizId) {
        MaterialQuiz quiz = loadOwnedQuiz(userId, materialId, quizId);
        quizRepository.delete(quiz);
        scoreService.deleteForQuiz(quiz.getQuizId());
        log.info("[QUIZ_DELETE] materialId={} quizId={} by userId={}", materialId, quizId, userId);
    }

    // ── 공통 ────────────────────────────────────────────────────────────────

    /** 404(없음) → 404(자료 불일치, 존재 유추 방지) → 403(소유자 아님) 순서로 검증한다. */
    private MaterialQuiz loadOwnedQuiz(Long userId, Long materialId, Long quizId) {
        MaterialQuiz quiz = quizRepository.findById(quizId)
                .orElseThrow(() -> new NoSuchElementException("퀴즈를 찾을 수 없습니다."));
        Material material = quiz.getMaterial();
        if (material == null || materialId == null || !materialId.equals(material.getMaterialId())) {
            throw new NoSuchElementException("이 자료에 속한 퀴즈가 아닙니다.");
        }
        if (userId == null || !userId.equals(material.getUserId())) {
            throw new SecurityException("해당 퀴즈에 대한 권한이 없습니다.");
        }
        Material owned = materialRepository.findById(materialId).orElse(null);
        if (owned == null) throw new NoSuchElementException("자료를 찾을 수 없습니다.");
        return quiz;
    }
}
