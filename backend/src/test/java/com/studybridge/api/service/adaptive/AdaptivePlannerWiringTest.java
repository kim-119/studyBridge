package com.studybridge.api.service.adaptive;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.config.WebClientConfig;
import com.studybridge.api.controller.AdaptivePlannerController;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.service.PlannerService;
import com.studybridge.api.service.ScheduleRegistrationService;
import com.studybridge.api.service.recommendation.PlannerProgressReader;
import java.time.Duration;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 실제 Spring 컨테이너로 적응형 학습 엔진 빈 연결을 검증한다(생성자 선택·@Qualifier·@Value 기본값·WebClientConfig 전용 클라이언트).
 * 2026-10-28 운영 기동 실패(AdaptivePlannerClient 생성자 2개 + @Autowired 누락 → No default constructor) 재발 방지.
 */
class AdaptivePlannerWiringTest {

    @Test
    void adaptiveBeans_wireInRealContainer_withDefaults() {
        try (AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext()) {
            ctx.getEnvironment().getPropertySources().addFirst(new MapPropertySource("test", Map.of("ai.server.api-key", "k")));
            ctx.registerBean(WebClient.Builder.class, () -> WebClient.builder());
            ctx.registerBean(ObjectMapper.class, () -> new ObjectMapper());
            ctx.registerBean(PlatformTransactionManager.class, () -> mock(PlatformTransactionManager.class));
            ctx.registerBean(PlannerRepository.class, () -> mock(PlannerRepository.class));
            ctx.registerBean(ReviewNoteRepository.class, () -> mock(ReviewNoteRepository.class));
            ctx.registerBean(PlannerProgressReader.class, () -> mock(PlannerProgressReader.class));
            ctx.registerBean(ScheduleRegistrationService.class, () -> mock(ScheduleRegistrationService.class));
            ctx.registerBean(PlannerService.class, () -> mock(PlannerService.class));
            ctx.register(WebClientConfig.class, AdaptivePlannerClient.class, AdaptiveProposalSigner.class, AdaptivePlannerContextBuilder.class,
                    AdaptivePlannerService.class, AdaptivePlannerApplyService.class, AdaptivePlannerController.class);
            ctx.refresh();

            AdaptivePlannerClient client = ctx.getBean(AdaptivePlannerClient.class);
            assertEquals(Duration.ofSeconds(45), client.timeout(), "기본 응답 상한 45초");
            assertEquals(true, client.configured());
            assertEquals(Duration.ofMinutes(30), ctx.getBean(AdaptiveProposalSigner.class).ttl());
            assertEquals("Asia/Seoul", ctx.getBean(AdaptivePlannerService.class).zone().getId());
            assertNotNull(ctx.getBean("adaptivePlannerWebClient", WebClient.class));
            assertNotNull(ctx.getBean("visionWebClient", WebClient.class), "비전 전용 클라이언트 구성은 그대로");
            assertNotNull(ctx.getBean(AdaptivePlannerController.class));
        }
    }
}
