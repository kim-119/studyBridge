package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.LearningSourceType;
import com.studybridge.api.repository.LearningLoopEventRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.domain.PageRequest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 학습 루프 이벤트 기록의 트랜잭션 경계(실제 PostgreSQL 필요 — read-only 트랜잭션 INSERT 거부는 PG 가 강제한다).
 *
 * 재현 대상(수정 전 LearningLoopService):
 *  - recordSafe() 가 같은 클래스의 record() 를 직접 호출 → @Transactional(REQUIRES_NEW) 프록시 미적용.
 *    recordSafe 자체는 클래스 기본 @Transactional(readOnly=true) 라서, 호출자 트랜잭션이 없으면 READ ONLY 트랜잭션에서
 *    INSERT 가 실행돼 실패하고 예외가 삼켜져 이벤트가 조용히 유실된다.
 *  - 호출자 트랜잭션이 있으면 그 트랜잭션에 합류 → 이벤트 INSERT 실패가 호출자 트랜잭션을 rollback-only/aborted 로 만들어
 *    본기능(요약 저장·오답노트 생성)이 UnexpectedRollbackException 으로 실패한다.
 *
 * 일회용 DB 로만 실행한다(운영 RDS 금지):
 *   docker run --rm -d -p 127.0.0.1:55432:5432 -e POSTGRES_USER=sbtest -e POSTGRES_PASSWORD=sbtest -e POSTGRES_DB=sbtest postgres:16
 *   SB_TEST_PG_URL=jdbc:postgresql://127.0.0.1:55432/sbtest SB_TEST_PG_USER=sbtest SB_TEST_PG_PASSWORD=sbtest ./gradlew test
 */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import({LearningLoopService.class, LearningLoopEventWriter.class})
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@EnabledIfEnvironmentVariable(named = "SB_TEST_PG_URL", matches = "jdbc:postgresql://(127\\.0\\.0\\.1|localhost):.*")
class LearningLoopRecordPostgresTest {

        @DynamicPropertySource
        static void pg(DynamicPropertyRegistry r) {
                r.add("spring.datasource.url", () -> System.getenv("SB_TEST_PG_URL"));
                r.add("spring.datasource.username", () -> System.getenv().getOrDefault("SB_TEST_PG_USER", "sbtest"));
                r.add("spring.datasource.password", () -> System.getenv().getOrDefault("SB_TEST_PG_PASSWORD", "sbtest"));
                r.add("spring.jpa.hibernate.ddl-auto", () -> "create-drop");
        }

        @Autowired
        LearningLoopService service;
        @Autowired
        LearningLoopEventRepository repository;
        @Autowired
        PlatformTransactionManager txManager;

        TransactionTemplate tx;

        @BeforeEach
        void setUp() {
                tx = new TransactionTemplate(txManager);
                repository.deleteAllInBatch();
        }

        private static LearningLoopEvent event(long userId, String action) {
                return LearningLoopEvent.builder()
                                .userId(userId)
                                .eventType(LearningEventType.MATERIAL_SUMMARY_GENERATED)
                                .sourceType(LearningSourceType.MATERIAL)
                                .sourceId(7L)
                                .materialId(7L)
                                .aiOutputSummary("요약")
                                .userAction(action)
                                .build();
        }

        private long countFor(long userId) {
                return repository.findByUserIdOrderByCreatedAtDesc(userId, PageRequest.of(0, 50)).size();
        }

        @Test
        void recordSafeWithoutCallerTransactionPersists() {
                Long id = service.recordSafe(event(101L, "SUMMARY_GENERATED"));
                assertNotNull(id, "호출자 트랜잭션이 없어도 이벤트는 독립(read-write) 트랜잭션으로 저장돼야 한다");
                assertEquals(1, countFor(101L));
        }

        @Test
        void failingEventDoesNotPoisonCallerTransaction() {
                String tooLong = "X".repeat(150); // user_action varchar(100) 초과 → PG 오류
                assertDoesNotThrow(() -> tx.executeWithoutResult(s -> {
                        repository.save(event(202L, "MAIN_FEATURE_ROW")); // 본기능 쓰기(대역)
                        service.recordSafe(event(202L, tooLong));          // 실패하는 부가 기록
                }), "부가 이벤트 기록 실패가 호출자 커밋을 실패시키면 안 된다");
                assertEquals(1, countFor(202L), "본기능 행은 커밋돼야 하고 실패한 이벤트는 없어야 한다");
        }

        @Test
        void eventInsideRolledBackCallerIsNotPersisted() {
                tx.executeWithoutResult(s -> {
                        service.recordSafe(event(303L, "SUMMARY_GENERATED"));
                        s.setRollbackOnly(); // 본기능 실패 → 롤백
                });
                assertEquals(0, countFor(303L), "본기능이 롤백되면 그 결과를 주장하는 이벤트도 남지 않는다(유령 이벤트 금지)");
        }

        @Test
        void eventInsideCommittedCallerIsPersistedAfterCommit() {
                Long idInside = tx.execute(s -> service.recordSafe(event(404L, "SUMMARY_GENERATED")));
                assertNull(idInside, "호출자 트랜잭션 안에서는 커밋 후로 미뤄지므로 즉시 id 가 없다");
                assertEquals(1, countFor(404L), "호출자 커밋 직후 독립 트랜잭션으로 저장돼야 한다");
        }

        @Test
        void recordStrictPropagatesValidationErrors() {
                LearningLoopEvent bad = LearningLoopEvent.builder().eventType(LearningEventType.QUIZ_SUBMITTED).build();
                org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> service.record(bad));
        }

        @Test
        void recordSafeCalledFromAnotherAfterCommitCallbackIsNotDropped() {
                tx.executeWithoutResult(s -> org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
                                new org.springframework.transaction.support.TransactionSynchronization() {
                                        @Override
                                        public void afterCommit() {
                                                service.recordSafe(event(505L, "NESTED_AFTER_COMMIT"));
                                        }
                                }));
                assertEquals(1, countFor(505L), "다른 afterCommit 콜백 안에서 호출돼도 유실되지 않는다");
        }
}
