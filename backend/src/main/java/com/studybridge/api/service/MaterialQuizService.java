package com.studybridge.api.service;

import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.MaterialGroupShare;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.QuizAccessException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.MaterialGroupShareRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.MaterialQuizScoreService.RankedUser;
import com.studybridge.api.service.MaterialQuizScoreService.RankingSnapshot;
import com.studybridge.api.service.MaterialQuizScoreService.RecordOutcome;
import com.studybridge.api.service.MaterialQuizScoreService.StoredScore;
import com.studybridge.api.util.MaterialQuizContent;
import com.studybridge.api.util.MaterialQuizContent.InternalQuestion;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
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
    private final MaterialGroupShareRepository shareRepository;
    private final GroupStudyMemberRepository memberRepository;
    private final UserRepository userRepository;

    public static final String RANKING_POLICY = "BEST_SCORE";
    static final int DEFAULT_RANKING_LIMIT = 50;
    static final int MAX_RANKING_LIMIT = 100;
    static final String WITHDRAWN_NICKNAME = "탈퇴한 사용자";

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
     * 서버 채점. 흐름: 사용자(JWT) → 퀴즈 조회 → materialId 소속 검증 → 참여 권한(소유자 또는 공유 그룹 멤버) → 정답 키 조회 → 문항별 채점
     * → score → Redis 원자 기록(응시 횟수·최고점·랭킹) → 결과 반환. 알 수 없는 questionId(다른 퀴즈 접두어 포함)/optionId 는 400.
     */
    @Transactional
    public QuizDTO.ResultResponse submit(Long userId, Long materialId, Long quizId, QuizDTO.SubmitRequest request) {
        MaterialQuiz quiz = loadAccessibleQuiz(userId, materialId, quizId);
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

        Instant now = Instant.now();
        QuizDTO.ResultResponse result = grade(quiz, userId, questions, selected, 1, LocalDateTime.now());

        StoredScore stored = StoredScore.builder()
                .quizId(quiz.getQuizId())
                .userId(userId)
                .score(result.getScore())
                .correctCount(result.getCorrectCount())
                .totalQuestions(result.getTotalQuestions())
                .answeredCount(result.getAnsweredCount())
                .submittedAt(result.getSubmittedAt())
                .selected(selected)
                .build();
        RecordOutcome outcome = scoreService.record(stored, now);
        result.setAttempt(outcome.attempt());
        result.setPersisted(outcome.persisted());
        result.setBestScore(outcome.persisted() ? outcome.bestScore() : null);
        result.setDuplicate(outcome.duplicate());
        log.info("[QUIZ_SCORE] quizId={} userId={} score={} correct={}/{} attempt={} best={} improved={} duplicate={} persisted={}",
                quiz.getQuizId(), userId, result.getScore(), result.getCorrectCount(), result.getTotalQuestions(),
                outcome.attempt(), outcome.bestScore(), outcome.improved(), outcome.duplicate(), outcome.persisted());
        return result;
    }

    /** 최근 채점 결과(Redis 의 선택 답안을 DB 정답 키로 재채점해 결과 생성). 없으면 404. */
    public QuizDTO.ResultResponse latestResult(Long userId, Long materialId, Long quizId) {
        MaterialQuiz quiz = loadAccessibleQuiz(userId, materialId, quizId);
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
        r.setBestScore(s.getBestScore() != null ? s.getBestScore() : s.getScore());
        return r;
    }

    // ── 랭킹 ────────────────────────────────────────────────────────────────

    /**
     * 퀴즈별 랭킹(최고점, 경쟁 순위 1·1·3, 동점은 먼저 달성한 사람 우선). 권한 = 응시 권한과 같다(소유자 또는 공유 그룹 멤버).
     * 닉네임은 User.displayName 일괄 조회(N+1 없음). 응답에 userId·email 을 싣지 않는다. Redis 장애 → RankingUnavailableException(503).
     */
    public QuizDTO.RankingResponse ranking(Long userId, Long materialId, Long quizId, Integer limit) {
        int lim = limit == null ? DEFAULT_RANKING_LIMIT : limit;
        if (lim < 1 || lim > MAX_RANKING_LIMIT) {
            throw QuizAccessException.of(HttpStatus.BAD_REQUEST, "INVALID_LIMIT", "limit 은 1~" + MAX_RANKING_LIMIT + " 사이여야 합니다.");
        }
        MaterialQuiz quiz = loadAccessibleQuiz(userId, materialId, quizId);
        int totalQuestions = (int) MaterialQuizContent.parse(quiz.getQuizId(), quiz.getQuizData()).stream()
                .filter(InternalQuestion::isGradable).count();
        RankingSnapshot snap = scoreService.ranking(quiz.getQuizId(), userId, lim);

        Set<Long> ids = new HashSet<>();
        snap.top().forEach(r -> ids.add(r.userId()));
        if (snap.me() != null) ids.add(snap.me().userId());
        Map<Long, User> users = new LinkedHashMap<>();
        if (!ids.isEmpty()) userRepository.findAllById(ids).forEach(u -> users.put(u.getId(), u));

        List<QuizDTO.RankingEntry> entries = new ArrayList<>();
        for (RankedUser r : snap.top()) entries.add(toEntry(r, users, userId, totalQuestions));
        return QuizDTO.RankingResponse.builder()
                .materialId(materialId)
                .quizId(quiz.getQuizId())
                .rankingPolicy(RANKING_POLICY)
                .totalQuestions(totalQuestions)
                .totalParticipants(snap.totalParticipants())
                .generatedAt(LocalDateTime.now())
                .entries(entries)
                .me(snap.me() == null ? null : toEntry(snap.me(), users, userId, totalQuestions))
                .build();
    }

    private static QuizDTO.RankingEntry toEntry(RankedUser r, Map<Long, User> users, Long me, int totalQuestions) {
        StoredScore s = r.score();
        User u = users.get(r.userId());
        String nick = u == null ? WITHDRAWN_NICKNAME
                : u.getDisplayName() == null || u.getDisplayName().isBlank() ? "익명" : u.getDisplayName().trim();
        return QuizDTO.RankingEntry.builder()
                .rank(r.rank())
                .nickname(nick)
                .score(s.getBestScore())
                .correctCount(s.getBestCorrectCount())
                .totalQuestions(s.getTotalQuestions() != null ? s.getTotalQuestions() : totalQuestions)
                .attemptCount(s.getAttempt() == null ? 1 : s.getAttempt())
                .achievedAt(s.getBestAt())
                .isMe(me != null && me.equals(r.userId()))
                .build();
    }

    /** 그룹에 공유된 자료의 퀴즈 목록(소유자도 사용 가능). 정답 키 없이 공개 문항 + 요청자의 최근 결과. */
    public List<QuizDTO.SharedQuiz> sharedQuizzes(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> QuizAccessException.of(HttpStatus.NOT_FOUND, "MATERIAL_NOT_FOUND", "자료를 찾을 수 없습니다."));
        if (!canParticipate(userId, material)) {
            throw QuizAccessException.of(HttpStatus.FORBIDDEN, "FORBIDDEN", "이 자료의 퀴즈에 참여할 권한이 없습니다.");
        }
        List<QuizDTO.SharedQuiz> out = new ArrayList<>();
        for (MaterialQuiz q : quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(materialId)) {
            out.add(QuizDTO.SharedQuiz.builder()
                    .quizId(q.getQuizId()).materialId(materialId).difficulty(q.getDifficulty())
                    .questionCount(q.getQuestionCount()).createdAt(q.getCreatedAt())
                    .questions(toPublicQuestions(q.getQuizId(), q.getQuizData()))
                    .lastResult(latestResultOrNull(q, userId))
                    .build());
        }
        return out;
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

    /**
     * 참여 권한: 자료 소유자, 또는 자료가 공유된 그룹의 JOINED 멤버(공유한 소유자도 그 그룹에 JOINED 여야 공유가 유효).
     * 공유 관계가 없으면 기존처럼 소유자 전용이다.
     */
    public boolean canParticipate(Long userId, Material material) {
        if (userId == null || material == null) return false;
        if (userId.equals(material.getUserId())) return true;
        for (MaterialGroupShare share : shareRepository.findByMaterialId(material.getMaterialId())) {
            Long g = share.getGroupStudyId();
            if (memberRepository.existsByGroupStudyIdAndUserIdAndStatus(g, userId, GroupStudyMemberStatus.JOINED)
                    && memberRepository.existsByGroupStudyIdAndUserIdAndStatus(g, material.getUserId(), GroupStudyMemberStatus.JOINED)) {
                return true;
            }
        }
        return false;
    }

    /** 404 QUIZ_NOT_FOUND(없음·다른 자료 소속) → 404 MATERIAL_NOT_FOUND → 403 FORBIDDEN(참여 권한 없음) 순서. */
    private MaterialQuiz loadAccessibleQuiz(Long userId, Long materialId, Long quizId) {
        MaterialQuiz quiz = quizId == null ? null : quizRepository.findById(quizId).orElse(null);
        if (quiz == null) throw QuizAccessException.of(HttpStatus.NOT_FOUND, "QUIZ_NOT_FOUND", "퀴즈를 찾을 수 없습니다.");
        Material material = quiz.getMaterial();
        if (material == null || materialId == null || !materialId.equals(material.getMaterialId())) {
            throw QuizAccessException.of(HttpStatus.NOT_FOUND, "QUIZ_NOT_FOUND", "이 자료에 속한 퀴즈가 아닙니다.");
        }
        Material current = materialRepository.findById(materialId).orElse(null);
        if (current == null) throw QuizAccessException.of(HttpStatus.NOT_FOUND, "MATERIAL_NOT_FOUND", "자료를 찾을 수 없습니다.");
        if (!canParticipate(userId, current)) {
            throw QuizAccessException.of(HttpStatus.FORBIDDEN, "FORBIDDEN", "해당 퀴즈에 대한 권한이 없습니다.");
        }
        return quiz;
    }

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
