package com.studybridge.api.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.studybridge.api.dto.InquiryDTO;
import com.studybridge.api.entity.Inquiry;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.InquiryRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 실제 PostgreSQL 에서 장애 재현: inquiries.type 은 NOT NULL(운영 RDS 와 같은 제약). type 없는 INSERT 는 DataIntegrityViolation(수정 전 500),
 * 컨트롤러 경로(Android 페이로드)는 기본 유형으로 저장되고 GET 목록·관리자 목록에 나타난다. 일회용 DB 전용(SB_TEST_PG_URL).
 */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@EnabledIfEnvironmentVariable(named = "SB_TEST_PG_URL", matches = "jdbc:postgresql://(127\\.0\\.0\\.1|localhost):.*")
class InquiryPostgresTest {

        @DynamicPropertySource
        static void pg(DynamicPropertyRegistry r) {
                r.add("spring.datasource.url", () -> System.getenv("SB_TEST_PG_URL"));
                r.add("spring.datasource.username", () -> System.getenv().getOrDefault("SB_TEST_PG_USER", "sbtest"));
                r.add("spring.datasource.password", () -> System.getenv().getOrDefault("SB_TEST_PG_PASSWORD", "sbtest"));
                r.add("spring.jpa.hibernate.ddl-auto", () -> "create-drop");
        }

        @Autowired
        InquiryRepository inquiries;
        @Autowired
        UserRepository users;
        @Autowired
        org.springframework.transaction.PlatformTransactionManager txm;

        /** 운영 요청은 OSIV(기본 true)로 지연 로딩 세션이 열려 있다 — 테스트에서는 요청 하나를 트랜잭션으로 감싸 같은 조건을 만든다. */
        <T> T inRequest(java.util.function.Supplier<T> s) {
                return new org.springframework.transaction.support.TransactionTemplate(txm).execute(st -> s.get());
        }

        User user() {
                User u = new User();
                u.setEmail("inquiry-it-" + System.nanoTime() + "@studybridge.test");
                u.setDisplayName("문의테스트");
                u.setPassword("x");
                u.setIsSubscribed(false);
                u.setStatus("ACTIVE");
                u.setRole("USER");
                return users.saveAndFlush(u);
        }

        @Test
        void nullTypeViolatesNotNullLikeProductionAndControllerPathPersists() {
                User u = user();
                Inquiry broken = Inquiry.builder().title("ㅈㄱㄴ").content("내용").author(u).status("대기중").build();
                assertThrows(DataIntegrityViolationException.class, () -> inquiries.saveAndFlush(broken), "수정 전 동작 재현: type NULL → NOT NULL 위반");

                CustomUserDetails principal = mock(CustomUserDetails.class);
                when(principal.getId()).thenReturn(u.getId());
                InquiryController c = new InquiryController(inquiries, users);
                InquiryDTO.Response created = inRequest(() -> c.createInquiry(principal, new InquiryDTO.Request(null, "앱 문의", "알림 문제")).getBody());
                assertEquals("이용문의", created.getType());
                inRequest(() -> c.createInquiry(principal, new InquiryDTO.Request(null, "앱 문의", "알림 문제"))); // 연속 클릭
                List<InquiryDTO.Response> mine = inRequest(() -> c.getMyInquiries(principal).getBody());
                assertEquals(1, mine.size(), "연속 클릭은 1건");
                assertEquals("앱 문의", mine.get(0).getTitle());
                assertEquals(1L, (long) inRequest(() -> inquiries.findAllByOrderByCreatedAtDesc().stream().filter(i -> i.getAuthor().getId().equals(u.getId())).count()),
                                "관리자 목록과 같은 저장소 기준 정합");
        }
}
