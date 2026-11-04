package com.studybridge.api.ai.contract.v1;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.junit.jupiter.api.Test;

/**
 * 교차 언어 서명 벡터(signing-vectors.v1, ai07 Python/OpenSSL/JVM 4/4 산출)를 Spring 구현으로 회귀 고정한다.
 *  · 본문 서명은 원시 바이트 그대로 — 재직렬화된 본문(한글 \\u 이스케이프)은 SIGNATURE_INVALID.
 *  · Java 발급 토큰이 Python 발급 토큰과 문자 단위로 같다(CanonicalJson = json.dumps(sort_keys, compact, ensure_ascii)).
 *  · scope 토큰을 consent 로 쓰면 CONSENT_TOKEN_TYPE_INVALID(C-SIG-1 — ai07 d7346fc6 에서 벡터 기대값도 같게 갱신, 오버라이드 없음).
 */
class AiContractSigningVectorsTest {

        static final ObjectMapper M = new ObjectMapper();

        static JsonNode vectors() throws Exception {
                return M.readTree(ContractV1FixturesTest.resource("signing-vectors.v1.json"));
        }

        static byte[] key(JsonNode v, String env) {
                return v.get("keys").get(env).asText().getBytes(StandardCharsets.UTF_8);
        }

        static String outcome(Runnable r) {
                try {
                        r.run();
                        return "VALID";
                } catch (AiContractException e) {
                        return e.code();
                }
        }

        @Test
        void bodySignatureVectors() throws Exception {
                JsonNode v = vectors();
                byte[] k = key(v, "AI_TRAINING_SAMPLE_SIGNING_KEY");
                List<String> wrong = new ArrayList<>();
                for (JsonNode c : v.get("bodySignature")) {
                        byte[] body = Base64.getDecoder().decode(c.get("bodyBase64").asText());
                        String got = outcome(() -> AiContractSigning.verifyBody(k, body, c.get("signature").asText(),
                                        c.get("timestamp").asText(), c.get("verifyAt").asLong()));
                        if (!got.equals(c.get("expect").asText())) {
                                wrong.add(c.get("name").asText() + " got=" + got);
                        }
                        if ("VALID".equals(c.get("expect").asText())) {
                                assertEquals(c.get("signature").asText(), AiContractSigning.signBody(k, c.get("timestamp").asLong(), body));
                        }
                }
                assertEquals(List.of(), wrong);
        }

        @Test
        void scopeTokenVectors() throws Exception {
                JsonNode v = vectors();
                byte[] k = key(v, "AI_SCOPE_SIGNING_KEY");
                for (JsonNode c : v.get("scopeToken")) {
                        String got = outcome(() -> AiContractSigning.verifyScopeToken(k, c.get("token").asText(),
                                        c.get("requestId").asText(), null, c.get("verifyAt").asLong()));
                        assertEquals(c.get("expect").asText(), got, c.get("name").asText());
                }
        }

        @Test
        void consentTokenVectorsMatchWithoutOverride() throws Exception {
                JsonNode v = vectors();
                byte[] k = key(v, "AI_TRAINING_CONSENT_SIGNING_KEY");
                for (JsonNode c : v.get("consentToken")) {
                        String name = c.get("name").asText();
                        String got = outcome(() -> AiContractSigning.verifyConsentToken(k, c.get("token").asText(),
                                        c.get("requestId").asText(), null, c.get("verifyAt").asLong()));
                        assertEquals(c.get("expect").asText(), got, name);
                }
        }

        @Test
        void javaIssuedTokensAreByteIdenticalToPythonVectors() throws Exception {
                JsonNode v = vectors();
                JsonNode sp = v.get("scopeToken").get(0).get("payload");
                List<Long> mids = new ArrayList<>();
                sp.get("materialIds").forEach(n -> mids.add(n.asLong()));
                String scope = AiContractSigning.issueScopeToken(key(v, "AI_SCOPE_SIGNING_KEY"), sp.get("sub").asText(), mids,
                                List.of(), sp.get("rid").asText(), sp.get("iat").asLong(),
                                (int) (sp.get("exp").asLong() - sp.get("iat").asLong()));
                assertEquals(v.get("scopeToken").get(0).get("token").asText(), scope);

                JsonNode cp = v.get("consentToken").get(0).get("payload");
                Map<String, String> rights = new TreeMap<>();
                cp.get("rights").fields().forEachRemaining(e -> rights.put(e.getKey(), e.getValue().asText()));
                List<String> sc = new ArrayList<>();
                cp.get("scope").forEach(n -> sc.add(n.asText()));
                String consent = AiContractSigning.issueConsentToken(key(v, "AI_TRAINING_CONSENT_SIGNING_KEY"), cp.get("sub").asText(),
                                cp.get("cv").asText(), cp.get("ct").asText(), sc, rights, cp.get("dtid").asText(), cp.get("rid").asText(),
                                cp.get("iat").asLong(), (int) (cp.get("exp").asLong() - cp.get("iat").asLong()));
                assertEquals(v.get("consentToken").get(0).get("token").asText(), consent);
        }

        @Test
        void tsvRawHmacVectors() throws Exception {
                JsonNode v = vectors();
                String tsv = new String(ContractV1FixturesTest.resource("signing-vectors.v1.tsv"), StandardCharsets.UTF_8);
                int ok = 0;
                for (String line : tsv.split("\n")) {
                        if (line.isBlank()) {
                                continue;
                        }
                        String[] f = line.split("\t");
                        byte[] raw = AiContractSigning.hmac(key(v, f[1]), Base64.getDecoder().decode(f[2]));
                        String got = f[0].equals("HEX") ? HexFormat.of().formatHex(raw)
                                        : Base64.getUrlEncoder().withoutPadding().encodeToString(raw);
                        assertEquals(f[3], got, line);
                        ok++;
                }
                assertEquals(4, ok);
        }

        @Test
        void tokenBoundToSubjectAndRequestAndPurpose() throws Exception {
                byte[] k = "scope-key-for-unit-test-0123456789abcdef".getBytes(StandardCharsets.UTF_8);
                String t = AiContractSigning.issueScopeToken(k, "pk_unit_user_000001", List.of(42L, 7L, 42L), List.of("doc-a1"),
                                "req-unit-000001", 1_793_750_400L, 120);
                AiContractSigning.ScopeClaims c = AiContractSigning.verifyScopeToken(k, t, "req-unit-000001", "pk_unit_user_000001",
                                1_793_750_410L);
                assertEquals(java.util.Set.of(7L, 42L), c.materialIds());
                assertEquals("SCOPE_SUBJECT_MISMATCH", outcome(() -> AiContractSigning.verifyScopeToken(k, t, "req-unit-000001",
                                "pk_someone_else_0001", 1_793_750_410L)));
                assertEquals("SCOPE_REQUEST_MISMATCH", outcome(() -> AiContractSigning.verifyScopeToken(k, t, null, null, 1_793_750_410L)));
                assertEquals("SCOPE_TOKEN_EXPIRED", outcome(() -> AiContractSigning.verifyScopeToken(k, t, "req-unit-000001", null,
                                1_793_750_521L)));
                byte[] other = "another-key-for-unit-test-0123456789abcd".getBytes(StandardCharsets.UTF_8);
                assertEquals("SCOPE_TOKEN_INVALID", outcome(() -> AiContractSigning.verifyScopeToken(other, t, "req-unit-000001", null,
                                1_793_750_410L)));
                assertThrows(IllegalArgumentException.class, () -> AiContractSigning.issueScopeToken(k, "pk_unit_user_000001",
                                List.of(), List.of(), "req-unit-000001", 0, 601));
                assertEquals("SIGNING_KEY_NOT_CONFIGURED", outcome(() -> AiContractSigning.verifyScopeToken(new byte[8], t,
                                "req-unit-000001", null, 1_793_750_410L)));
        }

        @Test
        void signingKeysFailClosedOnMissingOrReusedKeys() {
                String a = "a".repeat(40);
                AiSigningKeys missing = new AiSigningKeys("", "", "", "", "");
                assertEquals("SIGNING_KEY_NOT_CONFIGURED", outcome(() -> missing.key(AiSigningKeys.Purpose.SCOPE)));
                AiSigningKeys reused = new AiSigningKeys(a, a, "b".repeat(40), "c".repeat(40), "");
                assertEquals("SIGNING_KEY_REUSED", outcome(() -> reused.key(AiSigningKeys.Purpose.SCOPE)));
                AiSigningKeys bearerReuse = new AiSigningKeys(a, "d".repeat(40), "b".repeat(40), "c".repeat(40), a);
                assertEquals("SIGNING_KEY_REUSED", outcome(() -> bearerReuse.key(AiSigningKeys.Purpose.SCOPE)));
                AiSigningKeys ok = new AiSigningKeys(a, "d".repeat(40), "b".repeat(40), "c".repeat(40), "e".repeat(64));
                assertEquals(40, ok.key(AiSigningKeys.Purpose.SCOPE).length);
                PseudonymousUserKeys pk = new PseudonymousUserKeys(ok);
                String k1 = pk.of(55L);
                assertEquals(k1, pk.of(55L));
                assertEquals(35, k1.length());
                assertEquals(true, ContractJson.pseudonymous(k1));
                assertEquals(false, k1.equals(pk.of(56L)));
        }
}
