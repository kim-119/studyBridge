package com.studybridge.api.config;

import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.exhibit.ExhibitAccountProperties;
import com.studybridge.api.service.UserService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * 전시 방문객용 체험 계정(exhibit.accounts) 생성 — 기동 시 1회, 멱등.
 *
 * <ul>
 *   <li>없는 계정만 회원가입과 같은 {@link UserService#createUser} 로 만든다(PasswordEncoder 해시, 일반 USER 권한).</li>
 *   <li>같은 email 이 이미 있으면 비밀번호·상태·권한을 포함해 아무것도 바꾸지 않고 로그로 보고한다
 *       (전시 종료 후 정지한 계정을 재기동이 되살리지 않는다).</li>
 *   <li>실패해도 기동은 계속한다(다른 서비스에 영향 없음).</li>
 * </ul>
 * 끄기: {@code EXHIBIT_PROVISION_ON_STARTUP=false}.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ExhibitAccountInitializer implements CommandLineRunner {

    private final ExhibitAccountProperties properties;
    private final UserRepository userRepository;
    private final UserService userService;

    @Override
    public void run(String... args) {
        if (!properties.isProvisionOnStartup()) {
            log.info("[EXHIBIT] provision-on-startup=false → 체험 계정 생성 건너뜀");
            return;
        }
        List<String> created = new ArrayList<>();
        List<String> existing = new ArrayList<>();
        List<String> failed = new ArrayList<>();
        for (String alias : properties.getAccounts()) {
            if (alias == null || alias.isBlank()) continue;
            String email = properties.emailFor(alias);
            try {
                Optional<User> found = userRepository.findByEmail(email);
                if (found.isPresent()) {
                    log.info("[EXHIBIT] account exists, unchanged email={} userId={} role={} status={}",
                            email, found.get().getId(), found.get().getRole(), found.get().getStatus());
                    existing.add(email);
                    continue;
                }
                User user = userService.createUser(email, properties.getInitialPassword(), properties.aliasOf(email), null);
                log.info("[EXHIBIT] account created email={} userId={} role={}", email, user.getId(), user.getRole());
                created.add(email);
            } catch (DataIntegrityViolationException e) {
                // 동시에 뜬 다른 인스턴스가 먼저 만들었다(email unique) → 이미 있음과 같다.
                log.info("[EXHIBIT] account created concurrently elsewhere, unchanged email={}", email);
                existing.add(email);
            } catch (Exception e) {
                log.error("[EXHIBIT] account provision failed email={} ({}: {})", email, e.getClass().getSimpleName(), e.getMessage());
                failed.add(email);
            }
        }
        log.info("[EXHIBIT] provision summary created={} existing={} failed={} maxSessionsPerAccount={} idleMinutes={} maxHours={}",
                created, existing, failed, properties.getMaxSessionsPerAccount(), properties.getSessionIdleMinutes(),
                properties.getSessionMaxHours());
    }
}
