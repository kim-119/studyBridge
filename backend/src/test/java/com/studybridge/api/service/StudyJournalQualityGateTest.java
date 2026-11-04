package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.StudyJournalDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.StudyJournal;
import com.studybridge.api.exception.StudyJournalRejectedException;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.StudyJournalRepository;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 학습일지 품질 게이트(Phase D — material). 판정(ACCEPT/수정 요청/차단)은 저장 허용 여부를 정하는 게이트 판단이라 평가기로 다시 거르지 않고,
 * 사용자에게 보이는 AI 자유 텍스트(연결 경로·사유·제안)만 평가한다(재생성 없음 — 재검증은 판정을 바꿀 수 있음).
 * 미승인 문구는 DB/S3/응답 어디에도 없고(거절 사유는 분류별 Spring 고정 문구), 메모 본문(사용자 데이터)은 가리지 않는다.
 * 목록/상세는 quality_status≠APPROVED 인 연결 경로를 가리고 판정 라벨은 허용 enum 만 내보낸다. Spring 로컬 폴백은 평가하지 않는다.
 */
class StudyJournalQualityGateTest {

        static final long USER = 21L;
        static final long MATERIAL = 733L;
        static final String VALIDATE = "/api/ai/study-journal/validate";
        static final String MEMO = "상속은 부모 클래스의 속성과 메서드를 자식 클래스가 재사용하는 것이라고 정리했다.";
        static final ObjectMapper M = new ObjectMapper();

        MaterialAiStubServer stub;
        volatile String verdict = accept("OOP → 상속(AI경로)");
        volatile boolean validatorDown;
        StudyJournalRepository journals;
        StudyJournalS3Service s3;

        static String accept(String path) {
                return "{\"decision\":\"ACCEPT\",\"category\":\"PDF_CONCEPT_SUMMARY\",\"relationType\":\"CHILD_CONCEPT\",\"relationPath\":\"" + path
                                + "\",\"studyRelated\":true,\"pdfGrounded\":true,\"conceptExpanded\":true,\"confidence\":0.9,\"reason\":\"AI사유-수락\","
                                + "\"suggestion\":null}";
        }

        static String revision(String category) {
                return "{\"decision\":\"REQUEST_REVISION\",\"category\":\"" + category + "\",\"relationType\":\"NONE\",\"relationPath\":\"AI경로-거절\","
                                + "\"studyRelated\":false,\"pdfGrounded\":false,\"conceptExpanded\":false,\"confidence\":0.4,"
                                + "\"reason\":\"AI사유원문: 자료의 다형성과 연결되지 않습니다\",\"suggestion\":\"AI제안원문: 오버라이딩 예시를 덧붙이세요\"}";
        }

        @BeforeEach
        void up() throws Exception {
                stub = new MaterialAiStubServer();
                stub.route(VALIDATE, (n, in) -> validatorDown ? new MaterialAiStubServer.Reply(503, "{}") : new MaterialAiStubServer.Reply(200, verdict));
        }

        @AfterEach
        void down() {
                stub.close();
        }

        StudyJournalService service(boolean gateOn, List<StudyJournal> existing) {
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.PDF).title("객체지향 프로그래밍")
                                .keywords("상속, 다형성").extractedText("상속은 기존 클래스를 확장한다. 다형성은 같은 메시지에 다르게 반응한다. ".repeat(5)).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                journals = mock(StudyJournalRepository.class);
                when(journals.saveAndFlush(any(StudyJournal.class))).thenAnswer(inv -> {
                        StudyJournal j = inv.getArgument(0);
                        j.setId(99L);
                        return j;
                });
                when(journals.findByMaterialIdAndStatusOrderByCreatedAtDesc(MATERIAL, StudyJournal.StudyJournalStatus.ACTIVE)).thenReturn(existing);
                for (StudyJournal j : existing) {
                        when(journals.findByIdAndStatus(j.getId(), StudyJournal.StudyJournalStatus.ACTIVE)).thenReturn(Optional.of(j));
                }
                s3 = mock(StudyJournalS3Service.class);
                when(s3.buildKey(anyLong(), anyLong(), anyString())).thenReturn("journals/k.json");
                when(s3.getJournalJson(anyString())).thenReturn("{\"content\":\"" + MEMO + "\"}");
                StudyJournalValidationClient client = new StudyJournalValidationClient(stub.client(), VALIDATE, 5, "");
                StudyJournalService svc = new StudyJournalService(materials, journals, client, s3, M);
                svc.setQualityGate(stub.gate(gateOn));
                return svc;
        }

        StudyJournal savedJournal() {
                ArgumentCaptor<StudyJournal> c = ArgumentCaptor.forClass(StudyJournal.class);
                verify(journals).saveAndFlush(c.capture());
                return c.getValue();
        }

        String s3Body() {
                ArgumentCaptor<byte[]> c = ArgumentCaptor.forClass(byte[].class);
                verify(s3).putJournalJson(eq("journals/k.json"), c.capture(), anyMap());
                return new String(c.getValue(), StandardCharsets.UTF_8);
        }

        static StudyJournal row(long id, String path, String quality, String category) {
                return StudyJournal.builder().id(id).materialId(MATERIAL).userId(USER).s3Key("journals/" + id + ".json")
                                .validationDecision("ACCEPT").validationCategory(category).relationType("DIRECT").relationPath(path)
                                .qualityStatus(quality).confidence(0.8).build();
        }

        @GateEvidence({"POST /api/materials/{materialId}/study-journals"})
        @Test
        void unapprovedRejectionReasonIsReplacedByFixedTextAndJudgementIsNotRegenerated() {
                verdict = revision("OFF_TOPIC");
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(79, "REJECTED");
                StudyJournalRejectedException e = assertThrows(StudyJournalRejectedException.class,
                                () -> service(true, List.of()).create(USER, MATERIAL, MEMO));
                StudyJournalValidationResult r = e.getResult();
                assertEquals("REQUEST_REVISION", r.getDecision(), "판정은 그대로(평가기가 판정을 바꾸지 않음)");
                assertEquals("OFF_TOPIC", r.getCategory());
                assertEquals(StudyJournalService.fixedReason("OFF_TOPIC"), r.getReason());
                assertEquals(StudyJournalService.fixedSuggestion("OFF_TOPIC"), r.getSuggestion());
                assertNull(r.getRelationPath());
                assertTrue(r.getQualityRedacted());
                assertEquals("REJECTED", r.getQualityStatus());
                assertEquals(1, stub.calls(VALIDATE), "재검증(=판정 재추첨) 없음");
                assertEquals(1, stub.evaluations.size(), "문구 재생성 없음");
                String proposed = MaterialAiStubServer.text(stub.evaluations.get(0));
                assertTrue(proposed.contains("AI사유원문") && proposed.contains("AI제안원문") && proposed.contains("AI경로-거절"), "노출 문구 전부 평가");
                JsonNode g = stub.evaluations.get(0).get("groundingEvidence");
                assertEquals("USER_INPUT", g.get(0).get("sourceType").asText());
                assertEquals(MEMO, g.get(0).get("text").asText(), "근거 = 학습자가 쓴 메모");
                assertEquals("PDF_ORIGINAL", g.get(1).get("sourceType").asText());
                assertEquals(MATERIAL, stub.evaluations.get(0).get("constraints").get("allowedMaterialIds").get(0).asLong());
                verify(journals, never()).saveAndFlush(any());
                verify(s3, never()).putJournalJson(anyString(), any(), anyMap());
        }

        @GateEvidence({"POST /api/materials/{materialId}/study-journals"})
        @Test
        void approvedRejectionReasonAt80IsShownAsIs() {
                verdict = revision("OFF_TOPIC");
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(80, "APPROVED");
                StudyJournalRejectedException e = assertThrows(StudyJournalRejectedException.class,
                                () -> service(true, List.of()).create(USER, MATERIAL, MEMO));
                assertTrue(e.getResult().getReason().startsWith("AI사유원문"));
                assertEquals("AI경로-거절", e.getResult().getRelationPath());
                assertEquals("APPROVED", e.getResult().getQualityStatus());
                assertNull(e.getResult().getQualityRedacted());
        }

        @GateEvidence({"POST /api/materials/{materialId}/study-journals", "GET /api/materials/{materialId}/study-journals",
                        "GET /api/materials/{materialId}/study-journals/{journalId}"})
        @Test
        void acceptedJournalStoresOnlyApprovedPathAndListHidesUnapprovedPaths() {
                // 평가기 503 → 판정 ACCEPT 이므로 메모는 저장하되, 미검증 AI 연결 경로는 DB·S3·응답 어디에도 없다.
                stub.evaluator = (n, in) -> null;
                StudyJournalDTO.Response saved = service(true, List.of()).create(USER, MATERIAL, MEMO);
                StudyJournal j = savedJournal();
                assertNull(j.getRelationPath());
                assertNull(j.getQualityStatus());
                assertFalse(s3Body().contains("AI경로"), "S3 원문 JSON 에도 미검증 경로 없음");
                assertTrue(s3Body().contains(MEMO), "메모 본문(사용자 데이터)은 저장");
                assertNull(saved.getRelationPath());
                assertEquals("ACCEPT", saved.getValidationDecision());

                // 승인(85) → 경로 저장(quality_status=APPROVED) + 응답 노출
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(85, "APPROVED");
                StudyJournalDTO.Response ok = service(true, List.of()).create(USER, MATERIAL, MEMO);
                StudyJournal j2 = savedJournal();
                assertEquals("OOP → 상속(AI경로)", j2.getRelationPath());
                assertEquals("APPROVED", j2.getQualityStatus());
                assertEquals("OOP → 상속(AI경로)", ok.getRelationPath());
                assertTrue(s3Body().contains("AI경로"));

                // 목록/상세: 레거시(판정 없음) 경로는 가리고, 승인 경로만. 허용 밖 판정 라벨(자유 텍스트)은 내보내지 않음.
                StudyJournal legacy = row(1L, "레거시 AI 경로", null, "PDF_CONCEPT_SUMMARY");
                StudyJournal approved = row(2L, "승인된 경로", "APPROVED", "자유 텍스트 분류 라벨");
                StudyJournalService svc = service(true, List.of(legacy, approved));
                int evaluationsBefore = stub.evaluations.size();
                List<StudyJournalDTO.Response> list = svc.list(USER, MATERIAL);
                assertNull(list.get(0).getRelationPath());
                assertTrue(list.get(0).getQualityRedacted());
                assertEquals("PDF_CONCEPT_SUMMARY", list.get(0).getValidationCategory());
                assertEquals("승인된 경로", list.get(1).getRelationPath());
                assertNull(list.get(1).getQualityRedacted());
                assertNull(list.get(1).getValidationCategory(), "enum 밖 라벨은 노출 금지");
                StudyJournalDTO.Response detail = svc.detail(USER, MATERIAL, 1L);
                assertNull(detail.getRelationPath());
                assertTrue(detail.getQualityRedacted());
                assertEquals(MEMO, detail.getContent(), "메모 본문은 가리지 않는다");
                assertEquals(evaluationsBefore, stub.evaluations.size(), "목록/상세는 평가기를 부르지 않는다(저장본 판정만 본다)");
        }

        @Test
        void localFallbackTextIsSpringFixedAndNotEvaluated() {
                validatorDown = true; // ai07 503 → Spring 제한적 로컬 폴백
                StudyJournalRejectedException e = assertThrows(StudyJournalRejectedException.class,
                                () -> service(true, List.of()).create(USER, MATERIAL, "이거 너무 어렵다 모르겠다"));
                assertTrue(e.getResult().isLocalOrigin());
                assertEquals(0, stub.evaluations.size(), "Spring 고정 문구는 평가하지 않는다");
                assertNull(e.getResult().getQualityRedacted());
        }

        @Test
        void gateOffIsLegacyBehaviour() {
                StudyJournalDTO.Response saved = service(false, List.of()).create(USER, MATERIAL, MEMO);
                assertEquals("OOP → 상속(AI경로)", saved.getRelationPath());
                assertNull(saved.getQualityStatus());
                assertNull(savedJournal().getQualityStatus());
                assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
                List<StudyJournalDTO.Response> list = service(false, List.of(row(1L, "레거시 AI 경로", null, "아무 라벨"))).list(USER, MATERIAL);
                assertEquals("레거시 AI 경로", list.get(0).getRelationPath());
                assertEquals("아무 라벨", list.get(0).getValidationCategory());
                assertNull(list.get(0).getQualityRedacted());
                verdict = revision("OFF_TOPIC");
                StudyJournalRejectedException e = assertThrows(StudyJournalRejectedException.class,
                                () -> service(false, List.of()).create(USER, MATERIAL, MEMO));
                assertTrue(e.getResult().getReason().startsWith("AI사유원문"));
                assertNull(e.getResult().getQualityStatus());
        }
}
