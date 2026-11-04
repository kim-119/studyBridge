package com.studybridge.api.ai.contract.v1;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.Collection;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * EC2↔ai07 서명 계약 v1 (canonical owner = EC2). ai07 {@code app/contracts/signing.py} 와 바이트 단위 호환.
 *
 * <pre>
 * 1) 본문 서명  X-AI-Contract-Signature = "v1=" + hex(HMAC-SHA256(key, ascii(timestamp) + "." + RAW_BODY_BYTES))
 *               X-AI-Contract-Timestamp = unix seconds(10진 숫자, 최대 12자리), 허용 오차 ±300s.
 *               RAW_BODY_BYTES = 실제로 전송하는 바이트 그대로. 검증자는 JSON 을 재직렬화하지 않는다.
 * 2) scope 토큰 X-AI-Scope = b64url(payload).b64url(HMAC(scopeKey, b64url(payload)))
 *               payload = {v:1, typ:"ai-scope", sub, materialIds[int, 정렬], documentIds[str, 정렬], iat, exp, rid}
 * 3) consent    X-AI-Training-Consent = 같은 형식, typ:"training-consent", {sub, cv, ct, scope[], rights{}, dtid, rid, iat, exp}
 * 토큰 수명 ≤ 600s, iat 는 now+30s 를 넘을 수 없다. 모든 비교는 상수 시간(MessageDigest.isEqual).
 * 용도별 키 3개는 서로·내부 Bearer 키와 달라야 한다(AiSigningKeys 가 강제).
 * </pre>
 */
public final class AiContractSigning {

    public static final int MAX_SKEW_SECONDS = 300;
    public static final int MAX_TOKEN_TTL_SECONDS = 600;
    public static final int FUTURE_IAT_TOLERANCE_SECONDS = 30;
    public static final String SCOPE_TYP = "ai-scope";
    public static final String CONSENT_TYP = "training-consent";
    public static final String HEADER_SIGNATURE = "X-AI-Contract-Signature";
    public static final String HEADER_TIMESTAMP = "X-AI-Contract-Timestamp";
    public static final String HEADER_SCOPE = "X-AI-Scope";
    public static final String HEADER_CONSENT = "X-AI-Training-Consent";

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Base64.Encoder B64URL = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder B64URL_DEC = Base64.getUrlDecoder();

    private AiContractSigning() {
    }

    // ── 1) 본문 서명 ────────────────────────────────────────────────────────────────
    public static String signBody(byte[] key, long timestamp, byte[] rawBody) {
        return "v1=" + HexFormat.of().formatHex(hmac(key, concat((timestamp + ".").getBytes(StandardCharsets.US_ASCII), rawBody)));
    }

    public static void verifyBody(byte[] key, byte[] rawBody, String signature, String timestamp, long nowEpochSeconds) {
        requireKey(key);
        if (signature == null || signature.isBlank() || timestamp == null || timestamp.isBlank()) {
            throw new AiContractException("SIGNATURE_MISSING");
        }
        String ts = timestamp.strip();
        if (ts.length() > 12 || !ts.chars().allMatch(ch -> ch >= '0' && ch <= '9')) {
            throw new AiContractException("SIGNATURE_TIMESTAMP_INVALID");
        }
        long t = Long.parseLong(ts);
        if (Math.abs(nowEpochSeconds - t) > MAX_SKEW_SECONDS) {
            throw new AiContractException("SIGNATURE_EXPIRED");
        }
        String expected = signBody(key, t, rawBody);
        if (!constantTimeEquals(expected, signature.strip())) {
            throw new AiContractException("SIGNATURE_INVALID");
        }
    }

    // ── 2) scope 토큰 ───────────────────────────────────────────────────────────────
    public record ScopeClaims(String sub, Set<Long> materialIds, Set<String> documentIds, long iat, long exp, String rid) {
        public boolean allowsMaterial(Long materialId) {
            return materialId != null && materialIds.contains(materialId);
        }

        public boolean allowsDocument(String documentId) {
            return documentId != null && documentIds.contains(documentId);
        }
    }

    public static String issueScopeToken(byte[] key, String sub, Collection<Long> materialIds, Collection<String> documentIds,
                                         String requestId, long iat, int ttlSeconds) {
        requireKey(key);
        requireTtl(ttlSeconds);
        Map<String, Object> p = new TreeMap<>();
        p.put("v", 1);
        p.put("typ", SCOPE_TYP);
        p.put("sub", sub);
        p.put("materialIds", materialIds.stream().map(Long::longValue).distinct().sorted().toList());
        p.put("documentIds", documentIds.stream().map(String::valueOf).distinct().sorted().toList());
        p.put("iat", iat);
        p.put("exp", iat + ttlSeconds);
        p.put("rid", requestId);
        return token(key, p);
    }

    public static ScopeClaims verifyScopeToken(byte[] key, String token, String expectedRequestId, String expectedSub,
                                               long nowEpochSeconds) {
        JsonNode p = verifyTokenSignature(key, token, "SCOPE");
        long[] times = times(p, "SCOPE");
        if (!SCOPE_TYP.equals(text(p, "typ"))) {
            throw new AiContractException("SCOPE_TOKEN_TYPE_INVALID");
        }
        if (p.path("v").asInt(-1) != 1 || !p.path("v").isInt() || !timesValid(times, nowEpochSeconds)) {
            throw new AiContractException("SCOPE_TOKEN_EXPIRED");
        }
        if (expectedSub != null && !expectedSub.equals(text(p, "sub"))) {
            throw new AiContractException("SCOPE_SUBJECT_MISMATCH");
        }
        String rid = text(p, "rid");
        if (expectedRequestId == null || rid == null || !constantTimeEquals(rid, expectedRequestId)) {
            throw new AiContractException("SCOPE_REQUEST_MISMATCH");
        }
        Set<Long> mids = new LinkedHashSet<>();
        for (JsonNode n : p.path("materialIds")) {
            if (!n.canConvertToLong() || !n.isIntegralNumber()) {
                throw new AiContractException("SCOPE_TOKEN_MALFORMED");
            }
            mids.add(n.asLong());
        }
        Set<String> dids = new LinkedHashSet<>();
        for (JsonNode n : p.path("documentIds")) {
            dids.add(n.asText());
        }
        return new ScopeClaims(text(p, "sub"), Set.copyOf(mids), Set.copyOf(dids), times[0], times[1], rid);
    }

    // ── 3) 학습 동의 claim ─────────────────────────────────────────────────────────
    public record ConsentClaims(String sub, String consentVersion, String consentTimestamp, Set<String> scope,
                                Map<String, String> rights, String deletionTrackingId, String rid, long iat, long exp) { }

    public static String issueConsentToken(byte[] key, String sub, String consentVersion, String consentTimestamp,
                                           Collection<String> scope, Map<String, String> rights, String deletionTrackingId,
                                           String requestId, long iat, int ttlSeconds) {
        requireKey(key);
        requireTtl(ttlSeconds);
        Map<String, Object> p = new TreeMap<>();
        p.put("v", 1);
        p.put("typ", CONSENT_TYP);
        p.put("sub", sub);
        p.put("cv", consentVersion);
        p.put("ct", consentTimestamp);
        p.put("scope", scope.stream().distinct().sorted().toList());
        p.put("rights", new TreeMap<>(rights));
        p.put("dtid", deletionTrackingId);
        p.put("rid", requestId);
        p.put("iat", iat);
        p.put("exp", iat + ttlSeconds);
        return token(key, p);
    }

    /**
     * EC2 canonical: typ 불일치는 CONSENT_TOKEN_TYPE_INVALID(ai07 PROPOSED 구현은 CONSENT_TOKEN_EXPIRED 로 합쳐 보고 — 둘 다 거부,
     * 코드만 다름. 인계 항목 C-SIG-1).
     */
    public static ConsentClaims verifyConsentToken(byte[] key, String token, String expectedRequestId, String expectedSub,
                                                   long nowEpochSeconds) {
        JsonNode p = verifyTokenSignature(key, token, "CONSENT");
        long[] times = times(p, "CONSENT");
        if (!CONSENT_TYP.equals(text(p, "typ"))) {
            throw new AiContractException("CONSENT_TOKEN_TYPE_INVALID");
        }
        if (p.path("v").asInt(-1) != 1 || !p.path("v").isInt() || !timesValid(times, nowEpochSeconds)) {
            throw new AiContractException("CONSENT_TOKEN_EXPIRED");
        }
        String rid = text(p, "rid");
        if (rid == null || rid.isBlank()) {
            throw new AiContractException("CONSENT_REQUEST_MISSING");
        }
        if (expectedRequestId != null && !constantTimeEquals(rid, expectedRequestId)) {
            throw new AiContractException("CONSENT_REQUEST_MISMATCH");
        }
        if (expectedSub != null && !expectedSub.equals(text(p, "sub"))) {
            throw new AiContractException("CONSENT_SUBJECT_MISMATCH");
        }
        Set<String> scope = new LinkedHashSet<>();
        p.path("scope").forEach(n -> scope.add(n.asText()));
        Map<String, String> rights = new LinkedHashMap<>();
        p.path("rights").fields().forEachRemaining(e -> rights.put(e.getKey(), e.getValue().asText()));
        return new ConsentClaims(text(p, "sub"), text(p, "cv"), text(p, "ct"), Set.copyOf(scope), Map.copyOf(rights),
                text(p, "dtid"), rid, times[0], times[1]);
    }

    // ── 공통 ────────────────────────────────────────────────────────────────────────
    private static String token(byte[] key, Map<String, Object> payload) {
        String p = B64URL.encodeToString(CanonicalJson.write(payload).getBytes(StandardCharsets.UTF_8));
        return p + "." + B64URL.encodeToString(hmac(key, p.getBytes(StandardCharsets.US_ASCII)));
    }

    private static JsonNode verifyTokenSignature(byte[] key, String token, String kind) {
        requireKey(key);
        if (token == null || token.chars().filter(ch -> ch == '.').count() != 1) {
            throw new AiContractException(kind + "_TOKEN_MISSING");
        }
        int dot = token.indexOf('.');
        String p = token.substring(0, dot);
        String sig = token.substring(dot + 1);
        String expected = B64URL.encodeToString(hmac(key, p.getBytes(StandardCharsets.US_ASCII)));
        if (!constantTimeEquals(expected, sig)) {
            throw new AiContractException(kind + "_TOKEN_INVALID");
        }
        try {
            JsonNode n = MAPPER.readTree(B64URL_DEC.decode(p));
            if (n == null || !n.isObject()) {
                throw new AiContractException(kind + "_TOKEN_MALFORMED");
            }
            return n;
        } catch (AiContractException e) {
            throw e;
        } catch (Exception e) {
            throw new AiContractException(kind + "_TOKEN_MALFORMED");
        }
    }

    private static long[] times(JsonNode p, String kind) {
        JsonNode iat = p.get("iat");
        JsonNode exp = p.get("exp");
        // Python: isinstance(int) and not bool — 정수가 아니면(문자열/실수/불리언) MALFORMED
        if (iat == null || exp == null || !iat.isIntegralNumber() || !exp.isIntegralNumber()) {
            throw new AiContractException(kind + "_TOKEN_MALFORMED");
        }
        return new long[]{iat.asLong(), exp.asLong()};
    }

    private static boolean timesValid(long[] t, long now) {
        long iat = t[0];
        long exp = t[1];
        return exp >= now && iat <= now + FUTURE_IAT_TOLERANCE_SECONDS && iat <= exp && exp - iat <= MAX_TOKEN_TTL_SECONDS;
    }

    private static String text(JsonNode p, String field) {
        JsonNode n = p.get(field);
        return n == null || n.isNull() ? null : n.asText();
    }

    private static void requireKey(byte[] key) {
        if (key == null || key.length < AiSigningKeys.MIN_KEY_BYTES) {
            throw new AiContractException("SIGNING_KEY_NOT_CONFIGURED");
        }
    }

    private static void requireTtl(int ttl) {
        if (ttl <= 0 || ttl > MAX_TOKEN_TTL_SECONDS) {
            throw new IllegalArgumentException("ttl must be 1.." + MAX_TOKEN_TTL_SECONDS);
        }
    }

    static byte[] hmac(byte[] key, byte[] data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException("HmacSHA256 unavailable", e);
        }
    }

    public static boolean constantTimeEquals(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = new byte[a.length + b.length];
        System.arraycopy(a, 0, out, 0, a.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }
}
