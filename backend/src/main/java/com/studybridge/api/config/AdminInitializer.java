package com.studybridge.api.config;

import com.studybridge.api.entity.AdminRole;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
@RequiredArgsConstructor
@Slf4j
public class AdminInitializer implements ApplicationRunner {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    @Value("${root.default.email:root@studybridge.com}")
    private String defaultEmail;

    @Value("${root.default.password:root1234!}")
    private String defaultPassword;

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        if (!userRepository.existsByEmail(defaultEmail)) {
            User admin = User.builder()
                    .email(defaultEmail)
                    .password(passwordEncoder.encode(defaultPassword))
                    .displayName("Admin")
                    .major("Administration")
                    .role(AdminRole.ADMIN)
                    .build();

            userRepository.save(admin);
            log.info("Default admin account created: {}", defaultEmail);
        } else {
            log.info("Admin account already exists: {}", defaultEmail);
        }
    }
}
