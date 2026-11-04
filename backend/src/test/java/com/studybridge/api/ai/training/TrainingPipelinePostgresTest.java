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
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
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
                                        byte[] out = "{\"success\":true,\"status\":\"COLLECTED\"}".getBytes(StandardCharsets.UTF_8);
                                        ex.sendResponseHeaders(status.get(), out.length);
                                        ex.getResponseBody().write(out);
                                        ex.close();
                                });
                                server.start();
                        }
                        return WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                }

                @Bean
                TrainingOutboxWriter writer(AiTrainingOutboxRepository r) {
                        return new TrainingOutboxWriter(r);
                }

                @Bean
                TrainingConsentService consentService(AiTrainingConsentRepository c, AiTrainingOutboxRepository o, AiTrainingSettings s,
                                TrainingOutboxWriter w, PseudonymousUserKeys p) {
                        return new TrainingConsentService(c, o, s, w, p);
                }

                @Bean
                TrainingCandidateCollector collector(AiTrainingSettings s, TrainingConsentService cs, TrainingOutboxWriter w,
                                PseudonymousUserKeys p, AiTrainingOutboxRepository o, AiTrainingConsentRepository c) {
                        return new TrainingCandidateCollector(s, cs, w, p, o, c);
                }

                @Bean
                TrainingOutboxDispatcher dispatcher(AiTrainingOutboxRepository r, TransactionTemplate tx, WebClient fastApiWebClient,
                                AiTrainingSettings s, AiSigningKeys k, TrainingConsentService cs, PseudonymousUserKeys p) {
                        return new TrainingOutboxDispatcher(r, tx, fastApiWebClient, s, k, cs, p);
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

        @BeforeEach
        void reset() {
                outbox.deleteAllInBatch();
                consentRepo.deleteAllInBatch();
                hits.clear();
                status.set(200);
        }

        @AfterEach
        void after() {
                status.set(200);
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
                assertEquals(1, rows.stream().filter(r -> "REVOCATION".equals(r.getKind()) && "PENDING".equals(r.getStatus())).count());
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
                assertTrue(r.getNextAttemptAt().isAfter(LocalDateTime.now()), "백오프");
                assertNotNull(r.getPayloadJson());
                for (int i = 0; i < 3; i++) {
                        tx.executeWithoutResult(s -> outbox.findAll().forEach(x -> x.setNextAttemptAt(LocalDateTime.now().minusSeconds(1))));
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
                assertEquals("HTTP_422", outbox.findAll().get(0).getLastErrorCode());
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
                        tx.executeWithoutResult(st -> outbox.findAll().forEach(x -> x.setNextAttemptAt(LocalDateTime.now().minusSeconds(1))));
                        dispatcher.dispatchOnce();
                }
                AiTrainingOutbox rv = outbox.findAll().stream().filter(r -> "REVOCATION".equals(r.getKind())).findFirst().orElseThrow();
                assertEquals("PENDING", rv.getStatus(), "철회 요청은 max-attempts 를 넘어도 포기하지 않는다");
                assertNotNull(rv.getPayloadJson());
                status.set(200);
                tx.executeWithoutResult(st -> outbox.findAll().forEach(x -> x.setNextAttemptAt(LocalDateTime.now().minusSeconds(1))));
                dispatcher.dispatchOnce();
                assertEquals("SENT", outbox.findById(rv.getId()).orElseThrow().getStatus());
        }

        @Test
        void missingSigningKeyDoesNotBurnAttemptsOrPayload() {
                grant(14L);
                collector.onApproved(candidate(14L, "SYN-ACK"));
                AiSigningKeys noKeys = new AiSigningKeys("", "", "", "pseudonym-secret-for-tests-0123456789", "");
                TrainingOutboxDispatcher d = new TrainingOutboxDispatcher(outbox, tx, WebClient.create("http://127.0.0.1:9"),
                                AiTrainingSettings.forTest(true, true), noKeys, consents, pseudonyms);
                for (int i = 0; i < 5; i++) {
                        tx.executeWithoutResult(st -> outbox.findAll().forEach(x -> x.setNextAttemptAt(LocalDateTime.now().minusSeconds(1))));
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
                dispatcher.apply(r, "RETRY:HTTP_503");
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

        static TrainingSampleV1 readSample(AiTrainingOutbox r) {
                try {
                        return ContractJson.STRICT.readValue(r.getPayloadJson(), TrainingSampleV1.class);
                } catch (Exception e) {
                        throw new IllegalStateException(e);
                }
        }
}
