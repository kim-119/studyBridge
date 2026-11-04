package com.studybridge.api.ai.contract.v1;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.Output;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.QualityStatus;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.TaskType;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * Phase C 계약 경계(ai07 차등 605건에서 Java 만 받던 7건 + isDisplayable 방어선):
 *  · C-TIME-2 연도 0001..9999(적힌 오프셋 기준), epoch 는 UTC 연도.
 *  · C-JSON-1 중복 키 거부(최상위·중첩).
 *  · C-JSON-2 고립 서러게이트 거부(값 위치), 정상 서러게이트 쌍(이모지)은 허용.
 *  · isDisplayable 은 계약 위반 출력(필수 필드 누락 등)을 APPROVED 라도 노출하지 않는다.
 */
class ContractStrictParsingTest {

        static String sampleJson() throws Exception {
                try (var in = ContractStrictParsingTest.class.getResourceAsStream("/ai-contracts/v1/training-sample.v1/valid_pdf_qa_candidate.json")) {
                        return new String(in.readAllBytes(), StandardCharsets.UTF_8);
                }
        }

        static String withCreatedAt(String raw) throws Exception {
                ObjectNode n = (ObjectNode) ContractJson.STRICT.readTree(sampleJson());
                n.put("createdAt", raw);
                return ContractJson.STRICT.writeValueAsString(n);
        }

        static boolean parses(String json) {
                try {
                        TrainingSampleV1 s = ContractJson.STRICT.readValue(json, TrainingSampleV1.class);
                        return TrainingSampleV1.validate(s).ok();
                } catch (Exception e) {
                        return false;
                }
        }

        @Test
        void yearBoundsFollowWrittenOffsetLikePython() throws Exception {
                assertTrue(parses(sampleJson()), "기준 fixture 는 유효");
                assertFalse(parses(withCreatedAt("0000-12-31T00:00:00Z")), "연도 0000 거부");
                assertFalse(parses(withCreatedAt("+12026-01-01T00:00:00Z")), "5자리 연도 거부");
                assertTrue(parses(withCreatedAt("0001-01-01T00:00:00+09:00")), "적힌 연도 0001(UTC 로는 0000) — Python 과 같이 허용");
                assertTrue(parses(withCreatedAt("9999-12-31T23:00:00-05:00")), "적힌 연도 9999(UTC 로는 10000) — 허용");
                ObjectNode n = (ObjectNode) ContractJson.STRICT.readTree(sampleJson());
                n.put("createdAt", 253402300800L); // 10000-01-01T00:00:00Z
                assertFalse(parses(ContractJson.STRICT.writeValueAsString(n)), "epoch 연도 10000 거부");
                n.put("createdAt", 253402300799L);
                assertTrue(parses(ContractJson.STRICT.writeValueAsString(n)), "epoch 9999-12-31T23:59:59Z 허용");
        }

        @Test
        void offsetIsPreservedButInstantIsUnchanged() throws Exception {
                TrainingSampleV1 s = ContractJson.STRICT.readValue(withCreatedAt("2026-11-04T12:00:00+09:00"), TrainingSampleV1.class);
                assertEquals(ZoneOffset.ofHours(9), s.createdAt().getOffset());
                assertTrue(s.createdAt().isEqual(OffsetDateTime.parse("2026-11-04T03:00:00Z")), "같은 순간");
        }

        @Test
        void duplicateKeysAreRejectedAtAnyDepth() throws Exception {
                String base = sampleJson();
                String top = base.replaceFirst("\\{", "{\"modelName\":\"a\",");
                assertThrows(Exception.class, () -> ContractJson.STRICT.readValue(top, TrainingSampleV1.class));
                JsonNode n = ContractJson.STRICT.readTree(base);
                assertTrue(n.has("trainingEligibility"));
                String nested = base.replaceFirst("\"trainingEligibility\"\\s*:\\s*\\{", "\"trainingEligibility\":{\"consentGranted\":true,");
                assertThrows(Exception.class, () -> ContractJson.STRICT.readValue(nested, TrainingSampleV1.class));
                assertThrows(Exception.class, () -> ContractJson.STRICT.readTree("{\"a\":1,\"a\":1}"), "readTree 도 중복 키 거부");
        }

        @Test
        void loneSurrogatesRejectedPairsAccepted() throws Exception {
                ObjectNode n = (ObjectNode) ContractJson.STRICT.readTree(sampleJson());
                n.put("question", "질문 😀");
                n.put("contentHash", TrainingSampleV1.contentHash("질문 😀", n.get("candidateAnswer").asText()));
                assertTrue(parses(ContractJson.STRICT.writeValueAsString(n)), "정상 서러게이트 쌍 허용");
                String lone = ContractJson.STRICT.writeValueAsString(n).replace("😀", "\\ud800");
                assertFalse(parses(lone), "고립 high surrogate 거부");
                String lowOnly = ContractJson.STRICT.writeValueAsString(n).replace("😀", "\\udc00x");
                assertFalse(parses(lowOnly), "고립 low surrogate 거부");
                assertTrue(ContractJson.hasLoneSurrogate("a\ud800"));
                assertFalse(ContractJson.hasLoneSurrogate("a😀b"));
        }

        @Test
        void constructionPathAlsoRejectsLoneSurrogateText() throws Exception {
                TrainingSampleV1 s = ContractJson.STRICT.readValue(sampleJson(), TrainingSampleV1.class);
                TrainingSampleV1 bad = new TrainingSampleV1(s.schemaVersion(), s.eventId(), s.pseudonymousUserKey(), s.consentVersion(),
                                s.consentTimestamp(), s.sourceKind(), s.sourceRevisionHash(), s.rightsStatus(), "q\ud800", s.candidateAnswer(),
                                s.verifiedAnswer(), s.verification(), s.evidence(), s.feedback(), s.qualityLabel(), s.qualityEvaluatorVersion(),
                                s.modelName(), s.modelDigest(), s.promptTemplateVersion(), s.contentHash(), s.createdAt(), s.deletionTrackingId(),
                                s.retentionPolicy(), s.trainingEligibility());
                assertTrue(TrainingSampleV1.validate(bad).list().contains("text:lone_surrogate"));
        }

        @Test
        void isDisplayableRevalidatesContract() {
                Output ok = new Output("response-quality.v1", "req-strict-0001", TaskType.PDF_SUMMARY, true, true, QualityStatus.APPROVED,
                                90.0, 80, false, List.of(), List.of(), null, "rqg-1.0.0", null, 3, true);
                assertTrue(ResponseQualityV1.isDisplayable(ok, "req-strict-0001"));
                Output noEvaluator = new Output("response-quality.v1", "req-strict-0001", TaskType.PDF_SUMMARY, true, true,
                                QualityStatus.APPROVED, 90.0, 80, false, List.of(), List.of(), null, null, null, 3, true);
                assertFalse(ResponseQualityV1.isDisplayable(noEvaluator, "req-strict-0001"), "evaluatorVersion 누락 = 계약 위반 = 미노출");
                Output noTask = new Output("response-quality.v1", "req-strict-0001", null, true, true, QualityStatus.APPROVED, 90.0, 80,
                                false, List.of(), List.of(), null, "rqg-1.0.0", null, 3, true);
                assertFalse(ResponseQualityV1.isDisplayable(noTask, "req-strict-0001"), "taskType 누락 미노출");
                Output nullMin = new Output("response-quality.v1", "req-strict-0001", TaskType.PDF_SUMMARY, true, true, QualityStatus.APPROVED,
                                90.0, null, false, List.of(), List.of(), null, "rqg-1.0.0", null, 3, true);
                assertTrue(ResponseQualityV1.isDisplayable(nullMin, "req-strict-0001"), "minimumScore null 허용(기준은 수신측 상수 80) — ai07 과 같음");
                Output min70 = new Output("response-quality.v1", "req-strict-0001", TaskType.PDF_SUMMARY, true, true, QualityStatus.APPROVED,
                                90.0, 70, false, List.of(), List.of(), null, "rqg-1.0.0", null, 3, true);
                assertFalse(ResponseQualityV1.isDisplayable(min70, "req-strict-0001"), "평가기가 기준을 낮춰 보내도 승인 불가");
        }
}
