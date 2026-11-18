package com.studybridge.api.service.adaptive;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.adaptive.AdaptiveProposalSigner.Change;
import com.studybridge.api.service.adaptive.AdaptiveProposalSigner.Payload;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.List;
import org.junit.jupiter.api.Test;

/** 일정 제안 토큰: 왕복·변조·다른 키·만료. */
class AdaptiveProposalSignerTest {

    private final ObjectMapper om = new ObjectMapper();
    private final Clock t0 = Clock.fixed(Instant.parse("2026-10-28T03:00:00Z"), ZoneOffset.UTC);
    private final List<Change> changes = List.of(
            new Change("S:22:2026-10-29", "ADD_STUDY_SESSION", 22L, "2026-10-29", 20, null, null, "PARTIAL_PLAN", List.of(31L, "c1")));

    @Test
    void roundTrip_preservesChanges() {
        AdaptiveProposalSigner s = new AdaptiveProposalSigner("k", Duration.ofMinutes(30), om, t0);
        Payload p = s.verify(s.sign(55L, 21L, "MANUAL_NEXT", null, "abc", changes), 55L, 21L);
        assertEquals("abc", p.basis());
        assertEquals("S:22:2026-10-29", p.changes().get(0).id());
        assertEquals(20, p.changes().get(0).minutes());
    }

    @Test
    void forgedPayload_withValidLookingSignature_isRejected() {
        AdaptiveProposalSigner s = new AdaptiveProposalSigner("k", Duration.ofMinutes(30), om, t0);
        String token = s.sign(55L, 21L, "MANUAL_NEXT", null, "abc", changes);
        String sig = token.substring(token.lastIndexOf('.') + 1);
        String forgedBody = Base64.getUrlEncoder().withoutPadding().encodeToString(
                new String(Base64.getUrlDecoder().decode(token.substring(0, token.lastIndexOf('.')))).replace("\"minutes\":20", "\"minutes\":240").getBytes());
        assertEquals("ADAPTIVE_PROPOSAL_INVALID", assertThrows(AdaptivePlannerException.class,
                () -> s.verify(forgedBody + "." + sig, 55L, 21L)).getCode());
    }

    @Test
    void tokenFromAnotherKey_isRejected() {
        String token = new AdaptiveProposalSigner("other", Duration.ofMinutes(30), om, t0).sign(55L, 21L, "MANUAL_NEXT", null, "abc", changes);
        AdaptiveProposalSigner s = new AdaptiveProposalSigner("k", Duration.ofMinutes(30), om, t0);
        assertThrows(AdaptivePlannerException.class, () -> s.verify(token, 55L, 21L));
        assertThrows(AdaptivePlannerException.class, () -> s.verify("garbage", 55L, 21L));
        assertThrows(AdaptivePlannerException.class, () -> s.verify(null, 55L, 21L));
    }

    @Test
    void expiredAfterTtl_is409() {
        String token = new AdaptiveProposalSigner("k", Duration.ofMinutes(30), om, t0).sign(55L, 21L, "MANUAL_NEXT", null, "abc", changes);
        AdaptiveProposalSigner later = new AdaptiveProposalSigner("k", Duration.ofMinutes(30), om,
                Clock.offset(t0, Duration.ofMinutes(31)));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> later.verify(token, 55L, 21L));
        assertEquals("ADAPTIVE_PROPOSAL_EXPIRED", e.getCode());
    }

    @Test
    void randomKeyWhenSecretBlank_tokensDoNotSurviveRestart() {
        String token = new AdaptiveProposalSigner("", Duration.ofMinutes(30), om, t0).sign(55L, 21L, "MANUAL_NEXT", null, "abc", changes);
        assertThrows(AdaptivePlannerException.class,
                () -> new AdaptiveProposalSigner("", Duration.ofMinutes(30), om, t0).verify(token, 55L, 21L));
    }
}
