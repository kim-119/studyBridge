package com.studybridge.api.ai.contract.v1;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.junit.jupiter.api.Test;

/**
 * EC2 canonical fixture 검증(Java/Jackson 쪽). 기대값 = expectations.json 의 canonical.
 * 같은 파일을 ai07 Pydantic 으로 검증하는 쪽은 tools/crosscheck_pydantic.py(ai07 PR 체크아웃 필요) — 불일치는 openIssue 로 추적.
 */
class ContractV1FixturesTest {

        static final ObjectMapper PLAIN = new ObjectMapper();

        static byte[] resource(String path) throws Exception {
                try (InputStream in = ContractV1FixturesTest.class.getResourceAsStream("/ai-contracts/v1/" + path)) {
                        if (in == null) {
                                throw new IllegalStateException("missing fixture " + path);
                        }
                        return in.readAllBytes();
                }
        }

        static JsonNode expectations() throws Exception {
                return PLAIN.readTree(resource("expectations.json"));
        }

        /** strict 파싱 + 계약 검증. 파싱 실패(모르는 필드/타입 강제변환/형식)도 INVALID. */
        static String javaOutcome(String key, String model) {
                try {
                        byte[] body = resource(key);
                        ContractJson.Violations v;
                        if (key.startsWith("learning-context.v1/")) {
                                v = LearningContextV1.validate(ContractJson.STRICT.readValue(body, LearningContextV1.class));
                        } else if (key.startsWith("training-sample.v1/")) {
                                v = TrainingSampleV1.validate(ContractJson.STRICT.readValue(body, TrainingSampleV1.class));
                        } else if ("output".equals(model)) {
                                v = ResponseQualityV1.validate(ContractJson.STRICT.readValue(body, ResponseQualityV1.Output.class));
                        } else {
                                v = ResponseQualityV1.validate(ContractJson.STRICT.readValue(body, ResponseQualityV1.Input.class));
                        }
                        return v.ok() ? "VALID" : "INVALID";
                } catch (Exception e) {
                        return "INVALID";
                }
        }

        @Test
        void everyFixtureMatchesCanonicalExpectation() throws Exception {
                JsonNode fx = expectations().get("fixtures");
                List<String> wrong = new ArrayList<>();
                int n = 0;
                for (Iterator<Map.Entry<String, JsonNode>> it = fx.fields(); it.hasNext(); n++) {
                        Map.Entry<String, JsonNode> e = it.next();
                        String got = javaOutcome(e.getKey(), e.getValue().path("model").asText(null));
                        if (!got.equals(e.getValue().get("canonical").asText())) {
                                wrong.add(e.getKey() + " java=" + got);
                        }
                }
                assertEquals(30, n, "fixture 수가 바뀌면 expectations.json 을 함께 갱신해야 한다");
                assertTrue(wrong.isEmpty(), "canonical 불일치: " + wrong);
        }

        @Test
        void ai07MismatchesAreExplicitlyTrackedNotHidden() throws Exception {
                JsonNode fx = expectations().get("fixtures");
                Map<String, String> open = new TreeMap<>();
                fx.fields().forEachRemaining(e -> {
                        boolean differs = !e.getValue().get("canonical").asText().equals(e.getValue().get("ai07Observed").asText());
                        if (differs) {
                                assertTrue(e.getValue().hasNonNull("openIssue"), "추적 이슈 없는 불일치: " + e.getKey());
                                open.put(e.getKey(), e.getValue().get("openIssue").asText());
                        }
                });
                // ai07 이 맞추면 ai07Observed 를 갱신하고 이 목록에서 뺀다(계약 불일치 = FAIL 로 관리).
                assertEquals(Map.of(
                                "learning-context.v1/ec2_invalid_request_id_trailing_newline.json", "C-ID-1",
                                "learning-context.v1/ec2_invalid_string_material_id.json", "C-TYPE-1",
                                "response-quality.v1/ec2_invalid_output_score_above_100.json", "C-RQ-2",
                                "training-sample.v1/ec2_invalid_naive_datetime.json", "C-TIME-1"), open);
        }

        @Test
        void contentHashMatchesPythonVectorsAndFixtures() throws Exception {
                JsonNode hashes = expectations().get("contentHash");
                hashes.fields().forEachRemaining(e -> assertEquals(e.getValue().get("hash").asText(),
                                TrainingSampleV1.contentHash(e.getValue().get("question").asText(), e.getValue().get("answer").asText()),
                                e.getKey()));
                TrainingSampleV1 s = ContractJson.STRICT.readValue(resource("training-sample.v1/valid_pdf_qa_candidate.json"),
                                TrainingSampleV1.class);
                assertEquals(s.contentHash(), TrainingSampleV1.contentHash(s.question(), s.candidateAnswer()));
        }

        @Test
        void trustOverclaimIsCappedBySourceType() throws Exception {
                LearningContextV1 c = ContractJson.STRICT.readValue(resource("learning-context.v1/valid_pdf_and_history.json"),
                                LearningContextV1.class);
                LearningContextV1.ContextItem summary = c.contextItems().stream()
                                .filter(i -> i.kind() == LearningContextV1.Kind.SUMMARY).findFirst().orElseThrow();
                assertEquals(LearningContextV1.TrustLevel.SOURCE_PRIMARY, summary.trustLevel());
                assertEquals(LearningContextV1.TrustLevel.AI_GENERATED, summary.effectiveTrust());
                assertEquals(List.of("ctx-001"), c.contextItems().stream()
                                .filter(i -> i.effectiveTrust() == LearningContextV1.TrustLevel.SOURCE_PRIMARY).map(LearningContextV1.ContextItem::id).toList());
        }

        @Test
        void serializedJavaContextRoundTripsThroughStrictParser() throws Exception {
                LearningContextV1 c = ContractJson.STRICT.readValue(resource("learning-context.v1/valid_pdf_and_history.json"),
                                LearningContextV1.class);
                byte[] again = ContractJson.STRICT.writeValueAsBytes(c);
                LearningContextV1 back = ContractJson.STRICT.readValue(again, LearningContextV1.class);
                assertTrue(LearningContextV1.validate(back).ok(), new String(again, StandardCharsets.UTF_8));
                assertEquals(c, back);
                assertFalse(new String(again, StandardCharsets.UTF_8).contains("\"userId\""));
        }
}
