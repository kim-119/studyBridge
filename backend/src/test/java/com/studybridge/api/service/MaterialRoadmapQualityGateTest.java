package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.ai.quality.SegmentedQualityGate;
import com.studybridge.api.dto.RoadmapDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Roadmap;
import com.studybridge.api.entity.RoadmapStep;
import com.studybridge.api.entity.RoadmapTask;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuestionRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.repository.RoadmapTaskRepository;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 자료보관함 84일 로드맵 분할 품질 게이트(Phase D — material). 실제 크기(≈13만 자 > 상한 6만 자)를 주차 세그먼트로 나눠
 * 전 세그먼트 승인 시에만 저장(quality_status + 진행 상태 제외 AI 본문 체크섬), 한 세그먼트라도 79 면 전체 거절 후 재생성,
 * 평가기 503/계획 형태 미인식(PLAN_EMPTY) 은 재생성 없이 중단, 결정적 검사 위반은 평가 없이 거절, 저장본은 체크섬이 맞을 때만 노출
 * (일자 완료 토글은 승인을 깨지 않음), 레거시/미승인/변조 저장본은 AI 본문을 가리고 진행 상태만, 게이트 OFF 회귀 없음.
 *
 * 경로 레지스트리상 로드맵 4개 경로는 아직 BLOCKED_WHEN_GATE_ON 이다(ai07 rqg-1.0.0 check_plan 이 세그먼트 객체를 PLAN_EMPTY 로
 * 항상 거절 — 보고서 5절). ai07 계약 변경 후 GATED 로 바꿀 때 @GateEvidence 를 붙일 증거 테스트:
 * approvedSegmentsAreSavedWithChecksumAndToggleKeepsApproval, oneSegment79RejectsWholeThenRegenerated80IsSaved,
 * allRejectedOrUnavailableKeepsExistingRoadmapAndSavesNothing, storedRoadmapShownOnlyWhenApprovedAndChecksumMatches,
 * legacyTaskToggleHidesContentUnderGate.
 */
class MaterialRoadmapQualityGateTest {

        static final long USER = 77L;
        static final long MATERIAL = 901L;
        static final ObjectMapper M = new ObjectMapper();
        static final String GEN = "/api/ai/roadmap/generate";
        static final String PDF_TEXT = "프로세스 스케줄링은 준비 큐의 프로세스 중 하나를 골라 CPU 를 할당한다. 선점형과 비선점형이 있다. ";

        MaterialAiStubServer stub;
        volatile java.util.function.IntFunction<String> generator = n -> roadmap("초안" + n, 0).toString();
        RoadmapRepository roadmaps;
        RoadmapTaskRepository tasks;
        final AtomicReference<Roadmap> stored = new AtomicReference<>();

        @BeforeEach
        void up() throws Exception {
                stub = new MaterialAiStubServer();
                stub.json(GEN, n -> generator.apply(n));
        }

        @AfterEach
        void down() {
                stub.close();
        }

        /** 12주 × 7일. 일자마다 ≈1.5k 자 → 전체 ≈13만 자(실제 84일 로드맵 크기 재현). minutesOverride>0 이면 첫 과제 소요 시간. */
        static ObjectNode roadmap(String marker, int minutesOverride) {
                ObjectNode r = M.createObjectNode();
                r.put("success", true);
                r.putNull("error_code");
                r.put("total_weeks", 12);
                r.put("days_per_week", 7);
                r.put("total_days", 84);
                r.put("level", "intermediate");
                r.put("title", "문서 기반 12주 학습 로드맵 " + marker);
                r.put("subject", "스케줄링");
                r.put("level_policy", "중급: 개념 이해 후 적용 문제를 푼다.");
                ArrayNode weeks = r.putArray("weeks");
                for (int w = 1; w <= 12; w++) {
                        ObjectNode wk = weeks.addObject();
                        wk.put("week", w);
                        wk.put("title", w + "주차 스케줄링 심화 " + marker);
                        wk.put("objective", w + "주차에는 스케줄링 알고리즘을 비교한다.");
                        wk.put("week_summary", w + "주차는 적용 단계다.");
                        ArrayNode days = wk.putArray("days");
                        for (int d = 1; d <= 7; d++) {
                                ObjectNode day = days.addObject();
                                day.put("day_index", d);
                                day.put("day_label", d + "일차");
                                day.putNull("date");
                                day.put("title", "라운드 로빈 타임 슬라이스 비교 " + w + "-" + d);
                                day.put("objective", "라운드 로빈과 우선순위 스케줄링의 대기 시간을 비교해 설명할 수 있다.");
                                day.putArray("core_concepts").add("라운드 로빈").add("타임 슬라이스");
                                ArrayNode ts = day.putArray("tasks");
                                for (int t = 1; t <= 3; t++) {
                                        ObjectNode task = ts.addObject();
                                        task.put("index", t);
                                        task.put("title", "간트 차트 작성 " + t);
                                        task.put("description", ("프로세스 다섯 개의 도착 시간과 실행 시간을 표로 정리하고 평균 대기 시간을 계산한다 " + w + "-" + d + "-" + t + ". ")
                                                        .repeat(6));
                                        task.put("estimated_minutes", t == 1 && minutesOverride > 0 ? minutesOverride : 30);
                                        task.put("difficulty", "normal");
                                }
                                day.put("practice", "타임 슬라이스를 바꿔 가며 문맥 교환 횟수를 비교한다.");
                                day.putArray("review_questions").add("라운드 로빈의 장점은 무엇인가?").add("타임 슬라이스가 너무 크면 어떻게 되는가?");
                                day.put("checkpoint", "평균 대기 시간을 직접 계산할 수 있다.");
                                day.put("deliverable", "간트 차트 정리 노트");
                        }
                }
                r.put("isFallback", false);
                ObjectNode v = r.putObject("validation");
                v.put("passed", true);
                v.put("reason", "12주 × 7일 = 84일 구조 검증 통과");
                return r;
        }

        AiIntegrationService service(boolean gateOn, Roadmap existing) {
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.PDF).title("네트워크 기초")
                                .extractedText(PDF_TEXT.repeat(40)).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                roadmaps = mock(RoadmapRepository.class);
                stored.set(existing);
                when(roadmaps.findByMaterial_MaterialId(MATERIAL)).thenAnswer(inv -> Optional.ofNullable(stored.get()));
                when(roadmaps.save(any(Roadmap.class))).thenAnswer(inv -> {
                        Roadmap r = inv.getArgument(0);
                        if (r.getRoadmapId() == null) {
                                r.setRoadmapId(5000L);
                        }
                        stored.set(r);
                        return r;
                });
                tasks = mock(RoadmapTaskRepository.class);
                AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", "http://127.0.0.1", stub.client())));
                AiIntegrationService svc = new AiIntegrationService(materials, mock(MaterialSummaryRepository.class), mock(MaterialQuizRepository.class),
                                mock(MaterialMemoRepository.class), mock(MaterialQuestionRepository.class), roadmaps, tasks, stub.client(),
                                mock(IntentRouterService.class), mock(LearningLoopService.class), mock(MaterialQuizService.class),
                                new AiFailoverExecutor(ups), stub.gate(gateOn), mock(com.studybridge.api.ai.training.TrainingCandidateCollector.class));
                ReflectionTestUtils.setField(svc, "roadmapTimeoutSeconds", 20L);
                return svc;
        }

        Roadmap savedRoadmap() {
                ArgumentCaptor<Roadmap> c = ArgumentCaptor.forClass(Roadmap.class);
                verify(roadmaps).save(c.capture());
                return c.getValue();
        }

        static Roadmap legacyUnapproved(String json) {
                return Roadmap.builder().roadmapId(10L).userId(USER).material(Material.builder().materialId(MATERIAL).build()).title("레거시 로드맵")
                                .roadmapJson(json).build();
        }

        @SuppressWarnings("unchecked")
        static Map<String, Object> firstDay(RoadmapDTO dto) {
                Map<String, Object> data = (Map<String, Object>) dto.getRoadmapData();
                Map<String, Object> w = ((List<Map<String, Object>>) data.get("weeks")).get(0);
                return ((List<Map<String, Object>>) w.get("days")).get(0);
        }

        @Test
        void approvedSegmentsAreSavedWithChecksumAndToggleKeepsApproval() throws Exception {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(85, "APPROVED");
                AiIntegrationService svc = service(true, null);
                RoadmapDTO dto = svc.regenerateRoadmap(USER, MATERIAL, "intermediate");
                assertEquals("APPROVED", dto.getQualityStatus());
                assertTrue(dto.getVerified());
                Roadmap saved = savedRoadmap();
                assertEquals("APPROVED", saved.getQualityStatus());
                assertTrue(saved.getRoadmapJson().length() > ResponseQualityV1.MAX_OUTPUT_CHARS, "실제 크기 재현: " + saved.getRoadmapJson().length());
                assertEquals(MaterialRoadmapQualityGate.checksum(M.readTree(saved.getRoadmapJson())), saved.getQualityChecksum());
                // 분할 평가: 헤더 + 주차 묶음, 세그먼트마다 고유 requestId, 상한·ai07 256KB 본문 제한 이내, 계약 taskType/outputKind
                assertTrue(stub.evaluations.size() >= 5, "세그먼트 수=" + stub.evaluations.size());
                assertEquals(stub.evaluations.size(), stub.evaluations.stream().map(e -> e.get("requestId").asText()).distinct().count());
                for (int i = 0; i < stub.evaluations.size(); i++) {
                        JsonNode e = stub.evaluations.get(i);
                        assertEquals("PLANNER_COACHING", e.get("taskType").asText());
                        assertEquals("plan_json", e.get("outputKind").asText());
                        assertTrue(e.get("proposedOutput").toString().length() <= ResponseQualityV1.MAX_OUTPUT_CHARS);
                        assertTrue(stub.evaluationBytes.get(i) < 256 * 1024, "ai07 본문 제한: " + stub.evaluationBytes.get(i));
                        assertEquals("PDF_ORIGINAL", e.get("groundingEvidence").get(0).get("sourceType").asText());
                        assertEquals(MATERIAL, e.get("constraints").get("allowedMaterialIds").get(0).asLong());
                }
                String all = String.join("", stub.evaluations.stream().map(MaterialAiStubServer::text).toList());
                assertTrue(all.contains("12주차 스케줄링 심화 초안1") && all.contains("level_policy"), "원문 전 범위(헤더·마지막 주차)가 평가됨");

                // 일자 완료 토글: 진행 상태는 체크섬 밖 → 승인 유지, 응답에 AI 본문 노출
                RoadmapDTO toggled = svc.toggleRoadmapDay(USER, MATERIAL, 1, 1);
                assertEquals("APPROVED", toggled.getQualityStatus());
                assertEquals(true, firstDay(toggled).get("completed"));
                assertNotNull(firstDay(toggled).get("title"));
                assertTrue(stored.get().getRoadmapJson().contains("\"completed\":true"));
                assertEquals(saved.getQualityChecksum(), MaterialRoadmapQualityGate.checksum(M.readTree(stored.get().getRoadmapJson())));
                assertTrue(MaterialRoadmapQualityGate.displayable("APPROVED", saved.getQualityChecksum(), stored.get().getRoadmapJson()));
        }

        @Test
        void oneSegment79RejectsWholeThenRegenerated80IsSaved() {
                // 첫 생성: 세 번째 세그먼트만 79 → 전체 거절(부분 승인 금지) → 재생성: 전부 80 → 승인
                int[] firstAttemptSegments = new int[1];
                stub.evaluator = (n, in) -> {
                        boolean first = in.get("requestId").asText().contains(".a0.");
                        if (first) {
                                firstAttemptSegments[0]++;
                        }
                        return first && in.get("requestId").asText().endsWith(".s2") ? MaterialAiStubServer.out(79, "REJECTED")
                                        : MaterialAiStubServer.out(80, "APPROVED");
                };
                AiIntegrationService svc = service(true, null);
                RoadmapDTO dto = svc.regenerateRoadmap(USER, MATERIAL, "beginner");
                assertEquals("APPROVED", dto.getQualityStatus());
                assertEquals(2, stub.calls(GEN));
                Roadmap saved = savedRoadmap();
                assertTrue(saved.getRoadmapJson().contains("초안2") && !saved.getRoadmapJson().contains("초안1"), "재생성된 초안만 저장");
                assertTrue(firstAttemptSegments[0] >= 3, "첫 초안도 모든 세그먼트를 평가(79 이후에도)");
        }

        @Test
        void allRejectedOrUnavailableKeepsExistingRoadmapAndSavesNothing() {
                Roadmap existing = legacyUnapproved(roadmap("기존", 0).toString());
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(70, "REJECTED");
                RoadmapDTO rej = service(true, existing).regenerateRoadmap(USER, MATERIAL, null);
                assertFalse(rej.getSuccess());
                assertEquals("AI_QUALITY_REJECTED", rej.getErrorCode());
                assertTrue(rej.getRetryable());
                assertEquals("REJECTED", rej.getQualityStatus());
                assertFalse(String.valueOf(rej.getRoadmapData()).contains("초안"), "응답에 초안 본문 0");
                assertEquals(3, stub.calls(GEN), "최초 1 + 재생성 2");
                verify(roadmaps, never()).save(any());
                verify(roadmaps, never()).delete(any());
                assertEquals(existing, stored.get(), "기존 로드맵 보존");

                stub.evaluations.clear();
                stub.evaluator = (n, in) -> null; // 평가기 503
                RoadmapDTO down = service(true, existing).regenerateRoadmap(USER, MATERIAL, null);
                assertEquals("AI_QUALITY_UNAVAILABLE", down.getErrorCode());
                assertEquals(4, stub.calls(GEN), "평가기 장애면 재생성하지 않는다");
                assertEquals(1, stub.evaluations.size(), "첫 세그먼트에서 장애 확인 후 중단");
                verify(roadmaps, never()).save(any());
        }

        @Test
        void planShapeHardFailFromEvaluatorStopsRegeneration() {
                // ai07 rqg-1.0.0 check_plan: items/plan/tasks 배열이 없는 세그먼트 객체 → PLAN_EMPTY(HARD). 재생성해도 같은 판정 → 1회로 중단.
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(40, "REJECTED", true, "PLAN_EMPTY");
                RoadmapDTO dto = service(true, null).regenerateRoadmap(USER, MATERIAL, null);
                assertEquals("AI_QUALITY_REJECTED", dto.getErrorCode());
                assertEquals(1, stub.calls(GEN), "84일 재생성(최대 180초)을 반복하지 않는다");
                verify(roadmaps, never()).save(any());
        }

        @Test
        void deterministicWholeValidatorRejectsBeforeEvaluation() {
                generator = n -> roadmap("초안" + n, 900).toString(); // 과제 900분 = 시간 제약 위반
                RoadmapDTO dto = service(true, null).regenerateRoadmap(USER, MATERIAL, null);
                assertEquals("AI_QUALITY_REJECTED", dto.getErrorCode());
                assertEquals(0, stub.evaluations.size(), "결정적 검사 실패면 평가기 호출 0");
                verify(roadmaps, never()).save(any());
                List<String> v = MaterialRoadmapQualityGate.VALIDATOR.violations(roadmap("x", 900));
                assertTrue(v.contains("ROADMAP_TASK_MINUTES_OUT_OF_RANGE"));
                ObjectNode badOrder = roadmap("x", 0);
                ((ObjectNode) badOrder.get("weeks").get(3)).put("week", 9);
                ((ObjectNode) badOrder.get("weeks").get(0).get("days").get(2)).put("date", "2026-11-05");
                ((ObjectNode) badOrder.get("weeks").get(0).get("days").get(3)).put("date", "2026-11-04");
                List<String> v2 = MaterialRoadmapQualityGate.VALIDATOR.violations(badOrder);
                assertTrue(v2.contains("ROADMAP_WEEK_ORDER") && v2.contains("ROADMAP_DATE_ORDER"), v2.toString());
                assertEquals(List.of(), MaterialRoadmapQualityGate.VALIDATOR.violations(roadmap("ok", 0)));
        }

        @Test
        void storedRoadmapShownOnlyWhenApprovedAndChecksumMatches() throws Exception {
                String json = roadmap("저장본", 0).toString();
                // 1) 레거시/게이트 OFF 저장본(판정 없음) → AI 본문 가림, 진행 상태만
                ObjectNode withProgress = (ObjectNode) M.readTree(json);
                ((ObjectNode) withProgress.get("weeks").get(0).get("days").get(0)).put("completed", true);
                RoadmapDTO legacy = service(true, legacyUnapproved(withProgress.toString())).getRoadmap(USER, MATERIAL);
                assertTrue(legacy.getQualityRedacted());
                assertEquals(MaterialRoadmapQualityGate.REDACTED_TITLE, legacy.getTitle());
                assertFalse(String.valueOf(legacy.getRoadmapData()).contains("라운드 로빈"), "AI 본문 0");
                assertFalse(String.valueOf(legacy.getRoadmapData()).contains("저장본"));
                assertEquals(true, firstDay(legacy).get("completed"), "사용자 진행 상태 유지");
                assertEquals(1, firstDay(legacy).get("day_index"));
                assertEquals(0, stub.calls(GEN), "저장본 조회는 생성하지 않는다");
                assertEquals(0, stub.evaluations.size());

                // 2) 승인 + 체크섬 일치 → 노출
                Roadmap approved = legacyUnapproved(withProgress.toString());
                approved.setQualityStatus("APPROVED");
                approved.setQualityChecksum(MaterialRoadmapQualityGate.checksum(M.readTree(json))); // 진행 상태 없는 원본 기준
                RoadmapDTO ok = service(true, approved).getRoadmap(USER, MATERIAL);
                assertEquals("APPROVED", ok.getQualityStatus());
                assertTrue(String.valueOf(ok.getRoadmapData()).contains("라운드 로빈"));

                // 3) 승인 기록이 있어도 AI 본문이 바뀌었으면(변조·부분 갱신) 승인 범위 밖 → 가림
                ObjectNode tampered = (ObjectNode) M.readTree(withProgress.toString());
                ((ObjectNode) tampered.get("weeks").get(5)).put("title", "승인 후 바뀐 주차 제목");
                approved.setRoadmapJson(tampered.toString());
                RoadmapDTO t = service(true, approved).getRoadmap(USER, MATERIAL);
                assertTrue(t.getQualityRedacted());
                assertFalse(String.valueOf(t.getRoadmapData()).contains("승인 후 바뀐"));

                // 4) 미승인 저장본 토글 응답도 가림
                RoadmapDTO toggled = service(true, legacyUnapproved(json)).toggleRoadmapDay(USER, MATERIAL, 2, 3);
                assertTrue(toggled.getQualityRedacted());
                assertFalse(String.valueOf(toggled.getRoadmapData()).contains("라운드 로빈"));
        }

        @Test
        void legacyTaskToggleHidesContentUnderGate() {
                Material material = Material.builder().materialId(MATERIAL).build();
                Roadmap rm = Roadmap.builder().roadmapId(3L).userId(USER).material(material).title("레거시").build();
                RoadmapStep step = RoadmapStep.builder().stepId(1L).stepOrder(1).title("1주차 AI 제목").roadmap(rm).build();
                RoadmapTask task = RoadmapTask.builder().taskId(44L).taskOrder(1).content("AI 과제 문구").isCompleted(false).step(step).build();
                AiIntegrationService on = service(true, rm);
                when(tasks.findById(44L)).thenReturn(Optional.of(task));
                RoadmapDTO.RoadmapTaskDTO r = on.toggleRoadmapTask(USER, MATERIAL, 44L);
                assertNull(r.getContent());
                assertTrue(r.getQualityRedacted());
                assertTrue(r.getIsCompleted(), "진행 상태 토글은 그대로");
                step.setTasks(new ArrayList<>(List.of(task)));
                rm.setSteps(new ArrayList<>(List.of(step)));
                RoadmapDTO legacyGet = on.getRoadmap(USER, MATERIAL);
                assertTrue(legacyGet.getQualityRedacted());
                assertNull(legacyGet.getSteps().get(0).getTitle());
                assertNull(legacyGet.getSteps().get(0).getTasks().get(0).getContent());

                AiIntegrationService off = service(false, rm);
                when(tasks.findById(44L)).thenReturn(Optional.of(task));
                RoadmapDTO.RoadmapTaskDTO r2 = off.toggleRoadmapTask(USER, MATERIAL, 44L);
                assertEquals("AI 과제 문구", r2.getContent());
                assertNull(r2.getQualityRedacted());
        }

        @Test
        void gateOffIsLegacyBehaviour() {
                RoadmapDTO dto = service(false, null).regenerateRoadmap(USER, MATERIAL, null);
                assertTrue(dto.getSuccess());
                assertNull(dto.getQualityStatus());
                assertNull(dto.getQualityRedacted());
                assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
                Roadmap saved = savedRoadmap();
                assertNull(saved.getQualityStatus());
                assertNull(saved.getQualityChecksum());
                RoadmapDTO shown = service(false, legacyUnapproved(roadmap("기존", 0).toString())).getRoadmap(USER, MATERIAL);
                assertTrue(String.valueOf(shown.getRoadmapData()).contains("라운드 로빈"), "OFF 에선 기존 저장본 그대로");
                assertNull(shown.getQualityRedacted());
        }

        @Test
        void segmenterSplitsOversizedWeekAtDayLevelWithFullCoverage() throws Exception {
                ObjectNode big = roadmap("대형", 0);
                ObjectNode w0 = (ObjectNode) big.get("weeks").get(0);
                for (JsonNode d : w0.get("days")) {
                        ((ObjectNode) d).put("practice", "아주 긴 실습 설명 ".repeat(400)); // 주차 하나 > 예산
                }
                assertTrue(w0.toString().length() > MaterialRoadmapQualityGate.SEGMENT_BUDGET_CHARS);
                List<SegmentedQualityGate.SegmentPlan> plans = MaterialRoadmapQualityGate.segmenter(MaterialRoadmapQualityGate.SEGMENT_BUDGET_CHARS)
                                .plan(MaterialRoadmapQualityGate.aiBody(big));
                assertTrue(plans.stream().anyMatch(p -> p.pointers().contains("/weeks/0/days/0")), "주차 초과분은 일자 단위로");
                assertTrue(plans.stream().anyMatch(p -> p.pointers().contains("/weeks/0/title")));
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(90, "APPROVED");
                AiQualityGateSettings s = AiQualityGateSettings.forTest(true);
                SegmentedQualityGate g = new SegmentedQualityGate(new AiResponseQualityGate(s, new QualityEvaluatorClient(stub.client(), s, "k".repeat(64))));
                SegmentedQualityGate.Result res = g.evaluate(new AiResponseQualityGate.Spec("req-roadmap-seg-01", ResponseQualityV1.TaskType.PLANNER_COACHING,
                                ResponseQualityV1.OutputKind.PLAN_JSON, "84일 로드맵", List.of(), ResponseQualityV1.Constraints.empty(), null),
                                MaterialRoadmapQualityGate.aiBody(big), MaterialRoadmapQualityGate.segmenter(MaterialRoadmapQualityGate.SEGMENT_BUDGET_CHARS),
                                MaterialRoadmapQualityGate.VALIDATOR, 0);
                assertTrue(res.approved(), "커버리지 누락·중복 없음: " + res.violations());
                assertEquals(plans.size(), stub.evaluations.size());
        }
}
