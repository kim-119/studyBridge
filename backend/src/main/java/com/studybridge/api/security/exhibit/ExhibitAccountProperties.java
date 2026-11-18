package com.studybridge.api.security.exhibit;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

/**
 * application.yml `exhibit.*` 바인딩 — 전시 방문객용 체험 계정(test1~test4).
 *
 * <p>체험 계정의 로그인 ID 는 별칭(test1)이고, DB 의 email 은 {@code 별칭@emailDomain} 이다
 * (Android 앱 로그인 입력이 type=email 이라 이메일 형식으로도 로그인할 수 있어야 한다).
 * 동시 접속 제한·세션 슬롯은 여기 나열된 계정에만 적용되고 일반 사용자 인증 경로는 바뀌지 않는다.</p>
 */
@Getter
@Setter
@Component
@ConfigurationProperties(prefix = "exhibit")
public class ExhibitAccountProperties {
    /** 체험 계정 별칭 목록. 비우면 체험 계정 정책 전체가 꺼진다(일반 계정과 동일하게 취급). */
    private List<String> accounts = new ArrayList<>(List.of("test1", "test2", "test3", "test4"));
    private String emailDomain = "studybridge.co.kr";
    /** 기동 시 없는 체험 계정만 생성(있으면 변경하지 않는다). */
    private boolean provisionOnStartup = true;
    /** 최초 생성 시 비밀번호(전시용). 회원가입 비밀번호 정책(8~16자)은 그대로 둔다. */
    private String initialPassword = "1234";
    private int maxSessionsPerAccount = 2;
    /** 요청이 이 시간 동안 없으면 세션 슬롯을 반환한다(브라우저 종료·앱 강제 종료 등 비정상 종료). */
    private long sessionIdleMinutes = 30;
    /** 로그인 후 이 시간이 지나면 재로그인이 필요하다(리프레시로 연장되지 않는 절대 수명). */
    private long sessionMaxHours = 12;

    public String emailFor(String alias) {
        return alias.trim().toLowerCase(Locale.ROOT) + "@" + emailDomain.trim().toLowerCase(Locale.ROOT);
    }

    public List<String> canonicalEmails() {
        return accounts.stream().filter(a -> a != null && !a.isBlank()).map(this::emailFor).toList();
    }

    public boolean isExhibitEmail(String email) {
        if (email == null) return false;
        return canonicalEmails().contains(email);
    }

    /**
     * 로그인 입력을 체험 계정 email 로 해석한다. 별칭(test1)이나 체험 계정 email(대소문자·앞뒤 공백 무시)이면 그 email,
     * 아니면 empty — 일반 사용자 입력은 손대지 않는다.
     */
    public Optional<String> resolveLoginId(String input) {
        if (input == null) return Optional.empty();
        String normalized = input.trim().toLowerCase(Locale.ROOT);
        for (String alias : accounts) {
            if (alias == null || alias.isBlank()) continue;
            String email = emailFor(alias);
            if (normalized.equals(alias.trim().toLowerCase(Locale.ROOT)) || normalized.equals(email)) {
                return Optional.of(email);
            }
        }
        return Optional.empty();
    }

    public String aliasOf(String email) {
        int at = email == null ? -1 : email.indexOf('@');
        return at > 0 ? email.substring(0, at) : email;
    }
}
