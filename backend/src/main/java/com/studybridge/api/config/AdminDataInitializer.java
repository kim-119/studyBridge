package com.studybridge.api.config;

import com.studybridge.api.entity.Admin;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class AdminDataInitializer implements CommandLineRunner {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    @Value("${admin.default.email}")
    private String defaultAdminEmail;

    @Value("${admin.default.password}")
    private String defaultAdminPassword;

    @Override
    public void run(String... args) {
        // 최초 관리자 계정이 이미 존재하는지 확인
        if (userRepository.existsByAdmin(Admin.ADMIN)) {
            log.info("관리자 계정이 이미 존재하므로, 초기화 과정을 건너뜁니다.");
            return;
        }

        log.info("최초 관리자 계정을 생성합니다...");

        User admin = User.builder()
                .email(defaultAdminEmail)
                .password(passwordEncoder.encode(defaultAdminPassword))
                .displayName("최고관리자")
                .major("시스템관리")
                .admin(Admin.ADMIN)
                .status("ACTIVE")
                .build();

        userRepository.save(admin);

        log.info("최초 관리자 계정이 성공적으로 생성되었습니다. (ID: {})", defaultAdminEmail);
        log.warn("주의: 운영 환경(Production)에서는 반드시 기본 비밀번호를 변경하거나 환경변수(ADMIN_DEFAULT_PASSWORD)를 통해 주입받아야 합니다.");
    }
}