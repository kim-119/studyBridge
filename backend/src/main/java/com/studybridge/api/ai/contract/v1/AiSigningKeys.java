package com.studybridge.api.ai.contract.v1;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 용도별 서명 키(환경변수만, 코드·로그에 값 금지). ai07 {@code signing._key()} 와 같은 규칙으로 fail-closed:
 *  · 32바이트 미만 → SIGNING_KEY_NOT_CONFIGURED
 *  · 다른 용도 키나 내부 Bearer(AI_SERVER_API_KEY)와 같으면 → SIGNING_KEY_REUSED (한 키 유출이 다른 용도 위조로 번지지 않게)
 * AI_PSEUDONYM_SECRET 은 EC2 전용(ai07 로 보내지 않음) — 사용자 PK → 가명 키 파생에만 쓴다.
 * 키 회전: ai07 이 {현재, 이전} 두 키를 일정 기간 함께 검증하도록 먼저 배포한 뒤 EC2 값을 교체한다(인계 문서 참고).
 */
@Component
public class AiSigningKeys {

    public static final int MIN_KEY_BYTES = 32;

    public enum Purpose {
        SCOPE("AI_SCOPE_SIGNING_KEY"),
        TRAINING_CONSENT("AI_TRAINING_CONSENT_SIGNING_KEY"),
        TRAINING_SAMPLE("AI_TRAINING_SAMPLE_SIGNING_KEY"),
        PSEUDONYM("AI_PSEUDONYM_SECRET");

        public final String env;

        Purpose(String env) {
            this.env = env;
        }
    }

    private final Map<Purpose, String> keys = new LinkedHashMap<>();
    private final String internalBearer;

    public AiSigningKeys(@Value("${ai.contract.scope-signing-key:${AI_SCOPE_SIGNING_KEY:}}") String scope,
                         @Value("${ai.contract.training-consent-signing-key:${AI_TRAINING_CONSENT_SIGNING_KEY:}}") String consent,
                         @Value("${ai.contract.training-sample-signing-key:${AI_TRAINING_SAMPLE_SIGNING_KEY:}}") String sample,
                         @Value("${ai.contract.pseudonym-secret:${AI_PSEUDONYM_SECRET:}}") String pseudonym,
                         @Value("${ai.server.api-key:}") String internalBearer) {
        keys.put(Purpose.SCOPE, trim(scope));
        keys.put(Purpose.TRAINING_CONSENT, trim(consent));
        keys.put(Purpose.TRAINING_SAMPLE, trim(sample));
        keys.put(Purpose.PSEUDONYM, trim(pseudonym));
        this.internalBearer = trim(internalBearer);
    }

    /** 키 바이트. 미구성/재사용이면 AiContractException(호출자는 자료를 보내지 않고 기능을 거부해야 한다). */
    public byte[] key(Purpose purpose) {
        String k = keys.get(purpose);
        if (k.getBytes(StandardCharsets.UTF_8).length < MIN_KEY_BYTES) {
            throw new AiContractException("SIGNING_KEY_NOT_CONFIGURED", purpose.env);
        }
        for (Map.Entry<Purpose, String> e : keys.entrySet()) {
            if (e.getKey() != purpose && !e.getValue().isEmpty() && same(e.getValue(), k)) {
                throw new AiContractException("SIGNING_KEY_REUSED", purpose.env);
            }
        }
        if (!internalBearer.isEmpty() && same(internalBearer, k)) {
            throw new AiContractException("SIGNING_KEY_REUSED", purpose.env);
        }
        return k.getBytes(StandardCharsets.UTF_8);
    }

    public boolean configured(Purpose purpose) {
        try {
            key(purpose);
            return true;
        } catch (AiContractException e) {
            return false;
        }
    }

    private static boolean same(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    private static String trim(String v) {
        return v == null ? "" : v.strip();
    }
}
