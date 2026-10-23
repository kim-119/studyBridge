package com.studybridge.api.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * application.yml `password-reset.*` 바인딩. 모든 값은 환경변수로 재정의 가능(하드코딩 금지).
 */
@Getter
@Setter
@Component
@ConfigurationProperties(prefix = "password-reset")
public class PasswordResetProperties {
    /** 발신자 주소(SMTP_FROM). 비우면 spring.mail.username 사용. */
    private String from = "";
    private String fromName = "StudyBridge";
    private long codeTtlSeconds = 300;
    private long verifiedTtlSeconds = 600;
    private long resendCooldownSeconds = 60;
    private int maxVerifyAttempts = 5;
    private long ipWindowSeconds = 600;
    private int ipMaxRequests = 10;
}
