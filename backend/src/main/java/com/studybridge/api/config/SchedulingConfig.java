package com.studybridge.api.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

import java.time.Clock;

/**
 * 공부 세션 reaper(@Scheduled) 활성화 + 서버 시각 Clock 빈.
 * Clock 은 JVM 기본 시간대(컨테이너 TZ=Asia/Seoul)를 따르며, 테스트에서는 고정 Clock 으로 교체한다.
 */
@Configuration
@EnableScheduling
public class SchedulingConfig {

    @Bean
    public Clock clock() {
        return Clock.systemDefaultZone();
    }
}
