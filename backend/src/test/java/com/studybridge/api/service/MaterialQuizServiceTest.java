package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.RedisTemplate;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

/**
 * 자료 퀴즈 서버 채점(Q1~Q8) + 초기 payload 정답 미노출(Q3) + Redis 저장/정리(G8/G14).
 *  · Redis HASH 는 인메모리 Map fake. 정답 키는 quiz_data(DB) 에서만 읽는다.
 */
class MaterialQuizServiceTest {

    private static final long OWNER = 55L;
    private static final long OTHER = 56L;
    private static final long MATERIAL = 900L;
    private static final long QUIZ = 72L;
    private static final long OTHER_QUIZ = 73L;

    // AI07 /api/ai/quiz 원문 형태(정답 키 혼재: answerIndex / answer(int) / answer(text) / correctAnswer / correct_answer)
    private static final String QUIZ_DATA = "["
            + "{\"question\":\"Q1\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"answerIndex\":1,\"explanation\":\"e1\"},"
            + "{\"question\":\"Q2\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":2},"
            + "{\"question\":\"Q3\",\"choices\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":\"D\"},"
            + "{\"question\":\"Q4\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":0},"
            + "{\"question\":\"Q5\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"correct_answer\":\"C\"}"
            + "]";

    /** key -> (field -> value) — Redis HASH fake */
    private final Map<String, Map<Object, Object>> hashStore = new LinkedHashMap<>();
    private MaterialQuizService service;
    private MaterialQuizScoreService scoreService;
    private MaterialQuiz quiz;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        hashStore.clear();
        HashOperations<String, Object, Object> hash = mock(HashOperations.class, inv -> {
            String m = inv.getMethod().getName();
            Object[] a = inv.getArguments();
            switch (m) {
                case "put": hashStore.computeIfAbsent((String) a[0], k -> new LinkedHashMap<>()).put(a[1], a[2]); return null;
                case "get": { Map<Object, Object> h = hashStore.get((String) a[0]); return h == null ? null : h.get(a[1]); }
                default: return null;
            }
        });
        RedisTemplate<String, Object> redis = mock(RedisTemplate.class, inv -> {
            switch (inv.getMethod().getName()) {
                case "opsForHash": return hash;
                case "delete": return hashStore.remove(inv.getArguments()[0]) != null;
                case "expire": return Boolean.TRUE;
                default: return null;
            }
        });
        scoreService = new MaterialQuizScoreService(redis, new ObjectMapper().findAndRegisterModules(), 180);

        Material material = new Material();
        material.setMaterialId(MATERIAL);
        material.setUserId(OWNER);
        quiz = MaterialQuiz.builder().quizId(QUIZ).material(material).difficulty("보통").questionCount(5).quizData(QUIZ_DATA).build();

        Material otherMaterial = new Material();
        otherMaterial.setMaterialId(901L);
        otherMaterial.setUserId(OWNER);
        MaterialQuiz otherQuiz = MaterialQuiz.builder().quizId(OTHER_QUIZ).material(otherMaterial).quizData(QUIZ_DATA).build();

        MaterialRepository materials = mock(MaterialRepository.class);
        Mockito.when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
        Mockito.when(materials.findById(901L)).thenReturn(Optional.of(otherMaterial));
        MaterialQuizRepository quizzes = mock(MaterialQuizRepository.class);
        Mockito.when(quizzes.findById(QUIZ)).thenReturn(Optional.of(quiz));
        Mockito.when(quizzes.findById(OTHER_QUIZ)).thenReturn(Optional.of(otherQuiz));
        Mockito.when(quizzes.findById(404L)).thenReturn(Optional.empty());

        service = new MaterialQuizService(materials, quizzes, scoreService);
    }

    private static QuizDTO.SubmitRequest submit(String... pairs) {
        QuizDTO.SubmitRequest r = new QuizDTO.SubmitRequest();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            r.getAnswers().add(QuizDTO.SubmittedAnswer.builder().questionId(pairs[i]).selectedOptionId(pairs[i + 1]).build());
        }
        return r;
    }

    @Test
    void q3_public_dto_contains_no_answer_key_and_stable_ids() throws Exception {
        List<QuizDTO.PublicQuestion> pub = MaterialQuizService.toPublicQuestions(QUIZ, QUIZ_DATA);
        assertEquals(5, pub.size());
        assertEquals("q72-1", pub.get(0).getQuestionId());
        assertEquals(List.of("o1", "o2", "o3", "o4"), pub.get(2).getOptions().stream().map(QuizDTO.PublicOption::getOptionId).toList());
        assertTrue(pub.stream().allMatch(q -> Boolean.TRUE.equals(q.getGradable())));

        QuizDTO.Response resp = QuizDTO.Response.builder().quizId(QUIZ).materialId(MATERIAL).questions(pub).success(true).build();
        String json = new ObjectMapper().findAndRegisterModules().writeValueAsString(resp);
        for (String leak : List.of("answerIndex", "\"answer\"", "correctAnswer", "correct_answer", "correctOptionId", "quizData", "\"quizzes\"")) {
            assertFalse(json.contains(leak), "initial payload leaks answer key: " + leak + " in " + json);
        }
    }

    @Test
    void q1_four_of_five_correct_scores_80_and_q6_persists_to_redis() {
        // 정답: Q1=o2, Q2=o3, Q3=o4, Q4=o1, Q5=o3
        QuizDTO.ResultResponse r = service.submit(OWNER, MATERIAL, QUIZ,
                submit("q72-1", "o2", "q72-2", "o3", "q72-3", "o4", "q72-4", "o1", "q72-5", "o1"));
        assertEquals(80, r.getScore());
        assertEquals(4, r.getCorrectCount());
        assertEquals(5, r.getTotalQuestions());
        assertEquals(5, r.getAnsweredCount());
        assertEquals(1, r.getAttempt());
        assertTrue(r.getPersisted());
        // 문항별 결과: 제출 이후에만 정답 공개
        assertEquals(List.of("o3"), r.getResults().get(4).getCorrectOptionIds());
        assertEquals(List.of("o1"), r.getResults().get(4).getSelectedOptionIds());
        assertFalse(r.getResults().get(4).getCorrect());
        assertEquals("e1", r.getResults().get(0).getExplanation());

        // Q6: Redis 키/필드 존재, 정답 키 복제 없음
        Map<Object, Object> h = hashStore.get("studybridge:quiz:72:scores");
        assertNotNull(h);
        String stored = (String) h.get("55");
        assertTrue(stored.contains("\"score\":80"));
        assertFalse(stored.contains("correctOptionId"));
        assertFalse(stored.contains("explanation"));
        assertTrue(stored.contains("\"q72-5\":\"o1\""));
    }

    @Test
    void q2_client_supplied_score_cannot_influence_result() {
        // SubmitRequest 에는 score/isCorrect 필드가 없다(계약에서 받지 않음). 전부 오답 제출 → 0점.
        QuizDTO.ResultResponse r = service.submit(OWNER, MATERIAL, QUIZ,
                submit("q72-1", "o1", "q72-2", "o1", "q72-3", "o1", "q72-4", "o2", "q72-5", "o1"));
        assertEquals(0, r.getScore());
        assertEquals(0, r.getCorrectCount());
        // DTO 에 score 계열 setter 가 있어도 서버는 요청에서 읽지 않는다(필드 자체가 없음을 리플렉션으로 확인)
        assertTrue(java.util.Arrays.stream(QuizDTO.SubmitRequest.class.getDeclaredFields()).noneMatch(f -> f.getName().toLowerCase().contains("score")));
        assertTrue(java.util.Arrays.stream(QuizDTO.SubmittedAnswer.class.getDeclaredFields()).noneMatch(f -> f.getName().toLowerCase().contains("correct")));
    }

    @Test
    void q4_invalid_question_or_option_id_rejected() {
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q72-99", "o1")));
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o9")));
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o1", "q72-1", "o2")));
        assertTrue(hashStore.isEmpty(), "거절된 제출은 저장되지 않는다");
    }

    @Test
    void q5_question_id_from_another_quiz_rejected() {
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q73-1", "o2")));
        // quizId 가 materialId 에 속하지 않으면 404(존재 유추 방지)
        assertThrows(NoSuchElementException.class, () -> service.submit(OWNER, MATERIAL, OTHER_QUIZ, submit("q73-1", "o2")));
        assertThrows(NoSuchElementException.class, () -> service.submit(OWNER, MATERIAL, 404L, submit("q404-1", "o2")));
    }

    @Test
    void q7_two_users_do_not_collide_in_redis() {
        service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o2", "q72-2", "o3", "q72-3", "o4", "q72-4", "o1", "q72-5", "o3"));
        Map<Object, Object> h = hashStore.get("studybridge:quiz:72:scores");
        assertEquals(1, h.size());
        // 다른 사용자는 소유자가 아니므로 403 — 같은 키에 필드가 추가되지 않는다.
        assertThrows(SecurityException.class, () -> service.submit(OTHER, MATERIAL, QUIZ, submit("q72-1", "o1")));
        assertEquals(1, h.size());
        assertEquals(100, service.latestResult(OWNER, MATERIAL, QUIZ).getScore());
        // 저장소 단위: 사용자별 필드 분리
        MaterialQuizScoreService.StoredScore other = MaterialQuizScoreService.StoredScore.builder()
                .quizId(QUIZ).userId(OTHER).score(20).correctCount(1).totalQuestions(5).answeredCount(5).attempt(1).build();
        scoreService.save(other);
        assertEquals(2, h.size());
        assertEquals(100, scoreService.find(QUIZ, OWNER).getScore());
        assertEquals(20, scoreService.find(QUIZ, OTHER).getScore());
    }

    @Test
    void q8_duplicate_submit_is_idempotent_overwrite_with_attempt_counter() {
        QuizDTO.ResultResponse a = service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o2"));
        QuizDTO.ResultResponse b = service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o2"));
        assertEquals(a.getScore(), b.getScore());
        assertEquals(1, a.getAttempt());
        assertEquals(2, b.getAttempt());
        assertEquals(1, hashStore.get("studybridge:quiz:72:scores").size(), "덮어쓰기 — 이력 행이 늘지 않는다");
        // 재응시(다른 답) 는 최신이 반영된다
        QuizDTO.ResultResponse c = service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o1"));
        assertEquals(0, c.getScore());
        assertEquals(0, service.latestResult(OWNER, MATERIAL, QUIZ).getScore());
    }

    @Test
    void unanswered_questions_count_as_wrong_and_partial_submit_allowed() {
        QuizDTO.ResultResponse r = service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o2", "q72-2", ""));
        assertEquals(20, r.getScore());
        assertEquals(1, r.getAnsweredCount());
        assertFalse(r.getResults().get(1).getAnswered());
        assertFalse(r.getResults().get(1).getCorrect());
    }

    @Test
    void zero_gradable_questions_yields_zero_not_division_error() {
        assertEquals(0, MaterialQuizService.computeScore(0, 0));
        assertEquals(67, MaterialQuizService.computeScore(2, 3));
        assertEquals(100, MaterialQuizService.computeScore(3, 3));
    }

    @Test
    void ungradable_question_without_answer_key_is_excluded_from_total() {
        String data = "[{\"question\":\"Q1\",\"options\":[\"A\",\"B\"],\"answerIndex\":0},{\"question\":\"Q2\",\"options\":[\"A\",\"B\"]}]";
        List<QuizDTO.PublicQuestion> pub = MaterialQuizService.toPublicQuestions(5L, data);
        assertTrue(pub.get(0).getGradable());
        assertFalse(pub.get(1).getGradable());
        quiz.setQuizData(data);
        QuizDTO.ResultResponse r = service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o1", "q72-2", "o1"));
        assertEquals(1, r.getTotalQuestions());
        assertEquals(100, r.getScore());
        assertTrue(r.getResults().get(1).getCorrectOptionIds().isEmpty());
    }

    @Test
    void s3_s4_v2_ids_question_and_option_ids_from_ai07_are_honored_and_foreign_ids_rejected() {
        String v2 = "[{\"questionId\":\"q_a1\",\"question\":\"Q1\",\"options\":[\"a\",\"b\",\"c\",\"d\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":1,\"answer\":1,\"answerIndex\":1,\"correctOptionIds\":[\"B\"],\"explanation\":\"e\"},"
                + "{\"questionId\":\"q_a2\",\"question\":\"Q2\",\"options\":[\"a\",\"b\",\"c\",\"d\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctOptionIds\":[\"D\"]}]";
        quiz.setQuizData(v2);
        List<QuizDTO.PublicQuestion> pub = MaterialQuizService.toPublicQuestions(QUIZ, v2);
        assertEquals("q_a1", pub.get(0).getQuestionId());
        assertEquals(List.of("A", "B", "C", "D"), pub.get(1).getOptions().stream().map(QuizDTO.PublicOption::getOptionId).toList());
        assertTrue(pub.get(1).getGradable(), "correctOptionIds 만 있어도 채점 가능");

        QuizDTO.SubmitRequest req = new QuizDTO.SubmitRequest();
        req.getAnswers().add(QuizDTO.SubmittedAnswer.builder().questionId("q_a1").selectedOptionIds(List.of("B")).build());
        req.getAnswers().add(QuizDTO.SubmittedAnswer.builder().questionId("q_a2").selectedOptionIds(List.of("A")).build());
        QuizDTO.ResultResponse r = service.submit(OWNER, MATERIAL, QUIZ, req);
        assertEquals(50, r.getScore());
        assertEquals(List.of("D"), r.getResults().get(1).getCorrectOptionIds());

        // S3 foreign questionId / S4 foreign optionId / 다중 선택
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q_zzz", "A")));
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q_a1", "E")));
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, submit("q_a1", "o2")));
        QuizDTO.SubmitRequest multi = new QuizDTO.SubmitRequest();
        multi.getAnswers().add(QuizDTO.SubmittedAnswer.builder().questionId("q_a1").selectedOptionIds(List.of("A", "B")).build());
        assertThrows(IllegalArgumentException.class, () -> service.submit(OWNER, MATERIAL, QUIZ, multi));
    }

    @Test
    void latest_result_404_when_never_submitted_and_delete_clears_redis() {
        assertThrows(NoSuchElementException.class, () -> service.latestResult(OWNER, MATERIAL, QUIZ));
        service.submit(OWNER, MATERIAL, QUIZ, submit("q72-1", "o2"));
        assertTrue(hashStore.containsKey("studybridge:quiz:72:scores"));
        assertThrows(SecurityException.class, () -> service.delete(OTHER, MATERIAL, QUIZ));
        assertTrue(hashStore.containsKey("studybridge:quiz:72:scores"));
        service.delete(OWNER, MATERIAL, QUIZ);
        assertFalse(hashStore.containsKey("studybridge:quiz:72:scores"), "D6/G14: 퀴즈 삭제 후 stale score 없음");
    }
}
