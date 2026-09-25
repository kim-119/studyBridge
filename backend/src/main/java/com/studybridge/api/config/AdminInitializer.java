package com.studybridge.api.config;

import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class AdminInitializer implements CommandLineRunner {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    @Override
    public void run(String... args) throws Exception {
        String adminEmail = "admin@studybridge.com";

        // 시스템 기동 시 어드민 계정 존재 여부 검사
        if (!userRepository.existsByEmail(adminEmail)) {
            log.info("[어드민 초기화] 시스템 내 관리자 계정이 존재하지 않아 기본 계정을 초기 생성합니다.");

            User admin = User.builder()
                    .email(adminEmail)
                    .password(passwordEncoder.encode("admin1234")) // 기본 비밀번호
                    .displayName("시스템 관리자")
                    .major("SYSTEM")
                    .status("ACTIVE")
                    .role("ADMIN")
                    .isSubscribed(true) // 관리자는 구독 상태 활성화
                    .build();

            userRepository.save(admin);
            log.info("[어드민 초기화 완료] 이메일: {}, 비밀번호: admin1234", adminEmail);
        } else {
            log.info("[어드민 초기화] 관리자 계정이 이미 데이터베이스에 존재합니다.");
        }
    }
}
