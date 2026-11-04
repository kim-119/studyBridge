package com.studybridge.api.ai.contract.v1;

import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * 사용자 PK → ai07 로 보내는 가명 키(pseudonymousUserKey / 토큰 sub).
 *  · "pk_" + base64url(HMAC-SHA256(AI_PSEUDONYM_SECRET, "studybridge:user:v1:" + userId))[0..32) → 35자, 계약 정규식
 *    ^[A-Za-z0-9_\-]{16,128}$ 충족, 숫자만으로 이뤄질 수 없음.
 *  · 서버 비밀 키 기반이라 사용자가 바꾸거나 추측할 수 없고, ai07 쪽에서 PK 로 되돌릴 수 없다. 같은 사용자 → 항상 같은 키
 *    (철회·삭제 추적의 결합 키). 비밀 키를 바꾸면 모든 가명이 바뀌므로 회전 시 ai07 lineage 재매핑이 필요하다(인계).
 *  · 신원은 항상 Spring Security principal 의 userId 에서만 파생한다(클라이언트 헤더/본문의 userId·actorId 무시).
 */
@Component
public class PseudonymousUserKeys {

    private static final String DOMAIN = "studybridge:user:v1:";
    private final AiSigningKeys keys;

    public PseudonymousUserKeys(AiSigningKeys keys) {
        this.keys = keys;
    }

    public String of(long userId) {
        byte[] mac = AiContractSigning.hmac(keys.key(AiSigningKeys.Purpose.PSEUDONYM),
                (DOMAIN + userId).getBytes(StandardCharsets.UTF_8));
        return "pk_" + Base64.getUrlEncoder().withoutPadding().encodeToString(mac).substring(0, 32);
    }
}
