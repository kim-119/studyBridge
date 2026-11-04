package com.studybridge.api.ai.contract.v1;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * ai07 ↔ EC2 교차 언어 차등(differential) 하네스 — EC2 canonical Java 계약 클래스를 그대로 호출해
 * 같은 원시 입력에 대한 Java 판정을 JSONL 로 출력한다. (ai07 저장소에 두지만 EC2 소스를 git ref 에서 꺼내 컴파일한다.)
 *
 * 입력(stdin, 한 줄 = 한 케이스): {"id":..., "model":"lc|ts|rqi|rqo|sig-body|sig-scope|sig-consent", ...}
 *   계약: "raw"(원문 JSON 텍스트) 또는 "rawBase64"(바이트), rqo 는 선택 "expectedRequestId"
 *   서명: sig-body {key, bodyBase64, signature, timestamp, now} / sig-scope·sig-consent {key, token, requestId, sub, now}
 * 출력(stdout): {"id":..., "verdict":"VALID|INVALID", "violations":[...], "error":"...", "displayable":bool} / {"id", "outcome"}
 * 판정 규칙은 ContractV1FixturesTest.javaOutcome 과 동일: STRICT 파싱 실패 또는 validate 위반 → INVALID.
 */
public final class ContractDiffHarness {
    private static final ObjectMapper PLAIN = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = in.readLine()) != null) {
            if (line.isBlank()) {
                continue;
            }
            JsonNode c = PLAIN.readTree(line);
            ObjectNode out = PLAIN.createObjectNode();
            out.put("id", c.get("id").asText());
            String model = c.get("model").asText();
            if (model.startsWith("sig-")) {
                out.put("outcome", signing(model, c));
            } else {
                contract(model, c, out);
            }
            System.out.println(PLAIN.writeValueAsString(out));
        }
    }

    static byte[] body(JsonNode c) {
        if (c.hasNonNull("rawBase64")) {
            return Base64.getDecoder().decode(c.get("rawBase64").asText());
        }
        return c.get("raw").asText().getBytes(StandardCharsets.UTF_8);
    }

    static void contract(String model, JsonNode c, ObjectNode out) {
        try {
            byte[] b = body(c);
            ContractJson.Violations v;
            switch (model) {
                case "lc" -> v = LearningContextV1.validate(ContractJson.STRICT.readValue(b, LearningContextV1.class));
                case "ts" -> v = TrainingSampleV1.validate(ContractJson.STRICT.readValue(b, TrainingSampleV1.class));
                case "rqi" -> v = ResponseQualityV1.validate(ContractJson.STRICT.readValue(b, ResponseQualityV1.Input.class));
                case "rqo" -> {
                    ResponseQualityV1.Output o = ContractJson.STRICT.readValue(b, ResponseQualityV1.Output.class);
                    v = ResponseQualityV1.validate(o);
                    String rid = c.hasNonNull("expectedRequestId") ? c.get("expectedRequestId").asText() : null;
                    out.put("displayable", ResponseQualityV1.isDisplayable(o, rid));
                }
                default -> throw new IllegalArgumentException("model " + model);
            }
            out.put("verdict", v.ok() ? "VALID" : "INVALID");
            v.list().forEach(out.putArray("violations")::add);
        } catch (Exception e) {
            out.put("verdict", "INVALID");
            out.put("error", "parse:" + e.getClass().getSimpleName());
            if (!out.has("displayable") && "rqo".equals(model)) {
                out.put("displayable", false);
            }
        }
    }

    static String signing(String model, JsonNode c) {
        byte[] key = c.get("key").asText().getBytes(StandardCharsets.UTF_8);
        long now = c.get("now").asLong();
        String rid = c.hasNonNull("requestId") ? c.get("requestId").asText() : null;
        String sub = c.hasNonNull("sub") ? c.get("sub").asText() : null;
        try {
            switch (model) {
                case "sig-body" -> AiContractSigning.verifyBody(key, Base64.getDecoder().decode(c.get("bodyBase64").asText()),
                        c.hasNonNull("signature") ? c.get("signature").asText() : null,
                        c.hasNonNull("timestamp") ? c.get("timestamp").asText() : null, now);
                case "sig-scope" -> AiContractSigning.verifyScopeToken(key, c.hasNonNull("token") ? c.get("token").asText() : null,
                        rid, sub, now);
                case "sig-consent" -> AiContractSigning.verifyConsentToken(key, c.hasNonNull("token") ? c.get("token").asText() : null,
                        rid, sub, now);
                default -> throw new IllegalArgumentException("model " + model);
            }
            return "VALID";
        } catch (AiContractException e) {
            return e.code();
        } catch (Exception e) {
            return "JAVA_EXCEPTION:" + e.getClass().getSimpleName();
        }
    }
}
