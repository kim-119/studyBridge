package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.config.RedisConfig;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialGroupShare;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.QuizAccessException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.MaterialGroupShareRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.MaterialQuizScoreService.RankingUnavailableException;
import com.studybridge.api.service.MaterialQuizScoreService.StoredScore;
import com.studybridge.api.util.MaterialQuizContent;
import com.studybridge.api.util.MaterialQuizContent.InternalQuestion;
import java.io.File;
import java.net.Socket;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;

/**
 * 실제 Redis + 실제 Spring 컨테이너(RedisConfig 와 같은 직렬화) 로 퀴즈별 랭킹을 검증한다.
 * 운영 Redis 를 건드리지 않도록 QUIZ_RANKING_IT_REDIS_PORT 를 지정했을 때만 실행된다(지정 안 하면 skip).
 *   docker run --rm -d --name sb-ranking-it -p 127.0.0.1:6391:6379 redis:7-alpine
 *   QUIZ_RANKING_IT_REDIS_PORT=6391 ./gradlew test --tests '*MaterialQuizRankingRedisIT'
 */
class MaterialQuizRankingRedisIT {

    static final String PORT = System.getenv("QUIZ_RANKING_IT_REDIS_PORT");
    static final long OWNER = 55L, A = 61L, B = 62L, C = 63L, D = 64L, STRANGER = 70L;
    static final long MATERIAL = 900L, MATERIAL2 = 901L, QUIZ = 9001L, QUIZ2 = 9002L, GROUP = 33L;
    static final String QUIZ_DATA = "["
            + "{\"question\":\"Q1\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"answerIndex\":1},"
            + "{\"question\":\"Q2\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":2},"
            + "{\"question\":\"Q3\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":\"D\"},"
            + "{\"question\":\"Q4\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":0},"
            + "{\"question\":\"Q5\",\"options\":[\"A\",\"B\",\"C\",\"D\"],\"correct_answer\":\"C\"}"
            + "]";

    AnnotationConfigApplicationContext ctx;
    MaterialQuizService service;
    MaterialQuizScoreService scores;
    StringRedisTemplate redis;
    final Map<Long, Material> materials = new LinkedHashMap<>();
    final Map<Long, MaterialQuiz> quizzes = new LinkedHashMap<>();
    final List<MaterialGroupShare> shares = new ArrayList<>();
    final Set<String> joined = new HashSet<>();   // "group:user"

    @BeforeEach
    void setUp() {
        Assumptions.assumeTrue(PORT != null && !PORT.isBlank(), "QUIZ_RANKING_IT_REDIS_PORT 미지정 — 실제 Redis 통합 테스트 생략");
        Assumptions.assumeTrue(reachable(Integer.parseInt(PORT)), "Redis 127.0.0.1:" + PORT + " 연결 불가");
        assertFalse("6379".equals(PORT), "운영 Redis 포트(6379)로 통합 테스트를 실행하지 않는다");

        Material m1 = material(MATERIAL, OWNER), m2 = material(MATERIAL2, OWNER);
        quizzes.put(QUIZ, MaterialQuiz.builder().quizId(QUIZ).material(m1).difficulty("보통").questionCount(5).quizData(QUIZ_DATA).build());
        quizzes.put(QUIZ2, MaterialQuiz.builder().quizId(QUIZ2).material(m2).difficulty("보통").questionCount(5).quizData(QUIZ_DATA).build());

        MaterialRepository mr = mock(MaterialRepository.class);
        when(mr.findById(anyLong())).thenAnswer(i -> Optional.ofNullable(materials.get((Long) i.getArgument(0))));
        MaterialQuizRepository qr = mock(MaterialQuizRepository.class);
        when(qr.findById(anyLong())).thenAnswer(i -> Optional.ofNullable(quizzes.get((Long) i.getArgument(0))));
        MaterialGroupShareRepository sr = mock(MaterialGroupShareRepository.class);
        when(sr.findByMaterialId(anyLong())).thenAnswer(i -> shares.stream().filter(s -> s.getMaterialId().equals(i.getArgument(0))).toList());
        GroupStudyMemberRepository gm = mock(GroupStudyMemberRepository.class);
        when(gm.existsByGroupStudyIdAndUserIdAndStatus(anyLong(), anyLong(), any())).thenAnswer(i ->
                i.getArgument(2) == GroupStudyMemberStatus.JOINED && joined.contains(i.getArgument(0) + ":" + i.getArgument(1)));
        UserRepository ur = mock(UserRepository.class);
        when(ur.findAllById(any())).thenAnswer(i -> {
            List<User> out = new ArrayList<>();
            for (Object id : (Collection<?>) i.getArgument(0)) {
                long uid = (Long) id;
                if (uid != D) out.add(User.builder().id(uid).email("u" + uid + "@x").displayName("닉" + uid).password("p").build());
            }
            return out;
        });

        ctx = new AnnotationConfigApplicationContext();
        ctx.getEnvironment().getPropertySources().addFirst(new MapPropertySource("it", Map.of(
                "spring.data.redis.host", "127.0.0.1", "spring.data.redis.port", PORT, "ai.quiz.duplicate-submit-window-ms", "3000")));
        ctx.register(RedisConfig.class, MaterialQuizScoreService.class, MaterialQuizService.class);
        ctx.registerBean(ObjectMapper.class, () -> bootMapper());
        ctx.registerBean(StringRedisTemplate.class, () -> new StringRedisTemplate(ctx.getBean(RedisConnectionFactory.class)));
        ctx.registerBean(MaterialRepository.class, () -> mr);
        ctx.registerBean(MaterialQuizRepository.class, () -> qr);
        ctx.registerBean(MaterialGroupShareRepository.class, () -> sr);
        ctx.registerBean(GroupStudyMemberRepository.class, () -> gm);
        ctx.registerBean(UserRepository.class, () -> ur);
        ctx.refresh();
        service = ctx.getBean(MaterialQuizService.class);
        scores = ctx.getBean(MaterialQuizScoreService.class);
        redis = ctx.getBean(StringRedisTemplate.class);
        redis.delete(List.of(MaterialQuizScoreService.scoreKey(QUIZ), MaterialQuizScoreService.rankingKey(QUIZ),
                MaterialQuizScoreService.scoreKey(QUIZ2), MaterialQuizScoreService.rankingKey(QUIZ2)));
        // 소유자 OWNER 가 그룹 GROUP 에 자료 MATERIAL 공유, A·B·C·D 는 그 그룹 JOINED 멤버
        shares.add(MaterialGroupShare.builder().materialId(MATERIAL).groupStudyId(GROUP).sharedByUserId(OWNER).build());
        for (long u : new long[]{OWNER, A, B, C, D}) joined.add(GROUP + ":" + u);
    }

    @AfterEach
    void tearDown() {
        if (redis != null) {
            redis.delete(List.of(MaterialQuizScoreService.scoreKey(QUIZ), MaterialQuizScoreService.rankingKey(QUIZ),
                    MaterialQuizScoreService.scoreKey(QUIZ2), MaterialQuizScoreService.rankingKey(QUIZ2)));
        }
        if (ctx != null) ctx.close();
    }

    private Material material(long id, long owner) {
        Material m = new Material();
        m.setMaterialId(id);
        m.setUserId(owner);
        materials.put(id, m);
        return m;
    }

    /** Spring Boot JacksonAutoConfiguration 기본값과 같은 ObjectMapper(날짜 = ISO 문자열). 운영 Redis 의 기존 기록 형식과 같다. */
    static ObjectMapper bootMapper() {
        return Jackson2ObjectMapperBuilder.json()
                .featuresToDisable(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS).build();
    }

    private static boolean reachable(int port) {
        try (Socket s = new Socket("127.0.0.1", port)) {
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** correct 개 맞히는 답안(앞에서부터 정답, 나머지 오답). variant 로 오답 보기를 바꿔 지문을 다르게 만든다. */
    private QuizDTO.SubmitRequest answers(long quizId, int correct, int variant) {
        QuizDTO.SubmitRequest r = new QuizDTO.SubmitRequest();
        List<InternalQuestion> qs = MaterialQuizContent.parse(quizId, QUIZ_DATA);
        for (int i = 0; i < qs.size(); i++) {
            InternalQuestion q = qs.get(i);
            String opt = q.getCorrectOptionId();
            if (i >= correct) {
                List<String> wrong = new ArrayList<>(q.getOptionIds());
                wrong.remove(q.getCorrectOptionId());
                opt = wrong.get(Math.floorMod(variant + i, wrong.size()));
            }
            r.getAnswers().add(QuizDTO.SubmittedAnswer.builder().questionId(q.getQuestionId()).selectedOptionId(opt).build());
        }
        return r;
    }

    /** 코드 예외를 기대: 기존 예외 계층(NoSuchElement/Security/IllegalArgument)을 상속하고 code 를 가진다. */
    private static QuizAccessException.Coded coded(org.junit.jupiter.api.function.Executable ex) {
        RuntimeException e = assertThrows(RuntimeException.class, ex);
        assertTrue(e instanceof QuizAccessException.Coded, "코드 예외여야 함: " + e);
        return (QuizAccessException.Coded) e;
    }

    private QuizDTO.ResultResponse submit(long user, int correct, int variant) {
        return service.submit(user, MATERIAL, QUIZ, answers(QUIZ, correct, variant));
    }

    @Test
    void threeUsers_bestScoreRanking_competitionRanks_tieOrderedByEarlierAchievement() throws Exception {
        submit(A, 5, 0);                    // 100
        Thread.sleep(5);
        submit(B, 5, 0);                    // 100, 더 늦게
        submit(C, 4, 0);                    // 80
        submit(OWNER, 2, 0);                // 40
        QuizDTO.RankingResponse r = service.ranking(C, MATERIAL, QUIZ, 50);
        assertEquals(4L, r.getTotalParticipants());
        assertEquals(5, r.getTotalQuestions());
        assertEquals("BEST_SCORE", r.getRankingPolicy());
        assertEquals(List.of(1, 1, 3, 4), r.getEntries().stream().map(QuizDTO.RankingEntry::getRank).toList());
        assertEquals(List.of("닉61", "닉62", "닉63", "닉55"), r.getEntries().stream().map(QuizDTO.RankingEntry::getNickname).toList());
        assertEquals(List.of(100, 100, 80, 40), r.getEntries().stream().map(QuizDTO.RankingEntry::getScore).toList());
        assertTrue(r.getEntries().get(2).getIsMe());
        assertEquals(3, r.getMe().getRank());
        assertEquals(4, r.getMe().getCorrectCount());
        assertFalse(r.getEntries().get(0).getIsMe());
    }

    @Test
    void retake_higherScoreUpdatesBest_lowerScoreKeepsBest_attemptsCount() {
        assertEquals(60, submit(A, 3, 0).getScore());
        QuizDTO.ResultResponse up = submit(A, 4, 1);
        assertEquals(80, up.getBestScore());
        assertEquals(2, up.getAttempt());
        QuizDTO.ResultResponse down = submit(A, 1, 2);
        assertEquals(20, down.getScore());
        assertEquals(80, down.getBestScore(), "낮은 점수로 최고점을 덮어쓰지 않는다");
        assertEquals(3, down.getAttempt());
        QuizDTO.RankingEntry me = service.ranking(A, MATERIAL, QUIZ, 10).getMe();
        assertEquals(80, me.getScore());
        assertEquals(4, me.getCorrectCount());
        assertEquals(3, me.getAttemptCount());
        assertEquals(20, service.latestResult(A, MATERIAL, QUIZ).getScore(), "최근 결과 화면(/score)은 최신 제출 그대로");
    }

    @Test
    void duplicateResubmitWithinWindow_isNotCountedTwice() {
        QuizDTO.ResultResponse first = submit(A, 3, 0);
        QuizDTO.ResultResponse again = submit(A, 3, 0);
        assertEquals(1, first.getAttempt());
        assertTrue(again.getDuplicate());
        assertEquals(1, again.getAttempt());
        assertEquals(1, service.ranking(A, MATERIAL, QUIZ, 10).getMe().getAttemptCount());
        assertFalse(submit(A, 3, 1).getDuplicate(), "답안이 다르면 새 응시");
    }

    @Test
    void concurrentSubmissions_attemptsAtomic_hashAndZsetConsistent() throws Exception {
        int users = 12, perUser = 5;
        ExecutorService pool = Executors.newFixedThreadPool(16);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<?>> fs = new ArrayList<>();
        for (int u = 0; u < users; u++) {
            long uid = 1000 + u;
            joined.add(GROUP + ":" + uid);
            for (int k = 0; k < perUser; k++) {
                int correct = (u + k) % 6, variant = k;
                fs.add(pool.submit(() -> { start.await(); return submit(uid, correct, variant); }));
            }
        }
        start.countDown();
        for (Future<?> f : fs) f.get(30, TimeUnit.SECONDS);
        pool.shutdown();
        assertEquals((long) users, redis.opsForZSet().zCard(MaterialQuizScoreService.rankingKey(QUIZ)));
        assertEquals((long) users, redis.opsForHash().size(MaterialQuizScoreService.scoreKey(QUIZ)));
        for (int u = 0; u < users; u++) {
            StoredScore s = scores.find(QUIZ, 1000L + u);
            assertEquals(perUser, s.getAttempt(), "응시 횟수가 유실·중복 없이 정확");
            int expectedBest = 0;
            for (int k = 0; k < perUser; k++) expectedBest = Math.max(expectedBest, ((u + k) % 6) * 20);
            assertEquals(expectedBest, s.getBestScore());
            Double z = redis.opsForZSet().score(MaterialQuizScoreService.rankingKey(QUIZ), String.valueOf(1000 + u));
            assertEquals(expectedBest, MaterialQuizScoreService.scoreOf(z), "ZSET 최고점 = HASH 최고점");
        }
    }

    @Test
    void quizzesAndMaterialsAreIsolated_andWrongMaterialPathIs404() {
        submit(A, 5, 0);
        service.submit(OWNER, MATERIAL2, QUIZ2, answers(QUIZ2, 1, 0));
        assertEquals(1L, service.ranking(A, MATERIAL, QUIZ, 50).getTotalParticipants());
        QuizDTO.RankingResponse other = service.ranking(OWNER, MATERIAL2, QUIZ2, 50);
        assertEquals(1, other.getEntries().size());
        assertEquals("닉55", other.getEntries().get(0).getNickname());
        assertEquals("QUIZ_NOT_FOUND", coded(() -> service.ranking(OWNER, MATERIAL2, QUIZ, 50)).getCode());
        assertEquals("QUIZ_NOT_FOUND", coded(() -> service.ranking(OWNER, MATERIAL, 424242L, 50)).getCode());
        assertTrue(assertThrows(RuntimeException.class, () -> service.ranking(OWNER, MATERIAL, 424242L, 50)) instanceof java.util.NoSuchElementException);
    }

    @Test
    void accessControl_strangerKickedAndUnsharedAreForbidden_ownerLeavingDisablesShare() {
        QuizAccessException.Coded e = coded(() -> service.ranking(STRANGER, MATERIAL, QUIZ, 50));
        assertEquals(HttpStatus.FORBIDDEN, e.getStatus());
        assertEquals("FORBIDDEN", e.getCode());
        assertThrows(SecurityException.class, () -> service.submit(STRANGER, MATERIAL, QUIZ, answers(QUIZ, 5, 0)));
        assertThrows(SecurityException.class, () -> service.ranking(A, MATERIAL2, QUIZ2, 50), "공유하지 않은 자료는 그룹 멤버도 불가");
        submit(A, 5, 0);
        joined.remove(GROUP + ":" + A);          // 강퇴/탈퇴
        assertThrows(SecurityException.class, () -> service.ranking(A, MATERIAL, QUIZ, 50));
        joined.add(GROUP + ":" + A);
        joined.remove(GROUP + ":" + OWNER);      // 공유한 소유자가 그룹을 떠나면 공유 무효
        assertThrows(SecurityException.class, () -> service.ranking(B, MATERIAL, QUIZ, 50));
        assertNotNull(service.ranking(OWNER, MATERIAL, QUIZ, 50), "소유자는 항상 가능");
        assertEquals("INVALID_LIMIT", coded(() -> service.ranking(OWNER, MATERIAL, QUIZ, 0)).getCode());
        assertEquals("INVALID_LIMIT", coded(() -> service.ranking(OWNER, MATERIAL, QUIZ, 101)).getCode());
    }

    @Test
    void limit_meOutsideTop_rankByZcount_withdrawnUserShownAsWithdrawn() {
        submit(A, 5, 0);
        submit(B, 4, 0);
        submit(D, 4, 1);    // D 는 사용자 테이블에 없음(탈퇴)
        submit(C, 1, 0);
        QuizDTO.RankingResponse r = service.ranking(C, MATERIAL, QUIZ, 2);
        assertEquals(2, r.getEntries().size());
        assertEquals(4L, r.getTotalParticipants());
        assertEquals(4, r.getMe().getRank(), "상위 밖 요청자의 순위 = 더 높은 점수 수 + 1");
        assertEquals(20, r.getMe().getScore());
        QuizDTO.RankingResponse all = service.ranking(C, MATERIAL, QUIZ, 10);
        assertEquals(List.of(1, 2, 2, 4), all.getEntries().stream().map(QuizDTO.RankingEntry::getRank).toList());
        assertTrue(all.getEntries().stream().anyMatch(x -> "탈퇴한 사용자".equals(x.getNickname())));
        assertNull(service.ranking(OWNER, MATERIAL, QUIZ, 10).getMe(), "미응시면 me=null");
    }

    @Test
    void deleteQuiz_removesHashAndZset_andTtlAppliedToBoth() {
        submit(A, 5, 0);
        Long ht = redis.getExpire(MaterialQuizScoreService.scoreKey(QUIZ), TimeUnit.DAYS);
        Long zt = redis.getExpire(MaterialQuizScoreService.rankingKey(QUIZ), TimeUnit.DAYS);
        assertTrue(ht >= 179 && zt >= 179, "두 키 모두 180일 TTL: " + ht + "/" + zt);
        service.delete(OWNER, MATERIAL, QUIZ);
        quizzes.remove(QUIZ);
        assertFalse(redis.hasKey(MaterialQuizScoreService.scoreKey(QUIZ)));
        assertFalse(redis.hasKey(MaterialQuizScoreService.rankingKey(QUIZ)));
    }

    @Test
    void legacyRecordsWithoutZset_areReconciledOnRead_andLegacyScoreCountsAsBest() throws Exception {
        // 운영에 남아 있는 구 형식(bestScore 없음, ZSET 없음) — RedisTemplate 직렬화(JSON 문자열을 한 번 더 감쌈) 그대로 넣는다.
        @SuppressWarnings("unchecked")
        RedisTemplate<String, Object> tpl = (RedisTemplate<String, Object>) ctx.getBean("redisTemplate");
        String legacy = "{\"quizId\":" + QUIZ + ",\"userId\":" + B + ",\"score\":80,\"correctCount\":4,\"totalQuestions\":5,\"answeredCount\":5,"
                + "\"attempt\":2,\"submittedAt\":\"2026-10-07T19:33:20.699433318\",\"selected\":{}}";
        tpl.opsForHash().put(MaterialQuizScoreService.scoreKey(QUIZ), String.valueOf(B), legacy);
        QuizDTO.RankingResponse r = service.ranking(B, MATERIAL, QUIZ, 10);
        assertEquals(1L, r.getTotalParticipants());
        assertEquals(80, r.getMe().getScore());
        assertEquals(LocalDateTime.parse("2026-10-07T19:33:20.699"), r.getMe().getAchievedAt().withNano(699000000));
        QuizDTO.ResultResponse lower = submit(B, 1, 0);
        assertEquals(3, lower.getAttempt(), "구 기록의 응시 횟수에 이어서 센다");
        assertEquals(80, lower.getBestScore(), "구 기록 점수를 최고점으로 유지");
        assertEquals(80, service.ranking(B, MATERIAL, QUIZ, 10).getMe().getScore());
    }

    @Test
    void zsetCompositeIsExactInRealRedis_noPrecisionLoss() {
        String k = MaterialQuizScoreService.rankingKey(QUIZ);
        long[][] cases = {{100, 4102444800000L}, {100, 1577836800000L}, {0, 1577836800001L}, {99, 1793154226342L}, {1, 1793154226343L}};
        for (long[] c : cases) {
            long comp = MaterialQuizScoreService.composite((int) c[0], c[1]);
            redis.opsForZSet().add(k, "p" + c[0] + "-" + c[1], comp);
            Double back = redis.opsForZSet().score(k, "p" + c[0] + "-" + c[1]);
            assertEquals(comp, back.longValue(), "ZSET double 왕복 정확");
            assertEquals((int) c[0], MaterialQuizScoreService.scoreOf(back));
            assertEquals(c[1], MaterialQuizScoreService.achievedAtOf(back));
        }
        assertTrue(MaterialQuizScoreService.composite(100, 1793154226342L) < (1L << 53));
        assertTrue(MaterialQuizScoreService.composite(80, 1793154226342L) > MaterialQuizScoreService.composite(80, 1793154226343L),
                "동점이면 먼저 달성한 쪽이 큼");
        assertTrue(MaterialQuizScoreService.composite(81, 4102444800000L) > MaterialQuizScoreService.composite(80, 1577836800000L),
                "점수 차는 시간 차보다 항상 큼");
    }

    @Test
    void redisDown_submitStillGrades_rankingIs503Exception() {
        LettuceConnectionFactory dead = new LettuceConnectionFactory("127.0.0.1", 6399);
        dead.afterPropertiesSet();
        RedisTemplate<String, Object> deadTpl = new RedisConfig().redisTemplate(dead);
        deadTpl.afterPropertiesSet();
        StringRedisTemplate deadStr = new StringRedisTemplate(dead);
        MaterialQuizScoreService down = new MaterialQuizScoreService(deadTpl, deadStr, bootMapper(), 180, 3000);
        StoredScore s = StoredScore.builder().quizId(QUIZ).userId(A).score(80).correctCount(4).totalQuestions(5)
                .submittedAt(LocalDateTime.now()).selected(Map.of("q", "A")).build();
        assertFalse(down.record(s, Instant.now()).persisted(), "저장 실패는 false 로만 알리고 예외를 올리지 않는다");
        assertThrows(RankingUnavailableException.class, () -> down.ranking(QUIZ, A, 10));
        dead.destroy();
    }

    @Test
    void rankingJson_matchesAndroidContract_noUserIdOrEmail() throws Exception {
        submit(A, 5, 0);
        submit(B, 3, 0);
        ObjectMapper om = ctx.getBean(ObjectMapper.class);
        String json = om.writeValueAsString(service.ranking(A, MATERIAL, QUIZ, 50));
        JsonNode n = om.readTree(json);
        for (String f : List.of("materialId", "quizId", "rankingPolicy", "totalQuestions", "totalParticipants", "generatedAt", "entries", "me")) {
            assertTrue(n.has(f), "필드 " + f);
        }
        JsonNode e = n.get("entries").get(0);
        for (String f : List.of("rank", "nickname", "score", "correctCount", "totalQuestions", "attemptCount", "achievedAt", "isMe")) {
            assertTrue(e.has(f), "entry 필드 " + f);
        }
        assertFalse(json.contains("userId") || json.contains("email") || json.contains("@x"), json);
        assertTrue(n.get("me").get("isMe").asBoolean());
        assertTrue(n.get("entries").get(0).get("achievedAt").isTextual(), "achievedAt 은 ISO 문자열");
        @SuppressWarnings("unchecked")
        RedisTemplate<String, Object> tpl = (RedisTemplate<String, Object>) ctx.getBean("redisTemplate");
        String raw = (String) tpl.opsForHash().get(MaterialQuizScoreService.scoreKey(QUIZ), String.valueOf(A));
        assertTrue(raw.contains("\"bestAt\":\"20") && raw.contains("\"submittedAt\":\"20"), "Lua 가 기록한 값도 기존과 같은 ISO 형식: " + raw);
        String out = System.getenv("QUIZ_RANKING_IT_JSON_OUT");
        if (out != null) om.writeValue(new File(out), n);
    }
}
