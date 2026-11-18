package com.studybridge.api.service.adaptive;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.util.Base64;
import java.util.List;
import java.util.Objects;

/**
 * 일정 제안 토큰. 추천 응답에서 Spring 이 확정한 반영 후보(changes)를 사용자·플래너·DB 상태(basisToken)와 함께 HMAC 으로 묶는다.
 *
 * <ul>
 *   <li>반영 API 는 토큰 안의 후보만 받는다 — 화면이 날짜·분·대상을 바꿔 보내도 저장되지 않는다.</li>
 *   <li>상태 없음(서버 저장소 불필요). 키는 ai.planner.adaptive.proposal-secret, 비어 있으면 기동마다 무작위(재기동 후 토큰 만료).</li>
 *   <li>유효 시간 proposal-ttl-minutes(기본 30분). 만료·변조·다른 사용자/플래너 토큰은 거절한다.</li>
 * </ul>
 */
@Component
public class AdaptiveProposalSigner {

    /** 반영 후보 1건. kind = ADD_STUDY_SESSION(주간 일정에 학습 세션 추가) | RESCHEDULE_PLANNER(수기 플래너 예정일 변경). */
    public record Change(String id, String kind, Long plannerId, String date, Integer minutes,
                         String fromDate, String toDate, String source, List<Object> taskIds) {}

    public record Payload(int v, Long userId, Long plannerId, String mode, Long currentStepId, String basis,
                          long issuedAt, List<Change> changes) {}

    private static final int VERSION = 1;

    private final byte[] key;
    private final Duration ttl;
    private final ObjectMapper objectMapper;
    private final Clock clock;

    @Autowired
    public AdaptiveProposalSigner(@Value("${ai.planner.adaptive.proposal-secret:}") String secret,
                                  @Value("${ai.planner.adaptive.proposal-ttl-minutes:30}") long ttlMinutes,
                                  ObjectMapper objectMapper) {
        this(secret, Duration.ofMinutes(Math.max(1, ttlMinutes)), objectMapper, Clock.systemUTC());
    }

    AdaptiveProposalSigner(String secret, Duration ttl, ObjectMapper objectMapper, Clock clock) {
        this.key = deriveKey(secret);
        this.ttl = ttl;
        this.objectMapper = objectMapper;
        this.clock = clock;
    }

    public Duration ttl() {
        return ttl;
    }

    public String sign(Long userId, Long plannerId, String mode, Long currentStepId, String basis, List<Change> changes) {
        Payload p = new Payload(VERSION, userId, plannerId, mode, currentStepId, basis, clock.instant().getEpochSecond(), changes);
        try {
            String body = Base64.getUrlEncoder().withoutPadding().encodeToString(objectMapper.writeValueAsBytes(p));
            return body + "." + mac(body);
        } catch (Exception e) {
            throw new IllegalStateException("proposal token 생성 실패", e);
        }
    }

    /** 서명·버전·소유자·플래너·만료 검증. 실패 시 400(변조/형식) 또는 409(만료). */
    public Payload verify(String token, Long userId, Long plannerId) {
        if (token == null || token.isBlank() || token.length() > 16_384) throw invalid();
        int dot = token.lastIndexOf('.');
        if (dot <= 0 || dot == token.length() - 1) throw invalid();
        String body = token.substring(0, dot);
        String sig = token.substring(dot + 1);
        if (!MessageDigest.isEqual(mac(body).getBytes(StandardCharsets.US_ASCII), sig.getBytes(StandardCharsets.US_ASCII))) throw invalid();
        Payload p;
        try {
            p = objectMapper.readValue(Base64.getUrlDecoder().decode(body), Payload.class);
        } catch (Exception e) {
            throw invalid();
        }
        if (p.v() != VERSION || !Objects.equals(p.userId(), userId) || !Objects.equals(p.plannerId(), plannerId)) throw invalid();
        long age = clock.instant().getEpochSecond() - p.issuedAt();
        if (age < -60 || age > ttl.toSeconds()) {
            throw new AdaptivePlannerException(HttpStatus.CONFLICT, "ADAPTIVE_PROPOSAL_EXPIRED",
                    "일정 제안이 만료되었습니다. 추천을 다시 받은 뒤 반영해 주세요.");
        }
        return p;
    }

    private static AdaptivePlannerException invalid() {
        return new AdaptivePlannerException(HttpStatus.BAD_REQUEST, "ADAPTIVE_PROPOSAL_INVALID",
                "일정 제안 정보가 올바르지 않습니다. 추천을 다시 받은 뒤 반영해 주세요.");
    }

    private String mac(String body) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return Base64.getUrlEncoder().withoutPadding().encodeToString(mac.doFinal(body.getBytes(StandardCharsets.US_ASCII)));
        } catch (Exception e) {
            throw new IllegalStateException("HMAC 실패", e);
        }
    }

    private static byte[] deriveKey(String secret) {
        if (secret == null || secret.isBlank()) {
            byte[] k = new byte[32];
            new SecureRandom().nextBytes(k);
            return k;
        }
        try {
            return MessageDigest.getInstance("SHA-256").digest(("adaptive-proposal:" + secret.trim()).getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
