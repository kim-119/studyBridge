package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.StudyNoteAnalysisDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialStudyNoteAnalysis;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialStudyNoteAnalysisRepository;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * AI 핵심 요약 노트(업로드 후 백그라운드 생성) 품질 게이트(Phase D — material): 생성 시점에 분할 평가(GENERAL_EXPLANATION, 근거 = 자료 원문
 * 페이지별 + allowedMaterialIds) → 79 거절 후 재생성 80 승인분만 저장, 전부 거절/평가기 503 이면 어떤 저장 시점에도 초안 0(FAILED + 고정 사유),
 * 이전 승인 노트는 재분석 거절로 덮어쓰지 않음, GET 은 미승인/레거시 행의 AI 필드를 가림, 게이트 OFF 회귀 없음.
 */
class StudyNoteQualityGateTest {

        static final long USER = 9L;
        static final long MATERIAL = 620L;
        static final String NOTE = "/api/ai/major-analysis/note";
        static final String PAGE1 = "TCP 는 연결 지향 프로토콜이다. 3-way handshake 로 연결을 수립한다.";
        static final String PAGE2 = "UDP 는 비연결형이며 헤더가 8바이트다. 순서 보장이 없다.";

        MaterialAiStubServer stub;
        MaterialStudyNoteAnalysisRepository repo;
        final AtomicReference<MaterialStudyNoteAnalysis> row = new AtomicReference<>();
        /** 저장 시점마다의 AI 필드 스냅샷(같은 엔티티를 여러 번 save 하므로 마지막 상태만 보면 중간 저장을 놓친다). */
        final List<String> savedSnapshots = new CopyOnWriteArrayList<>();
        volatile boolean noteFails;

        @BeforeEach
        void up() throws Exception {
                stub = new MaterialAiStubServer();
                stub.route(NOTE, (n, in) -> noteFails ? new MaterialAiStubServer.Reply(500, "{}")
                                : new MaterialAiStubServer.Reply(200, "{\"domain\":\"COMPUTER_SCIENCE\",\"domainLabel\":\"컴퓨터공학\","
                                                + "\"coreObject\":\"TRANSPORT\",\"coreObjectLabel\":\"전송 계층\",\"documentOverview\":\"노트초안" + n
                                                + ": 전송 계층의 TCP 와 UDP 를 비교한다.\",\"keywords\":[\"TCP\",\"UDP\"],\"coreContents\":[\"TCP 는 연결 지향이다.\"],"
                                                + "\"detailedCoreContents\":[{\"title\":\"연결 수립\",\"content\":\"3-way handshake\"}],"
                                                + "\"pageSummaries\":[{\"page\":2,\"title\":\"UDP\",\"pageOverview\":\"UDP 헤더는 8바이트다.\"},"
                                                + "{\"page\":1,\"title\":\"TCP\",\"pageOverview\":\"연결 지향\"}],"
                                                + "\"studyPoints\":[\"TCP 와 UDP 차이\"],\"aiStudyQuestions\":[\"UDP 헤더 크기는?\"],"
                                                + "\"wikiSummaries\":[],\"limitations\":[]}"));
        }

        @AfterEach
        void down() {
                stub.close();
        }

        StudyNoteAnalysisService service(boolean gateOn, MaterialStudyNoteAnalysis existing) {
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.PDF).title("네트워크")
                                .extractedText(PAGE1 + "\f" + PAGE2).s3FileUrl("materials/9/a.pdf").build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                repo = mock(MaterialStudyNoteAnalysisRepository.class);
                row.set(existing);
                when(repo.findByMaterialId(MATERIAL)).thenAnswer(inv -> Optional.ofNullable(row.get()));
                when(repo.save(any(MaterialStudyNoteAnalysis.class))).thenAnswer(inv -> {
                        MaterialStudyNoteAnalysis r = inv.getArgument(0);
                        savedSnapshots.add(r.getStatus() + "|" + r.getQualityStatus() + "|" + r.getDocumentOverview() + "|" + r.getDomain() + "|"
                                        + r.getPageSummariesJson() + "|" + r.getCoreContentsJson());
                        row.set(r);
                        return r;
                });
                StudyNoteAnalysisService svc = new StudyNoteAnalysisService(materials, repo, stub.client());
                ReflectionTestUtils.setField(svc, "timeoutSeconds", 10L);
                svc.setQualityGate(stub.gate(gateOn));
                return svc;
        }

        static MaterialStudyNoteAnalysis stored(String status, String quality) {
                return MaterialStudyNoteAnalysis.builder().id(1L).materialId(MATERIAL).userId(USER).status(status).qualityStatus(quality)
                                .domain("COMPUTER_SCIENCE").domainLabel("컴퓨터공학").documentOverview("레거시 미검증 노트 개요")
                                .keywordsJson("[\"레거시키워드\"]").coreContentsJson("[\"레거시 핵심\"]").pageSummariesJson("[]").build();
        }

        @GateEvidence({"GET /api/materials/{materialId}/study-note"})
        @Test
        void rejected79ThenApproved80IsTheOnlyStoredDraft() {
                stub.evaluator = (n, in) -> in.get("requestId").asText().contains(".a0.") ? MaterialAiStubServer.out(79, "REJECTED")
                                : MaterialAiStubServer.out(80, "APPROVED");
                StudyNoteAnalysisService svc = service(true, null);
                svc.analyze(MATERIAL);
                MaterialStudyNoteAnalysis r = row.get();
                assertEquals("SUCCESS", r.getStatus());
                assertEquals("APPROVED", r.getQualityStatus());
                assertTrue(r.getDocumentOverview().startsWith("노트초안2"), "재생성된 승인 초안만 저장");
                assertEquals(2, stub.calls(NOTE));
                assertTrue(savedSnapshots.stream().noneMatch(s -> s.contains("노트초안1")), "거절된 초안은 어떤 저장 시점에도 없음");
                JsonNode ev = stub.evaluations.get(0);
                assertEquals("GENERAL_EXPLANATION", ev.get("taskType").asText());
                String proposed = MaterialAiStubServer.text(ev);
                assertTrue(proposed.contains("노트초안1") && proposed.contains("UDP 헤더 크기는?") && proposed.contains("전송 계층"),
                                "화면에 나갈 노트 필드 전부 평가");
                JsonNode g = ev.get("groundingEvidence");
                assertEquals(2, g.size(), "페이지별 원문 근거");
                assertEquals(1, g.get(0).get("page").asInt());
                assertEquals(2, g.get(1).get("page").asInt());
                assertTrue(g.get(1).get("text").asText().contains("8바이트"));
                assertEquals(MATERIAL, ev.get("constraints").get("allowedMaterialIds").get(0).asLong());

                StudyNoteAnalysisDTO dto = svc.get(USER, MATERIAL);
                assertEquals("SUCCESS", dto.getStatus());
                assertEquals("APPROVED", dto.getQualityStatus());
                assertTrue(dto.getDocumentOverview().startsWith("노트초안2"));
        }

        @GateEvidence({"GET /api/materials/{materialId}/study-note"})
        @Test
        void allRejectedOrUnavailableStoresNoDraft() {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(70, "REJECTED");
                service(true, null).analyze(MATERIAL);
                assertEquals("FAILED", row.get().getStatus());
                assertEquals(StudyNoteAnalysisService.GATE_REJECTED_MESSAGE, row.get().getErrorMessage());
                assertNull(row.get().getQualityStatus());
                assertTrue(savedSnapshots.stream().noneMatch(s -> s.contains("노트초안") || s.contains("TRANSPORT")), savedSnapshots.toString());
                assertEquals(3, stub.calls(NOTE), "최초 1 + 재생성 2");

                savedSnapshots.clear();
                stub.evaluator = (n, in) -> null; // 503
                service(true, null).analyze(MATERIAL);
                assertEquals("FAILED", row.get().getStatus());
                assertEquals(StudyNoteAnalysisService.GATE_UNAVAILABLE_MESSAGE, row.get().getErrorMessage());
                assertEquals(4, stub.calls(NOTE), "평가기 장애면 재생성하지 않는다");
                assertTrue(savedSnapshots.stream().noneMatch(s -> s.contains("노트초안")));
        }

        @Test
        void hardFailIsRejected() {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(96, "REJECTED", true, "UNVERIFIED_CITATION");
                service(true, null).analyze(MATERIAL);
                assertEquals("FAILED", row.get().getStatus());
                assertTrue(savedSnapshots.stream().noneMatch(s -> s.contains("노트초안")));
        }

        @Test
        void reanalysisRejectionKeepsPreviouslyApprovedNote() {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(60, "REJECTED");
                MaterialStudyNoteAnalysis approved = stored("SUCCESS", "APPROVED");
                service(true, approved).analyze(MATERIAL);
                assertEquals("SUCCESS", row.get().getStatus());
                assertEquals("APPROVED", row.get().getQualityStatus());
                assertEquals("레거시 미검증 노트 개요", row.get().getDocumentOverview(), "승인 노트를 덮어쓰지 않는다");
        }

        @GateEvidence({"GET /api/materials/{materialId}/study-note"})
        @Test
        void unapprovedLegacyRowIsRedactedOnGetAndApprovedRowIsShown() {
                StudyNoteAnalysisDTO legacy = service(true, stored("SUCCESS", null)).get(USER, MATERIAL);
                assertEquals("UNVERIFIED", legacy.getStatus(), "미검증 SUCCESS 를 SUCCESS 로 내보내지 않는다");
                assertTrue(legacy.getQualityRedacted());
                assertNull(legacy.getDocumentOverview());
                assertNull(legacy.getDomain());
                assertTrue(legacy.getKeywords().isEmpty() && legacy.getCoreContents().isEmpty());
                assertEquals(StudyNoteAnalysisService.REDACTED_MESSAGE, legacy.getErrorMessage());
                assertEquals(0, stub.calls(NOTE), "조회는 생성하지 않는다");
                assertEquals(0, stub.evaluations.size());

                StudyNoteAnalysisDTO failedLegacy = service(true, stored("FAILED", null)).get(USER, MATERIAL);
                assertEquals("FAILED", failedLegacy.getStatus());
                assertNull(failedLegacy.getDocumentOverview(), "FAILED 행에 남은 미검증 AI 필드도 가림");

                StudyNoteAnalysisDTO ok = service(true, stored("SUCCESS", "APPROVED")).get(USER, MATERIAL);
                assertEquals("SUCCESS", ok.getStatus());
                assertEquals("APPROVED", ok.getQualityStatus());
                assertEquals("레거시 미검증 노트 개요", ok.getDocumentOverview());
                assertNull(ok.getQualityRedacted());
        }

        @Test
        void generationFailureIsFailedWithoutEvaluation() {
                noteFails = true;
                service(true, null).analyze(MATERIAL);
                assertEquals("FAILED", row.get().getStatus());
                assertEquals(1, stub.calls(NOTE));
                assertEquals(0, stub.evaluations.size());
        }

        @Test
        void gateOffIsLegacyBehaviour() {
                StudyNoteAnalysisService svc = service(false, null);
                svc.analyze(MATERIAL);
                assertEquals("SUCCESS", row.get().getStatus());
                assertNull(row.get().getQualityStatus());
                assertTrue(row.get().getDocumentOverview().startsWith("노트초안1"));
                assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
                StudyNoteAnalysisDTO dto = service(false, stored("SUCCESS", null)).get(USER, MATERIAL);
                assertEquals("SUCCESS", dto.getStatus());
                assertEquals("레거시 미검증 노트 개요", dto.getDocumentOverview());
                assertNull(dto.getQualityStatus());
                assertNull(dto.getQualityRedacted());
        }
}
