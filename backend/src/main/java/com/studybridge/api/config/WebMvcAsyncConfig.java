package com.studybridge.api.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.web.servlet.config.annotation.AsyncSupportConfigurer;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Spring MVC 비동기(Flux/SSE 컨트롤러) 실행기.
 *
 * <p>학습메이트 SSE 컨트롤러({@code ChatController#chatStream})가 {@code Flux<ServerSentEvent>} 를 반환하면
 * MVC 는 비동기 요청 처리로 전환하는데, 기본 실행기가 {@code SimpleAsyncTaskExecutor}(요청마다 새 스레드, 상한 없음)라
 * 기동 로그에 "!!! not suitable for production use under load" 경고가 남고 동시 스트림 수만큼 스레드가 무제한 생성됐다.
 * 상한이 있는 풀로 교체한다(스트림 자체는 reactor 스레드에서 흐르므로 이 풀은 dispatch 용도).</p>
 */
@Configuration
public class WebMvcAsyncConfig implements WebMvcConfigurer {

    @Bean(name = "mvcAsyncTaskExecutor")
    public ThreadPoolTaskExecutor mvcAsyncTaskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setThreadNamePrefix("mvc-async-");
        executor.setCorePoolSize(8);
        executor.setMaxPoolSize(64);
        executor.setQueueCapacity(200);
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }

    @Override
    public void configureAsyncSupport(AsyncSupportConfigurer configurer) {
        configurer.setTaskExecutor(mvcAsyncTaskExecutor());
    }
}
