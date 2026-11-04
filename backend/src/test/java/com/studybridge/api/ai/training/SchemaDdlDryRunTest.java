package com.studybridge.api.ai.training;

import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * 운영 스키마 변경 dry-run 도구(기본 비활성). 운영 RDS 에 접속하지 않는다.
 *  1) 일회용 PG 에 운영 스키마 스냅샷(pg_dump --schema-only)을 올린다.
 *  2) 이 테스트를 SB_DDL_DRYRUN_URL(그 DB) + SB_DDL_DRYRUN_OUT(출력 파일)로 실행 → Hibernate 가 ddl-auto=update 로
 *     실제 실행할 DDL 을 DB 에 적용하지 않고 스크립트로만 남긴다(hbm2ddl.auto=none, scripts.action=update).
 *  3) 출력에서 이번 PR 의 테이블/컬럼만 골라 승인 요청서(db/migration/V20261104_2__*.sql)와 대조한다.
 */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@EnabledIfEnvironmentVariable(named = "SB_DDL_DRYRUN_URL", matches = "jdbc:postgresql://(127\\.0\\.0\\.1|localhost):.*")
class SchemaDdlDryRunTest {

        @DynamicPropertySource
        static void pg(DynamicPropertyRegistry r) {
                r.add("spring.datasource.url", () -> System.getenv("SB_DDL_DRYRUN_URL"));
                r.add("spring.datasource.username", () -> System.getenv().getOrDefault("SB_TEST_PG_USER", "sbtest"));
                r.add("spring.datasource.password", () -> System.getenv().getOrDefault("SB_TEST_PG_PASSWORD", "sbtest"));
                r.add("spring.jpa.hibernate.ddl-auto", () -> "none");
                r.add("spring.jpa.properties.jakarta.persistence.schema-generation.scripts.action", () -> "update");
                r.add("spring.jpa.properties.jakarta.persistence.schema-generation.scripts.create-target",
                                () -> System.getenv("SB_DDL_DRYRUN_OUT"));
                r.add("spring.jpa.properties.hibernate.hbm2ddl.delimiter", () -> ";");
                r.add("spring.jpa.properties.hibernate.default_schema", () -> "public");
        }

        @Test
        void exportsUpdateScriptWithoutApplyingIt() {
                assertTrue(java.nio.file.Files.exists(java.nio.file.Path.of(System.getenv("SB_DDL_DRYRUN_OUT"))), "update 스크립트 생성");
        }
}
