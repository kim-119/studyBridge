package com.studybridge.api.ai.training;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.AiSigningKeys;
import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.contract.v1.TrainingSampleV1;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.entity.AiTrainingOutbox;
import com.studybridge.api.repository.AiTrainingConsentRepository;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 학습 동의 → 후보 outbox → ai07 전달 파이프라인(실제 PostgreSQL — SKIP LOCKED·unique·afterCommit 의미 검증).
 * 일회용 DB 로만 실행(운영 RDS 금지): SB_TEST_PG_URL=jdbc:postgresql://127.0.0.1:55432/sbtest (LearningLoopRecordPostgresTest 참고).
 */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(TrainingPipelinePostgresTest.Config.class)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@EnabledIfEnvironmentVariable(named = "SB_TEST_PG_URL", matches = "jdbc:postgresql://(127\\.0\\.0\\.1|localhost):.*")
class TrainingPipelinePostgresTest {

        static final String SAMPLE_KEY = "sample-key-for-tests-0123456789abcdef";
        static final String CONSENT_KEY = "consent-key-for-tests-0123456789abcde";
        static HttpServer server;
        static final List<Map<String, String>> hits = new CopyOnWriteArrayList<>();
        static final AtomicInteger status = new AtomicInteger(200);
        /** null 이면 경로별 ai07 최종 응답(STORED/CONSENT_WITHDRAWN/DELETED/FEEDBACK_RECORDED). */
        static final AtomicReference<String> replyOverride = new AtomicReference<>();
        static final AtomicReference<String> retryAfter = new AtomicReference<>();
        static final ShiftClock CLOCK = new ShiftClock();

        /** 실제 시스템 시각 + 조정 가능한 이동(서명 검증은 실제 now 와 비교하므로 고정 시계 대신 이동만 준다). */
        static final class ShiftClock extends Clock {
                final AtomicReference<Duration> shift = new AtomicReference<>(Duration.ZERO);

                @Override
                public ZoneId getZone() {
                        return ZoneOffset.UTC;
                }

                @Override
                public Clock withZone(ZoneId zone) {
                        return this;
                }

                @Override
                public Instant instant() {
                        return Instant.now().plus(shift.get());
                }
        }

        static String defaultReply(String path) {
                if (path.endsWith("/collect-v1")) {
                        return "{\"success\":true,\"status\":\"STORED\",\"modelWeightsErased\":false}";
                }
                if (path.endsWith("/consent-withdrawal")) {
                        return "{\"success\":true,\"status\":\"CONSENT_WITHDRAWN\",\"modelWeightsErased\":false}";
                }
                if (path.endsWith("/deletion")) {
                        return "{\"success\":true,\"status\":\"DELETED\",\"modelWeightsErased\":false}";
                }
                return "{\"success\":true,\"status\":\"FEEDBACK_RECORDED\",\"modelWeightsErased\":false}";
        }

        @DynamicPropertySource
        static void pg(DynamicPropertyRegistry r) {
                r.add("spring.datasource.url", () -> System.getenv("SB_TEST_PG_URL"));
                r.add("spring.datasource.username", () -> System.getenv().getOrDefault("SB_TEST_PG_USER", "sbtest"));
                r.add("spring.datasource.password", () -> System.getenv().getOrDefault("SB_TEST_PG_PASSWORD", "sbtest"));
                r.add("spring.jpa.hibernate.ddl-auto", () -> "create-drop");
        }

        @TestConfiguration
        static class Config {
                @Bean
                AiTrainingSettings settings() {
                        return AiTrainingSettings.forTest(true, true);
                }

                @Bean
                AiSigningKeys keys() {
                        return new AiSigningKeys("scope-key-for-tests-0123456789abcdefgh", CONSENT_KEY, SAMPLE_KEY,
                                        "pseudonym-secret-for-tests-0123456789", "internal-bearer-0123456789abcdef");
                }

                @Bean
                PseudonymousUserKeys pseudonyms(AiSigningKeys k) {
                        return new PseudonymousUserKeys(k);
                }

                @Bean
                TransactionTemplate transactionTemplate(PlatformTransactionManager tm) {
                        return new TransactionTemplate(tm);
                }

                @Bean(name = "fastApiWebClient")
                WebClient fastApiWebClient() throws Exception {
                        if (server == null) {
                                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                                server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(4));
                                server.createContext("/api/training-candidates", ex -> {
                                        byte[] body = ex.getRequestBody().readAllBytes();
                                        hits.add(Map.of("path", ex.getRequestURI().getPath(),
                                                        "sig", String.valueOf(ex.getRequestHeaders().getFirst("X-AI-Contract-Signature")),
                                                        "ts", String.valueOf(ex.getRequestHeaders().getFirst("X-AI-Contract-Timestamp")),
                                                        "consent", String.valueOf(ex.getRequestHeaders().getFirst("X-AI-Training-Consent")),
                                                        "rid", String.valueOf(ex.getRequestHeaders().getFirst("X-Request-Id")),
                                                        "body", new String(body, StandardCharsets.UTF_8)));
                                        String reply = replyOverride.get() != null ? replyOverride.get() : defaultReply(ex.getRequestURI().getPath());
                                        byte[] out = reply.getBytes(StandardCharsets.UTF_8);
                                        if (retryAfter.get() != null) {
                                                ex.getResponseHeaders().add("Retry-After", retryAfter.get());
                                        }
                                        ex.getResponseHeaders().add("Content-Type", "application/json");
                                        ex.sendResponseHeaders(status.get(), out.length);
                                        ex.getResponseBody().write(out);
                                        ex.close();
                                });
                                server.start();
                        }
                        return WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                }

                @Bean
                Clock clock() {
                        return CLOCK;
                }

                @Bean
                TrainingOutboxWriter writer(AiTrainingOutboxRepository r, Clock c) {
                        return new TrainingOutboxWriter(r, c);
                }

                @Bean
                TrainingConsentService consentService(AiTrainingConsentRepository c, AiTrainingOutboxRepository o, AiTrainingSettings s,
                                TrainingOutboxWriter w, PseudonymousUserKeys p, Clock clk) {
                        return new TrainingConsentService(c, o, s, w, p, clk);
                }

                @Bean
                TrainingCandidateCollector collector(AiTrainingSettings s, TrainingConsentService cs, TrainingOutboxWriter w,
                                PseudonymousUserKeys p, AiTrainingOutboxRepository o, AiTrainingConsentRepository c, Clock clk) {
                        return new TrainingCandidateCollector(s, cs, w, p, o, c, clk);
                }

                @Bean
                TrainingOutboxDispatcher dispatcher(AiTrainingOutboxRepository r, TransactionTemplate tx, WebClient fastApiWebClient,
                                AiTrainingSettings s, AiSigningKeys k, TrainingConsentService cs, PseudonymousUserKeys p, TrainingOutboxWriter w,
                                Clock clk) {
                        return new TrainingOutboxDispatcher(r, tx, fastApiWebClient, s, k, cs, p, w, clk);
                }
        }

        @Autowired
        TrainingConsentService consents;
        @Autowired
        TrainingCandidateCollector collector;
        @Autowired
        TrainingOutboxDispatcher dispatcher;
        @Autowired
        AiTrainingOutboxRepository outbox;
        @Autowired
        AiTrainingConsentRepository consentRepo;
        @Autowired
        TransactionTemplate tx;
        @Autowired
        PseudonymousUserKeys pseudonyms;
        @Autowired
        TrainingOutboxWriter writerBean;

        @BeforeEach
        void reset() {
                outbox.deleteAllInBatch();
                consentRepo.deleteAllInBatch();
                hits.clear();
                status.set(200);
                replyOverride.set(null);
                retryAfter.set(null);
                CLOCK.shift.set(Duration.ZERO);
        }

        @AfterEach
        void after() {
                status.set(200);
                replyOverride.set(null);
                retryAfter.set(null);
                CLOCK.shift.set(Duration.ZERO);
        }

        void makeAllDue() {
                tx.executeWithoutResult(st -> outbox.findAll().forEach(x -> {
                        x.setNextAttemptAt(Instant.now().minusSeconds(1));
                        outbox.save(x);
                }));
        }

        static GateDecision approved() {
                return new GateDecision(true, ResponseQualityV1.QualityStatus.APPROVED, 91.0, null, List.of(), "rqg-1.0.0", "bdbd181c33f2", 1, 3);
        }

        static TrainingCandidateCollector.Candidate candidate(long userId, String answer) {
                return new TrainingCandidateCollector.Candidate(userId, ResponseQualityV1.TaskType.STUDYMATE_BASIC, "req-ts-000001",
                                "3-way handshake 두 번째 단계는?", answer, null, List.of(), approved(), "qwen3:14b", "studymate-sse-2");
        }

        void grant(long userId) {
                consents.grant(userId, "tc-2026-11", true, "WEB");
        }

        @Test
        void withoutConsentNothingIsCollected() {
                assertEquals(TrainingCandidateCollector.Status.SKIPPED_NO_CONSENT, collector.onApproved(candidate(1L, "SYN-ACK")));
                assertEquals(0, outbox.count());
        }

        @Test
        void unapprovedAnswerIsNeverCollectedEvenWithConsent() {
                grant(2L);
                TrainingCandidateCollector.Candidate c = new TrainingCandidateCollector.Candidate(2L, ResponseQualityV1.TaskType.STUDYMATE_BASIC,
                                "r", "q", "a", null, List.of(), GateDecision.unavailable("EVALUATOR_TIMEOUT", 1, 0), null, null);
                assertEquals(TrainingCandidateCollector.Status.SKIPPED_NOT_APPROVED, collector.onApproved(c));
                assertEquals(0, outbox.count());
        }

        @Test
        void consentRequiresCurrentVersionAndAgeConfirmation() {
                assertEquals("CONSENT_VERSION_MISMATCH", assertThrows(TrainingConsentService.ConsentRejected.class,
                                () -> consents.grant(3L, "tc-2020-01", true, "WEB")).errorCode());
                assertEquals("AGE_CONFIRMATION_REQUIRED", assertThrows(TrainingConsentService.ConsentRejected.class,
                                () -> consents.grant(3L, "tc-2026-11", false, "WEB")).errorCode());
                assertEquals(false, consents.status(3L).granted());
        }

        @Test
        void approvedWithConsentIsEnqueuedOnceAsValidContract() throws Exception {
                grant(4L);
                assertEquals(TrainingCandidateCollector.Status.ENQUEUED, collector.onApproved(candidate(4L, "SYN-ACK 이다.")));
                assertEquals(TrainingCandidateCollector.Status.DUPLICATE, collector.onApproved(candidate(4L, "SYN-ACK 이다.")));
                assertEquals(1, outbox.count());
                AiTrainingOutbox row = outbox.findAll().get(0);
                TrainingSampleV1 s = ContractJson.STRICT.readValue(row.getPayloadJson(), TrainingSampleV1.class);
                assertTrue(TrainingSampleV1.validate(s).ok(), TrainingSampleV1.validate(s).list().toString());
                assertEquals(pseudonyms.of(4L), s.pseudonymousUserKey());
                assertTrue(!row.getPayloadJson().contains("\"userId\"") && !row.getPayloadJson().contains("\"4\""), "직접 식별자 금지");
                assertEquals(TrainingSampleV1.RightsStatus.UNKNOWN, s.rightsStatus());
                assertEquals(TrainingSampleV1.QualityLabel.UNLABELED, s.qualityLabel(), "80점 승인 ≠ 검증된 정답");
        }

        @Test
        void eventInsideRolledBackTransactionIsNotEnqueued() {
                grant(5L);
                tx.executeWithoutResult(st -> {
                        assertEquals(TrainingCandidateCollector.Status.DEFERRED_AFTER_COMMIT, collector.onApproved(candidate(5L, "롤백될 답")));
                        st.setRollbackOnly();
                });
                assertEquals(0, outbox.count());
                tx.executeWithoutResult(st -> collector.onApproved(candidate(5L, "커밋될 답")));
                assertEquals(1, outbox.count());
        }

        @Test
        void withdrawalCancelsPendingAndBlocksFurtherCollection() {
                grant(6L);
                collector.onApproved(candidate(6L, "답 1"));
                collector.onApproved(candidate(6L, "답 2"));
                consents.withdraw(6L, "WEB");
                List<AiTrainingOutbox> rows = outbox.findAll();
                assertEquals(2, rows.stream().filter(r -> "SAMPLE".equals(r.getKind()) && "CANCELLED".equals(r.getStatus())
                                && r.getPayloadJson() == null).count(), "미전송 후보는 즉시 취소·원문 삭제");
                assertEquals(1, rows.stream().filter(r -> "CONSENT_WITHDRAWAL".equals(r.getKind()) && "PENDING".equals(r.getStatus())).count());
                assertEquals(TrainingCandidateCollector.Status.SKIPPED_NO_CONSENT, collector.onApproved(candidate(6L, "답 3")));
                // 재동의해도 과거(철회 전) 이벤트를 소급 수집하지 않는다 — 새 승인 답변만 대상
                grant(6L);
                assertEquals(TrainingCandidateCollector.Status.ENQUEUED, collector.onApproved(candidate(6L, "답 4")));
        }

        @Test
        void dispatcherSignsExactBytesAndClearsPayloadOnSuccess() {
                grant(7L);
                collector.onApproved(candidate(7L, "SYN-ACK"));
                String stored = outbox.findAll().get(0).getPayloadJson();
                assertEquals(1, dispatcher.dispatchOnce());
                Map<String, String> h = hits.get(0);
                assertEquals("/api/training-candidates/collect-v1", h.get("path"));
                assertEquals(stored, h.get("body"), "저장 바이트 그대로 전송(재직렬화 금지)");
                AiContractSigning.verifyBody(SAMPLE_KEY.getBytes(StandardCharsets.UTF_8), h.get("body").getBytes(StandardCharsets.UTF_8),
                                h.get("sig"), h.get("ts"), System.currentTimeMillis() / 1000);
                AiTrainingOutbox row = outbox.findAll().get(0);
                assertEquals(row.getEventId(), h.get("rid"));
                AiContractSigning.ConsentClaims claims = AiContractSigning.verifyConsentToken(CONSENT_KEY.getBytes(StandardCharsets.UTF_8),
                                h.get("consent"), row.getEventId(), pseudonyms.of(7L), System.currentTimeMillis() / 1000);
                assertTrue(claims.scope().contains("MODEL_TRAINING"));
                assertEquals("SENT", row.getStatus());
                assertNull(row.getPayloadJson(), "전송 후 원문을 남기지 않는다");
                assertEquals(0, dispatcher.dispatchOnce(), "재전송 없음");
        }

        @Test
        void transientFailureRetriesWithBackoffThenDeadLetters() {
                grant(8L);
                collector.onApproved(candidate(8L, "SYN-ACK"));
                status.set(503);
                dispatcher.dispatchOnce();
                AiTrainingOutbox r = outbox.findAll().get(0);
                assertEquals("PENDING", r.getStatus());
                assertEquals(1, r.getAttempts());
                assertTrue(r.getNextAttemptAt().isAfter(Instant.now()), "백오프");
                assertNotNull(r.getPayloadJson());
                for (int i = 0; i < 3; i++) {
                        makeAllDue();
                        dispatcher.dispatchOnce();
                }
                r = outbox.findAll().get(0);
                assertEquals("DEAD", r.getStatus(), "max-attempts(3) 초과");
                assertNull(r.getPayloadJson());
        }

        @Test
        void contractRejectionIsDeadImmediately() {
                grant(9L);
                collector.onApproved(candidate(9L, "SYN-ACK"));
                status.set(422);
                dispatcher.dispatchOnce();
                assertEquals("DEAD", outbox.findAll().get(0).getStatus());
                assertTrue(outbox.findAll().get(0).getLastErrorCode().startsWith("HTTP_422"));
        }

        @Test
        void withdrawnBeforeSendIsNeverTransmitted() {
                grant(10L);
                collector.onApproved(candidate(10L, "SYN-ACK"));
                // 철회 직전 경합: 행을 IN_FLIGHT 이전 상태(PENDING)로 두고 동의만 철회 기록(취소 UPDATE 를 건너뛴 경우 가정)
                consentRepo.save(com.studybridge.api.entity.AiTrainingConsent.builder().userId(10L).purpose("MODEL_TRAINING")
                                .status("WITHDRAWN").consentVersion("tc-2026-11").build());
                dispatcher.dispatchOnce();
                assertEquals(0, hits.stream().filter(m -> m.get("path").endsWith("collect-v1")).count());
                assertEquals("CANCELLED", outbox.findAll().get(0).getStatus());
        }

        @Test
        void materialDeletionCancelsAndRequestsDeletion() {
                grant(11L);
                TrainingCandidateCollector.Candidate pdf = new TrainingCandidateCollector.Candidate(11L, ResponseQualityV1.TaskType.PDF_SUMMARY,
                                "req-ts-000011", "요약해줘", "TCP 는 3-way handshake 로 연결한다.", 345L,
                                List.of(new TrainingSampleV1.Evidence("PDF_ORIGINAL", 345L, null, null, null, "m345-c0", "3-way handshake")),
                                approved(), "qwen3:14b", "material-summary-v1");
                assertEquals(TrainingCandidateCollector.Status.ENQUEUED, collector.onApproved(pdf));
                assertEquals(TrainingSampleV1.RightsStatus.THIRD_PARTY_UNVERIFIED, readSample(outbox.findAll().get(0)).rightsStatus(),
                                "업로드만으로 권리 확인 아님");
                tx.executeWithoutResult(s -> collector.onMaterialDeleted(11L, 345L));
                List<AiTrainingOutbox> rows = outbox.findAll();
                assertEquals(1, rows.stream().filter(r -> "SAMPLE".equals(r.getKind()) && "CANCELLED".equals(r.getStatus())).count());
                AiTrainingOutbox del = rows.stream().filter(r -> "DELETION".equals(r.getKind())).findFirst().orElseThrow();
                assertEquals(consents.deletionTrackingIdForMaterial(345L), del.getDeletionTrackingId());
                assertTrue(del.getDeletionTrackingId().matches("[A-Za-z0-9._:\\-]{8,128}"), "ai07 DeletionRequest 정규식");
                dispatcher.dispatchOnce();
                assertTrue(hits.stream().anyMatch(m -> m.get("path").endsWith("/deletion") && m.get("body").contains(del.getDeletionTrackingId())));
        }

        @Test
        void concurrentDispatchersSendEachRowOnce() throws Exception {
                grant(12L);
                for (int i = 0; i < 10; i++) {
                        collector.onApproved(candidate(12L, "답 " + i));
                }
                Thread a = new Thread(() -> dispatcher.dispatchOnce());
                Thread b = new Thread(() -> dispatcher.dispatchOnce());
                a.start();
                b.start();
                a.join();
                b.join();
                dispatcher.dispatchOnce();
                assertEquals(10, hits.size(), "SKIP LOCKED: 두 디스패처가 같은 행을 중복 전송하지 않는다");
                assertEquals(10, hits.stream().map(m -> m.get("rid")).distinct().count());
        }

        // ── 독립 리뷰 회귀(2026-11-04) ──────────────────────────────────────────────

        @Test
        void revocationIsNeverDeadLettered() {
                grant(13L);
                consents.withdraw(13L, "WEB");
                status.set(422);
                for (int i = 0; i < 5; i++) {
                        makeAllDue();
                        dispatcher.dispatchOnce();
                }
                AiTrainingOutbox rv = outbox.findAll().stream().filter(r -> "CONSENT_WITHDRAWAL".equals(r.getKind())).findFirst().orElseThrow();
                assertEquals("PENDING", rv.getStatus(), "철회 요청은 max-attempts 를 넘어도 포기하지 않는다");
                assertNotNull(rv.getPayloadJson());
                status.set(200);
                makeAllDue();
                dispatcher.dispatchOnce();
                assertEquals("SENT", outbox.findById(rv.getId()).orElseThrow().getStatus());
        }

        @Test
        void missingSigningKeyDoesNotBurnAttemptsOrPayload() {
                grant(14L);
                collector.onApproved(candidate(14L, "SYN-ACK"));
                AiSigningKeys noKeys = new AiSigningKeys("", "", "", "pseudonym-secret-for-tests-0123456789", "");
                TrainingOutboxDispatcher d = new TrainingOutboxDispatcher(outbox, tx, WebClient.create("http://127.0.0.1:9"),
                                AiTrainingSettings.forTest(true, true), noKeys, consents, pseudonyms, writerBean, CLOCK);
                for (int i = 0; i < 5; i++) {
                        makeAllDue();
                        d.dispatchOnce();
                }
                AiTrainingOutbox r = outbox.findAll().get(0);
                assertEquals("PENDING", r.getStatus());
                assertEquals(0, r.getAttempts(), "키 미구성은 시도 횟수를 쓰지 않는다");
                assertNotNull(r.getPayloadJson(), "키를 넣으면 재개할 수 있게 원문 보존");
                assertEquals(0, hits.size());
        }

        @Test
        void sampleCollectedBeforeWithdrawalIsNotSentAfterReconsent() {
                grant(15L);
                collector.onApproved(candidate(15L, "철회 전 답"));
                // 철회 취소 UPDATE 를 놓친 경합을 가정: WITHDRAWN 행만 추가 후 재동의
                consentRepo.save(com.studybridge.api.entity.AiTrainingConsent.builder().userId(15L).purpose("MODEL_TRAINING")
                                .status("WITHDRAWN").consentVersion("tc-2026-11").build());
                grant(15L);
                dispatcher.dispatchOnce();
                assertEquals(0, hits.size(), "재동의는 철회 전 수집분을 되살리지 않는다");
                AiTrainingOutbox r = outbox.findAll().get(0);
                assertEquals("CANCELLED", r.getStatus());
                assertEquals("CONSENT_RENEWED_AFTER_COLLECTION", r.getLastErrorCode());
        }

        @Test
        void cancelledInFlightRowIsNotResurrected() {
                grant(16L);
                collector.onApproved(candidate(16L, "답"));
                AiTrainingOutbox r = outbox.findAll().get(0);
                r.setStatus("CANCELLED");
                r.setPayloadJson(null);
                dispatcher.apply(r, TrainingOutboxDispatcher.Outcome.of("RETRY", "HTTP_503"));
                assertEquals("CANCELLED", r.getStatus());
        }

        @Test
        void enqueueInsideAnotherAfterCommitCallbackIsNotLost() {
                grant(17L);
                tx.executeWithoutResult(st -> org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
                                new org.springframework.transaction.support.TransactionSynchronization() {
                                        @Override
                                        public void afterCommit() {
                                                collector.onApproved(candidate(17L, "afterCommit 안에서 수집"));
                                        }
                                }));
                assertEquals(1, outbox.count(), "afterCommit 안에서 등록돼도 afterCompletion 으로 한 번 적재");
        }

        // ── Phase C (2026-11-04): C-TIME-3 · training-control.v1(C-SIG-2) · 응답 판정 ───────────────────

        static final long NOW_TOLERANCE_S = 5;

        @Test
        void consentTimestampIsTheRealUtcInstantInEveryJvmTimeZone() throws Exception {
                java.util.TimeZone original = java.util.TimeZone.getDefault();
                try {
                        long uid = 100L;
                        for (String tz : List.of("Asia/Seoul", "UTC", "America/New_York", "Australia/Lord_Howe")) {
                                java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone(tz));
                                uid++;
                                Instant before = Instant.now();
                                grant(uid);
                                Instant after = Instant.now();
                                com.studybridge.api.entity.AiTrainingConsent c = consentRepo.findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(uid,
                                                "MODEL_TRAINING").orElseThrow();
                                assertTrue(!c.getCreatedAt().isBefore(before.minusMillis(1)) && !c.getCreatedAt().isAfter(after.plusMillis(1)),
                                                tz + ": DB 왕복 후에도 실제 순간(9시간 어긋남 없음) " + c.getCreatedAt() + " vs " + before);
                                collector.onApproved(candidate(uid, "TZ " + tz));
                                AiTrainingOutbox row = outbox.findAll().stream().filter(r -> r.getUserId() == uid0(c)).findFirst().orElseThrow();
                                TrainingSampleV1 s = readSample(row);
                                assertTrue(s.consentTimestamp().toInstant().equals(c.getCreatedAt()), tz + ": consentTimestamp == 동의 행 순간");
                                assertTrue(s.consentTimestamp().toInstant().isBefore(Instant.now().plusSeconds(NOW_TOLERANCE_S)), tz + ": 미래 아님");
                                hits.clear();
                                dispatcher.dispatchOnce();
                                Map<String, String> h = hits.stream().filter(x -> x.get("path").endsWith("/collect-v1")
                                                && row.getEventId().equals(x.get("rid"))).findFirst().orElseThrow();
                                AiContractSigning.ConsentClaims claims = AiContractSigning.verifyConsentToken(CONSENT_KEY.getBytes(StandardCharsets.UTF_8),
                                                h.get("consent"), row.getEventId(), pseudonyms.of(uid), Instant.now().getEpochSecond());
                                assertEquals(s.consentTimestamp().toInstant(), java.time.OffsetDateTime.parse(claims.consentTimestamp()).toInstant(),
                                                tz + ": 토큰 ct == 샘플 consentTimestamp(ai07 CONSENT_TIMESTAMP_MISMATCH 방지)");
                                consents.withdraw(uid, "WEB");
                                AiTrainingOutbox cw = outbox.findAll().stream().filter(r -> r.getUserId() == uid0(c) && "CONSENT_WITHDRAWAL".equals(r.getKind()))
                                                .findFirst().orElseThrow();
                                com.studybridge.api.ai.contract.v1.TrainingControlV1 m = com.studybridge.api.ai.contract.v1.TrainingControlV1.parse(cw.getPayloadJson());
                                assertTrue(m.issuedAt().toInstant().isAfter(c.getCreatedAt()), tz + ": 철회 issuedAt > 동의 시각");
                                assertEquals(ZoneOffset.UTC, m.issuedAt().getOffset(), "issuedAt 은 UTC 표기");
                        }
                } finally {
                        java.util.TimeZone.setDefault(original);
                }
        }

        static long uid0(com.studybridge.api.entity.AiTrainingConsent c) {
                return c.getUserId();
        }

        @Test
        void consentTimelineIsStrictlyMonotonicEvenWhenClockStepsBack() {
                grant(120L);
                CLOCK.shift.set(Duration.ofHours(-2)); // NTP 역행·잘못된 시계
                consents.withdraw(120L, "WEB");
                grant(120L);
                List<com.studybridge.api.entity.AiTrainingConsent> rows = consentRepo.findAll().stream().filter(c -> c.getUserId() == 120L)
                                .sorted(java.util.Comparator.comparing(com.studybridge.api.entity.AiTrainingConsent::getId)).toList();
                assertEquals(List.of("GRANTED", "WITHDRAWN", "GRANTED"), rows.stream().map(com.studybridge.api.entity.AiTrainingConsent::getStatus).toList());
                assertTrue(rows.get(0).getCreatedAt().isBefore(rows.get(1).getCreatedAt()) && rows.get(1).getCreatedAt().isBefore(rows.get(2).getCreatedAt()),
                                "동의 < 철회 < 재동의 (ai07 철회 범위 판정의 근거)");
                grant(120L);
                assertEquals(3, consentRepo.findAll().stream().filter(c -> c.getUserId() == 120L).count(), "같은 버전 재동의 클릭은 새 행을 만들지 않는다(멱등)");
        }

        @Test
        void withdrawalIsSignedTrainingControlV1WithExactBytesAndRequestIdBinding() {
                grant(121L);
                consents.withdraw(121L, "WEB");
                AiTrainingOutbox cw = outbox.findAll().stream().filter(r -> "CONSENT_WITHDRAWAL".equals(r.getKind())).findFirst().orElseThrow();
                String stored = cw.getPayloadJson();
                dispatcher.dispatchOnce();
                Map<String, String> h = hits.stream().filter(m -> m.get("path").endsWith("/consent-withdrawal")).findFirst().orElseThrow();
                assertEquals(stored, h.get("body"), "저장 바이트 그대로");
                AiContractSigning.verifyBody(SAMPLE_KEY.getBytes(StandardCharsets.UTF_8), h.get("body").getBytes(StandardCharsets.UTF_8), h.get("sig"),
                                h.get("ts"), Instant.now().getEpochSecond());
                com.studybridge.api.ai.contract.v1.TrainingControlV1 m = com.studybridge.api.ai.contract.v1.TrainingControlV1.parse(h.get("body"));
                assertEquals(m.eventId(), h.get("rid"), "X-Request-Id == eventId");
                assertEquals("training-control.v1", m.schemaVersion());
                assertEquals(pseudonyms.of(121L), m.pseudonymousUserKey());
                assertEquals(List.of("MODEL_TRAINING"), m.scope());
                assertTrue(!h.get("body").contains("\"userId\"") && !h.get("body").contains("121"), "직접 식별자 금지");
                AiTrainingOutbox after = outbox.findById(cw.getId()).orElseThrow();
                assertEquals("SENT", after.getStatus());
                assertEquals("CONSENT_WITHDRAWN", after.getResultStatus());
                assertEquals("null", h.get("consent"), "제어 메시지에는 동의 토큰을 싣지 않는다");
        }

        @Test
        void retriesResignSameBytesWithSameEventId() {
                grant(122L);
                consents.withdraw(122L, "WEB");
                status.set(503);
                retryAfter.set("2");
                dispatcher.dispatchOnce();
                AiTrainingOutbox r = outbox.findAll().stream().filter(x -> "CONSENT_WITHDRAWAL".equals(x.getKind())).findFirst().orElseThrow();
                assertEquals("PENDING", r.getStatus());
                assertTrue(r.getNextAttemptAt().isAfter(Instant.now().plusSeconds(1)), "Retry-After 하한");
                CLOCK.shift.set(Duration.ofSeconds(3)); // 다른 서명 timestamp
                makeAllDue();
                dispatcher.dispatchOnce();
                List<Map<String, String>> sent = hits.stream().filter(m -> m.get("path").endsWith("/consent-withdrawal")).toList();
                assertEquals(2, sent.size());
                assertEquals(sent.get(0).get("body"), sent.get(1).get("body"), "재시도는 본문을 바꾸지 않는다");
                assertEquals(sent.get(0).get("rid"), sent.get(1).get("rid"), "eventId 불변");
                assertTrue(!sent.get(0).get("ts").equals(sent.get(1).get("ts")), "헤더 timestamp 만 갱신");
                assertEquals("PENDING", outbox.findById(r.getId()).orElseThrow().getStatus(), "503 은 계속 재시도(성공 아님)");
        }

        @Test
        void conflict409IsNeverSentAndControlIsReissuedWithSameIssuedAt() {
                grant(123L);
                consents.withdraw(123L, "WEB");
                AiTrainingOutbox first = outbox.findAll().stream().filter(x -> "CONSENT_WITHDRAWAL".equals(x.getKind())).findFirst().orElseThrow();
                status.set(409);
                replyOverride.set("{\"success\":false,\"status\":\"EVENT_ID_CONFLICT\",\"reasons\":[\"EVENT_ID_REUSED_WITH_DIFFERENT_BODY\"]}");
                dispatcher.dispatchOnce();
                AiTrainingOutbox closed = outbox.findById(first.getId()).orElseThrow();
                assertEquals("CONFLICT", closed.getStatus(), "409 = 같은 eventId 다른 본문 → SENT 금지");
                assertTrue(closed.getLastErrorCode().startsWith("HTTP_409_REISSUED:"));
                List<AiTrainingOutbox> cws = outbox.findAll().stream().filter(x -> "CONSENT_WITHDRAWAL".equals(x.getKind())).toList();
                assertEquals(2, cws.size());
                AiTrainingOutbox again = cws.stream().filter(x -> !x.getId().equals(first.getId())).findFirst().orElseThrow();
                var a = com.studybridge.api.ai.contract.v1.TrainingControlV1.parse(closed.getPayloadJson());
                var b = com.studybridge.api.ai.contract.v1.TrainingControlV1.parse(again.getPayloadJson());
                assertTrue(!a.eventId().equals(b.eventId()));
                assertEquals(a.issuedAt(), b.issuedAt(), "철회 시각은 그대로(재동의 이후 후보를 지우지 않게)");
                status.set(200);
                replyOverride.set(null);
                dispatcher.dispatchOnce();
                assertEquals("SENT", outbox.findById(again.getId()).orElseThrow().getStatus());
        }

        @Test
        void conflict409OnSampleIsDeadNotSent() {
                grant(124L);
                collector.onApproved(candidate(124L, "충돌"));
                status.set(409);
                replyOverride.set("{\"success\":false,\"status\":\"EVENT_ID_CONFLICT\",\"reasons\":[\"EVENT_ID_REUSED_WITH_DIFFERENT_BODY\"]}");
                dispatcher.dispatchOnce();
                AiTrainingOutbox r = outbox.findAll().get(0);
                assertEquals("DEAD", r.getStatus());
                assertTrue(r.getLastErrorCode().contains("EVENT_ID_CONFLICT"));
                assertNull(r.getPayloadJson());
        }

        @Test
        void processingConflict409IsRetriedNotSent() {
                grant(125L);
                collector.onApproved(candidate(125L, "경합"));
                status.set(409);
                replyOverride.set("{\"errorCode\":\"CONCURRENT_MODIFICATION\"}");
                dispatcher.dispatchOnce();
                assertEquals("PENDING", outbox.findAll().get(0).getStatus());
        }

        @Test
        void unfinished2xxIsRetriedAndKnownFinalStatusesAreRecorded() {
                grant(126L);
                collector.onApproved(candidate(126L, "보류"));
                replyOverride.set("{\"success\":true,\"status\":\"DEFERRED\"}");
                dispatcher.dispatchOnce();
                AiTrainingOutbox r = outbox.findAll().get(0);
                assertEquals("PENDING", r.getStatus(), "200 DEFERRED 는 끝난 게 아니다");
                assertTrue(r.getLastErrorCode().startsWith("UNFINISHED_2XX"));
                replyOverride.set("{\"success\":true}");
                makeAllDue();
                dispatcher.dispatchOnce();
                assertEquals("PENDING", outbox.findAll().get(0).getStatus(), "status 없는 200 도 성공으로 보지 않는다");
                replyOverride.set("{\"success\":false,\"status\":\"REJECTED_CONSENT_WITHDRAWN\"}");
                makeAllDue();
                dispatcher.dispatchOnce();
                r = outbox.findAll().get(0);
                assertEquals("SENT", r.getStatus(), "ai07 최종 판정(거절도 최종)");
                assertEquals("REJECTED_CONSENT_WITHDRAWN", r.getResultStatus());
        }

        @Test
        void controlMessagesGoFirstAndReconsentSamplesFollowTheOldWithdrawal() throws Exception {
                grant(127L);
                collector.onApproved(candidate(127L, "철회 전 답"));
                consents.withdraw(127L, "WEB");
                grant(127L);
                collector.onApproved(candidate(127L, "재동의 후 답"));
                dispatcher.dispatchOnce();
                List<String> order = hits.stream().map(m -> m.get("path").substring(m.get("path").lastIndexOf('/') + 1)).toList();
                assertEquals(List.of("consent-withdrawal", "collect-v1"), order, "tombstone 먼저, 철회 전 샘플은 전송 안 됨");
                var cw = com.studybridge.api.ai.contract.v1.TrainingControlV1.parse(hits.get(0).get("body"));
                TrainingSampleV1 s = ContractJson.STRICT.readValue(hits.get(1).get("body"), TrainingSampleV1.class);
                assertTrue(s.consentTimestamp().isAfter(cw.issuedAt()),
                                "재동의 샘플의 consentTimestamp > 옛 철회 issuedAt → 늦게 도착한 철회가 새 후보를 지우지 않는다");
        }

        @Test
        void accountDeletionWithdrawsAndRequestsUserAndMaterialDeletion() {
                grant(128L);
                TrainingCandidateCollector.Candidate pdf = new TrainingCandidateCollector.Candidate(128L, ResponseQualityV1.TaskType.PDF_SUMMARY,
                                "req-ts-000128", "요약", "TCP 는 연결 지향이다.", 900L,
                                List.of(new TrainingSampleV1.Evidence("PDF_ORIGINAL", 900L, null, null, null, "m900-c0", "연결 지향")),
                                approved(), "qwen3:14b", "material-summary-v1");
                collector.onApproved(pdf);
                dispatcher.dispatchOnce(); // 샘플이 ai07 에 도달
                collector.onApproved(candidate(128L, "아직 안 보낸 답"));
                int n = consents.onAccountDeleted(128L);
                assertEquals(2, n, "사용자 단위 + 자료 단위 삭제 요청");
                List<AiTrainingOutbox> rows = outbox.findAll().stream().filter(r -> r.getUserId() == 128L).toList();
                assertEquals(1, rows.stream().filter(r -> "SAMPLE".equals(r.getKind()) && "CANCELLED".equals(r.getStatus())).count());
                assertEquals(1, rows.stream().filter(r -> "CONSENT_WITHDRAWAL".equals(r.getKind())).count());
                assertTrue(rows.stream().filter(r -> "DELETION".equals(r.getKind())).map(AiTrainingOutbox::getDeletionTrackingId).toList()
                                .containsAll(List.of(consents.deletionTrackingIdForUser(128L), consents.deletionTrackingIdForMaterial(900L))));
                assertEquals("WITHDRAWN", consentRepo.findTopByUserIdAndPurposeOrderByCreatedAtDescIdDesc(128L, "MODEL_TRAINING").orElseThrow().getStatus());
                hits.clear();
                dispatcher.dispatchOnce();
                assertEquals(3, hits.size());
                assertTrue(hits.stream().allMatch(m -> m.get("path").endsWith("/consent-withdrawal") || m.get("path").endsWith("/deletion")));
                assertEquals(0, consents.onAccountDeleted(129L), "동의 이력 없으면 요청 없음");
        }

        @Test
        void feedbackWaitsForTargetSampleAndNegativeOnPendingCancels() {
                grant(130L);
                collector.onApproved(candidate(130L, "피드백 대상"));
                assertEquals(TrainingCandidateCollector.Status.ENQUEUED, collector.onAnswerFeedback(130L, ResponseQualityV1.TaskType.STUDYMATE_BASIC,
                                "3-way handshake 두 번째 단계는?", "피드백 대상", 1, "HELPFUL"));
                AiTrainingOutbox sample = outbox.findAll().stream().filter(r -> "SAMPLE".equals(r.getKind())).findFirst().orElseThrow();
                AiTrainingOutbox fb = outbox.findAll().stream().filter(r -> "FEEDBACK".equals(r.getKind())).findFirst().orElseThrow();
                tx.executeWithoutResult(st -> {
                        AiTrainingOutbox x = outbox.findById(sample.getId()).orElseThrow();
                        x.setNextAttemptAt(Instant.now().plusSeconds(3600)); // 샘플이 아직 전송 전인 상황
                        outbox.save(x);
                });
                dispatcher.dispatchOnce();
                AiTrainingOutbox fbAfter = outbox.findById(fb.getId()).orElseThrow();
                assertEquals("PENDING", fbAfter.getStatus(), "대상 샘플 전송 전 → 미룸");
                assertEquals(0, fbAfter.getAttempts(), "미룸은 시도로 세지 않는다");
                makeAllDue();
                dispatcher.dispatchOnce();
                makeAllDue();
                dispatcher.dispatchOnce();
                Map<String, String> h = hits.stream().filter(m -> m.get("path").endsWith("/feedback")).findFirst().orElseThrow();
                var m = com.studybridge.api.ai.contract.v1.TrainingControlV1.parse(h.get("body"));
                assertEquals(sample.getEventId(), m.candidateEventId());
                assertNull(m.contentHash(), "candidateEventId XOR contentHash");
                assertEquals(1, m.score());
                assertEquals("SENT", outbox.findById(fb.getId()).orElseThrow().getStatus());
                // 부정 피드백 + 아직 안 보낸 샘플 → 보내지 않고 취소
                collector.onApproved(candidate(130L, "나쁜 답"));
                assertEquals(TrainingCandidateCollector.Status.CANCELLED_PENDING, collector.onAnswerFeedback(130L,
                                ResponseQualityV1.TaskType.STUDYMATE_BASIC, "3-way handshake 두 번째 단계는?", "나쁜 답", -1, null));
                assertEquals(TrainingCandidateCollector.Status.SKIPPED_NO_CANDIDATE, collector.onAnswerFeedback(130L,
                                ResponseQualityV1.TaskType.STUDYMATE_BASIC, "없는 질문", "없는 답", 1, null));
        }

        @Test
        void expiredLeaseIsTakenOverAfterWorkerCrash() {
                grant(131L);
                collector.onApproved(candidate(131L, "크래시"));
                tx.executeWithoutResult(st -> {
                        AiTrainingOutbox x = outbox.findAll().get(0);
                        x.setStatus("IN_FLIGHT"); // 전송 도중 프로세스가 죽은 상태
                        x.setAttempts(1);
                        x.setLeaseUntil(Instant.now().minusSeconds(1));
                        outbox.save(x);
                });
                dispatcher.dispatchOnce();
                AiTrainingOutbox r = outbox.findAll().get(0);
                assertEquals("SENT", r.getStatus(), "lease 만료 행은 다른 워커/재시작 후 인수");
                assertEquals(2, r.getAttempts());
                assertEquals(1, hits.size(), "같은 eventId 로 재전송(ai07 원장이 1회 처리)");
        }

        @Test
        void controlNeverDeadOn422ButSampleIs() {
                grant(132L);
                collector.onApproved(candidate(132L, "계약"));
                tx.executeWithoutResult(st -> collector.onMaterialDeleted(132L, 77L));
                status.set(422);
                dispatcher.dispatchOnce();
                List<AiTrainingOutbox> rows = outbox.findAll().stream().filter(r -> r.getUserId() == 132L).toList();
                assertEquals("PENDING", rows.stream().filter(r -> "DELETION".equals(r.getKind())).findFirst().orElseThrow().getStatus(),
                                "삭제 요청은 422 여도 포기하지 않는다(ai07 계약 수정 후 재개)");
                assertEquals("DEAD", rows.stream().filter(r -> "SAMPLE".equals(r.getKind())).findFirst().orElseThrow().getStatus(),
                                "샘플은 422 = 계약 위반 → DEAD(원문 삭제)");
        }

        /**
         * ai07(Python) 교차 검증용 산출물. SB_TRAINING_XLANG_OUT 이 있으면 실제 전송 요청(본문·서명·헤더·동의 토큰)을 JSON 으로 남긴다.
         * 검증: tools/verify_training_requests_ai07.py 가 ai07 verify_control / verify_body / verify_consent_token / parse_sample_json 으로 판정.
         */
        @Test
        @EnabledIfEnvironmentVariable(named = "SB_TRAINING_XLANG_OUT", matches = ".+")
        void dumpRealRequestsForAi07Verification() throws Exception {
                java.util.TimeZone original = java.util.TimeZone.getDefault();
                java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("Asia/Seoul")); // 운영 컨테이너와 같은 TZ
                try {
                        grant(140L);
                        collector.onApproved(candidate(140L, "교차 검증 답"));
                        TrainingCandidateCollector.Candidate pdf = new TrainingCandidateCollector.Candidate(140L, ResponseQualityV1.TaskType.PDF_SUMMARY,
                                        "req-ts-000140", "요약", "UDP 는 비연결형이다.", 901L,
                                        List.of(new TrainingSampleV1.Evidence("PDF_ORIGINAL", 901L, null, null, null, "m901-c0", "비연결형")),
                                        approved(), "qwen3:14b", "material-summary-v1");
                        collector.onApproved(pdf);
                        dispatcher.dispatchOnce();
                        collector.onAnswerFeedback(140L, ResponseQualityV1.TaskType.STUDYMATE_BASIC, "3-way handshake 두 번째 단계는?", "교차 검증 답", -1,
                                        "WRONG");
                        tx.executeWithoutResult(st -> collector.onMaterialDeleted(140L, 901L));
                        consents.withdraw(140L, "WEB");
                        dispatcher.dispatchOnce();
                        List<Map<String, Object>> out = new java.util.ArrayList<>();
                        for (Map<String, String> h : hits) {
                                Map<String, Object> m = new java.util.LinkedHashMap<>(h);
                                m.put("sub", pseudonyms.of(140L));
                                m.put("dumpedAt", Instant.now().getEpochSecond());
                                out.add(m);
                        }
                        java.nio.file.Path p = java.nio.file.Path.of(System.getenv("SB_TRAINING_XLANG_OUT"));
                        java.nio.file.Files.writeString(p, new com.fasterxml.jackson.databind.ObjectMapper().writerWithDefaultPrettyPrinter()
                                        .writeValueAsString(Map.of("sampleKey", SAMPLE_KEY, "consentKey", CONSENT_KEY, "requests", out)));
                        assertEquals(5, hits.size(), "SAMPLE 2 + FEEDBACK 1 + DELETION 1 + CONSENT_WITHDRAWAL 1");
                } finally {
                        java.util.TimeZone.setDefault(original);
                }
        }

        static TrainingSampleV1 readSample(AiTrainingOutbox r) {
                try {
                        return ContractJson.STRICT.readValue(r.getPayloadJson(), TrainingSampleV1.class);
                } catch (Exception e) {
                        throw new IllegalStateException(e);
                }
        }
}
