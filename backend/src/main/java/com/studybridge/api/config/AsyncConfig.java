package com.studybridge.api.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * @Async 활성화 설정.
 *
 * PdfExtractionService.sendToFastApiForExtraction 는 @Async 로 선언되어 있으나,
 * 그동안 @EnableAsync 가 어디에도 없어 동기 실행되고 있었다. 그 결과 자료 업로드 요청 스레드가
 * ai07 추출/Vision OCR 응답(최대 read-timeout 180s)까지 블로킹되어 프론트가 "저장 중..." 에서
 * 수 분간 멈췄다. 이를 켜서 추출은 백그라운드 스레드에서 돌고 업로드는 즉시 반환되도록 한다.
 */
@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean(name = "taskExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(50);
        executor.setThreadNamePrefix("doc-extract-");
        executor.initialize();
        return executor;
    }
}
