package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

/** 사용자별 평가 한도(Phase D6): 버스트 후 429 + Retry-After, 시간 경과 보충, 사용자 간 격리, 게이트 OFF·비GATED 경로 미적용. */
class AiQualityUserRateLimiterTest {

        @AfterEach
        void clear() {
                SecurityContextHolder.clearContext();
        }

        @Test
        void burstThenRefillPerUser() {
                AtomicLong now = new AtomicLong(0);
                AiQualityUserRateLimiter l = new AiQualityUserRateLimiter(6, 2, now::get); // 분당 6 = 10초에 1개
                assertEquals(0, l.tryAcquire("u:1"));
                assertEquals(0, l.tryAcquire("u:1"));
                long wait = l.tryAcquire("u:1");
                assertTrue(wait >= 1 && wait <= 10, "버스트 소진 → 대기 " + wait);
                assertEquals(0, l.tryAcquire("u:2"), "다른 사용자는 영향 없음");
                now.addAndGet(10_000_000_000L);
                assertEquals(0, l.tryAcquire("u:1"), "10초 후 1개 보충");
        }

        static MockHttpServletRequest req(String method, String path, String pattern) {
                MockHttpServletRequest r = new MockHttpServletRequest(method, path);
                r.setAttribute(org.springframework.web.servlet.HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, pattern);
                return r;
        }

        @Test
        void interceptorReturns429OnlyForGatedRoutesWhenGateOn() throws Exception {
                SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken("77", "x", java.util.List.of()));
                AiQualityGateCoverage on = new AiQualityGateCoverage(AiQualityGateSettings.forTest(true));
                on.setRateLimiter(new AiQualityUserRateLimiter(1, 1, () -> 0L));
                String gated = "/api/materials/{materialId}/summary";
                assertTrue(on.preHandle(req("GET", "/api/materials/5/summary", gated), new MockHttpServletResponse(), null));
                MockHttpServletResponse limited = new MockHttpServletResponse();
                assertEquals(false, on.preHandle(req("GET", "/api/materials/5/summary", gated), limited, null));
                assertEquals(429, limited.getStatus());
                assertTrue(Long.parseLong(limited.getHeader("Retry-After")) >= 1);
                assertTrue(limited.getContentAsString().contains("AI_QUALITY_RATE_LIMITED"));
                assertTrue(on.preHandle(req("GET", "/api/timers", "/api/timers"), new MockHttpServletResponse(), null), "비AI 경로 미적용");
                for (int i = 0; i < 5; i++) {
                        assertTrue(on.preHandle(req("GET", "/api/review-notes", "/api/review-notes"), new MockHttpServletResponse(), null),
                                        "저장본 조회만 하는 GATED GET 은 평가를 일으키지 않아 한도 대상 아님");
                }

                AiQualityGateCoverage off = new AiQualityGateCoverage(AiQualityGateSettings.forTest(false));
                off.setRateLimiter(new AiQualityUserRateLimiter(1, 1, () -> 0L));
                for (int i = 0; i < 5; i++) {
                        assertTrue(off.preHandle(req("GET", "/api/materials/5/summary", gated), new MockHttpServletResponse(), null), "게이트 OFF 미적용");
                }
        }
}
