package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.util.ConceptFallbackProvider;
import com.studybridge.api.util.LearningContentSanitizer;
import com.lowagie.text.Document;
import com.lowagie.text.Element;
import com.lowagie.text.Font;
import com.lowagie.text.PageSize;
import com.lowagie.text.Paragraph;
import com.lowagie.text.Phrase;
import com.lowagie.text.pdf.BaseFont;
import com.lowagie.text.pdf.PdfPCell;
import com.lowagie.text.pdf.PdfPTable;
import com.lowagie.text.pdf.PdfWriter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.awt.Color;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.time.LocalDateTime;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerService {

    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final S3Service s3Service;
    private final ObjectMapper objectMapper;

    private static final Color GREEN_DARK = new Color(0x15, 0x80, 0x3D);
    private static final Color GREEN_LIGHT = new Color(0xEC, 0xFD, 0xF3);
    private static final Color GREEN_BORDER = new Color(0xBB, 0xF7, 0xD0);
    private static final Color GREY_LINE = new Color(0xD1, 0xD5, 0xDB);

    private static byte[] cachedFont;

    // ---------- CRUD ----------

    @Transactional
    public PlannerDTO.Response create(Long userId, PlannerDTO.Request req) {
        // 사용자가 플래너 화면에서 직접 만드는 경로 → 항상 USER. 로드맵(ROADMAP) 저장은 /from-roadmap 전용이다.
        // (요청 plannerType 은 무시하고 강제 USER — 수동 플래너가 ROADMAP 으로 위장되어 로드맵 전체삭제에 휩쓸리는 것을 차단)
        Planner planner = Planner.builder()
                .userId(userId)
                .plannerType(PlannerType.USER)
                .title(req.getTitle() != null && !req.getTitle().isBlank() ? req.getTitle() : "공부 플래너")
                .year(req.getYear()).month(req.getMonth()).day(req.getDay())
                .dayOfWeek(req.getDayOfWeek())
                .plannerDate(req.getPlannerDate())
                .goalTime(req.getGoalTime())
                .netStudyTime(req.getNetStudyTime())
                .wakeUpTime(req.getWakeUpTime())
                .dDay(req.getDDay())
                .studyType(req.getStudyType())
                .priority(req.getPriority())
                .term(req.getTerm())
                .subject(req.getSubject())
                .content(req.getContent())
                .tmi(req.getTmi())
                .timeTableJson(req.getTimeTableJson())
                .build();
        return toResponse(plannerRepository.save(planner), false);
    }

    // ---------- 로드맵 기반 84개 플래너 자동 생성 (D/E) ----------
    @Transactional
    public PlannerDTO.FromRoadmapResponse createFromRoadmap(Long userId, PlannerDTO.FromRoadmapRequest req) {
        java.util.List<PlannerDTO.RoadmapItem> items = req.getItems() != null ? req.getItems() : java.util.Collections.emptyList();
        if (items.isEmpty()) {
            throw new IllegalArgumentException("로드맵 항목이 비어 있습니다. 먼저 84일 로드맵을 생성해주세요.");
        }

        final String SOURCE_TYPE = "ROADMAP_AUTO";
        long existing = req.getMaterialId() != null
                ? plannerRepository.countByUserIdAndSourceMaterialIdAndSourceType(userId, req.getMaterialId(), SOURCE_TYPE)
                : 0L;
        boolean force = Boolean.TRUE.equals(req.getForce());
        if (existing > 0 && !force) {
            return PlannerDTO.FromRoadmapResponse.builder()
                    .createdCount(0).duplicate(true).existingCount(existing)
                    .message("이미 이 자료로 생성된 플래너가 있습니다. 다시 생성하면 기존 항목을 유지한 채 추가됩니다.")
                    .build();
        }

        String subject = (req.getSubject() != null && !req.getSubject().isBlank()) ? req.getSubject() : null;
        if (subject == null && req.getMaterialId() != null) {
            subject = materialRepository.findById(req.getMaterialId()).map(Material::getTitle).orElse(null);
        }
        if (subject == null) subject = "자료 기반 학습";

        java.time.LocalDate start = req.getStartDate() != null ? req.getStartDate() : java.time.LocalDate.now();

        int created = 0;
        int[] noiseStats = new int[4]; // [0]=noiseCandidate, [1]=cleaned, [2]=rejected, [3]=fallbackUsedFields
        for (int i = 0; i < items.size(); i++) {
            PlannerDTO.RoadmapItem it = items.get(i);
            java.time.LocalDate date = start.plusDays(i);

            // 노이즈 정제: PDF 표지 날짜/교수명/코스 제목이 섞인 항목 제거, 비면 개념형 fallback으로 대체.
            ConceptFallbackProvider.Concept fb = ConceptFallbackProvider.forTopicAt(subject, i);
            String objective = sanitizeRequiredField(it.getObjective(), subject, fb.objective, noiseStats);
            java.util.List<String> tasks = sanitizeStrListHard(it.getTasks(), subject, fb.tasks, noiseStats);
            java.util.List<String> coreConcepts = sanitizeStrListSoft(it.getCoreConcepts(), subject, fb.coreConcepts, noiseStats);
            java.util.List<String> reviewQuestions = sanitizeStrListSoft(it.getReviewQuestions(), subject, fb.reviewQuestions, noiseStats);
            String checkpoint = sanitizeOptionalField(it.getCheckpoint(), subject, "", noiseStats);
            String deliverable = sanitizeOptionalField(it.getDeliverable(), subject, fb.deliverable, noiseStats);

            StringBuilder content = new StringBuilder();
            if (!objective.isBlank()) content.append("[오늘 목표] ").append(objective).append("\n\n");
            if (!tasks.isEmpty()) {
                content.append("[할 일]\n");
                for (int t = 0; t < tasks.size(); t++) content.append(t + 1).append(". ").append(tasks.get(t)).append("\n");
            }

            StringBuilder memo = new StringBuilder();
            if (!coreConcepts.isEmpty()) memo.append("핵심 개념: ").append(String.join(", ", coreConcepts)).append("\n");
            if (!reviewQuestions.isEmpty()) {
                memo.append("복습 질문:\n");
                for (String q : reviewQuestions) memo.append("- ").append(q).append("\n");
            }
            if (!checkpoint.isBlank()) memo.append("체크포인트: ").append(checkpoint).append("\n");
            if (!deliverable.isBlank()) memo.append("산출물: ").append(deliverable).append("\n");

            String targetTime = it.getTargetMinutes() != null && it.getTargetMinutes() > 0 ? (it.getTargetMinutes() + "분") : null;
            // week/day는 명시값 우선, 없으면 index 기반 계산(84개=12주×7일): index/7+1 주차, index%7+1 일차
            int weekNo = it.getWeek() != null ? it.getWeek() : (i / 7 + 1);
            int dayNo = it.getDayIndex() != null ? it.getDayIndex() : (i % 7 + 1);
            // topic: 정제된 제목 우선, 노이즈/비면 개념형 fallback 제목 사용(메타데이터를 제목으로 쓰지 않는다)
            String topic = (it.getTitle() != null && !LearningContentSanitizer.isNoise(it.getTitle(), subject))
                    ? LearningContentSanitizer.clean(it.getTitle())
                    : fb.title;
            // DB에 저장되는 title 자체를 "[로드맵 N주차 M일] topic" 형식으로 통일 (목록/상세/캘린더 공통)
            String roadmapTitle = buildRoadmapPlannerTitle(weekNo, dayNo, topic);

            Planner planner = Planner.builder()
                    .userId(userId)
                    .plannerType(PlannerType.ROADMAP)   // 로드맵 저장 경로는 프론트 요청과 무관하게 ROADMAP 강제
                    .title(roadmapTitle)
                    .year(date.getYear()).month(date.getMonthValue()).day(date.getDayOfMonth())
                    .plannerDate(date)
                    .term(weekNo + "주차")
                    .subject(subject)
                    .studyType("자료 기반 학습")
                    .priority("보통")
                    .goalTime(targetTime)
                    .content(content.toString().trim())
                    .tmi(memo.toString().trim())
                    .materialId(req.getMaterialId())
                    .sourceType(SOURCE_TYPE)
                    .sourceMaterialId(req.getMaterialId())
                    .sourceRoadmapId(req.getRoadmapId())
                    .build();
            plannerRepository.save(planner);
            created++;
        }

        boolean fallbackUsed = noiseStats[3] > 0;
        log.info("[planner:validation] materialId={} roadmapId={} created={} noiseCandidates={} cleaned={} rejected={} fallbackUsed={} reason={}",
                req.getMaterialId(), req.getRoadmapId(), created,
                noiseStats[0], noiseStats[1], noiseStats[2], fallbackUsed,
                fallbackUsed ? "metadata_noise" : "none");

        return PlannerDTO.FromRoadmapResponse.builder()
                .createdCount(created).duplicate(false).existingCount(existing)
                .message(created + "개의 플래너가 생성되었습니다.")
                .build();
    }

    // ── 로드맵→플래너 노이즈 정제 헬퍼 (stats: [0]=noiseCandidate,[1]=cleaned,[2]=rejected,[3]=fallbackUsed) ──
    private String sanitizeRequiredField(String raw, String course, String fallback, int[] st) {
        if (raw == null || raw.isBlank()) { st[3]++; return fallback; }
        if (LearningContentSanitizer.isNoise(raw, course)) { st[0]++; st[2]++; st[3]++; return fallback; }
        String c = LearningContentSanitizer.clean(raw);
        if (!c.equals(raw.trim())) st[1]++;
        return c;
    }

    private String sanitizeOptionalField(String raw, String course, String fallback, int[] st) {
        if (raw == null || raw.isBlank()) return "";
        if (LearningContentSanitizer.isNoise(raw, course)) {
            st[0]++; st[2]++;
            if (fallback != null && !fallback.isBlank()) st[3]++;
            return fallback == null ? "" : fallback;
        }
        String c = LearningContentSanitizer.clean(raw);
        if (!c.equals(raw.trim())) st[1]++;
        return c;
    }

    // tasks: 전부 비거나 노이즈로 제거되면 개념형 fallback 으로 채운다(핵심 학습 항목).
    private java.util.List<String> sanitizeStrListHard(java.util.List<String> raw, String course, java.util.List<String> fallback, int[] st) {
        java.util.List<String> in = raw != null ? raw : java.util.Collections.emptyList();
        int before = in.size();
        java.util.List<String> out = LearningContentSanitizer.cleanList(in, course);
        int dropped = before - out.size();
        if (dropped > 0) { st[0] += dropped; st[2] += dropped; }
        if (out.isEmpty()) { st[3]++; return new java.util.ArrayList<>(fallback); }
        return out;
    }

    // core_concepts/review_questions: 원래 비어 있으면 그대로 비움. 있던 항목이 전부 노이즈면 fallback.
    private java.util.List<String> sanitizeStrListSoft(java.util.List<String> raw, String course, java.util.List<String> fallback, int[] st) {
        if (raw == null || raw.isEmpty()) return new java.util.ArrayList<>();
        int before = raw.size();
        java.util.List<String> out = LearningContentSanitizer.cleanList(raw, course);
        int dropped = before - out.size();
        if (dropped > 0) { st[0] += dropped; st[2] += dropped; }
        if (out.isEmpty()) { st[3]++; return new java.util.ArrayList<>(fallback); }
        return out;
    }

    /**
     * 로드맵 기반 플래너 제목 생성 규칙 (단일 진실 지점).
     * 형식: "[로드맵 N주차 M일] topic"
     * - week/day가 있으면 반드시 사용하고, topic이 비면 "학습 계획"을 사용한다.
     * - 이미 "[로드맵" prefix가 있으면 중복으로 붙이지 않는다(prefix 중복 방지).
     * - topic 앞 "N일차:" 중복 접두어 제거, 40자 초과 시 정리.
     * 로드맵 기반(ROADMAP_AUTO) 플래너에만 사용 — 일반 플래너 제목은 절대 변경하지 않는다.
     */
    static String buildRoadmapPlannerTitle(Integer week, Integer day, String topic) {
        String t = (topic == null || topic.isBlank()) ? "학습 계획" : topic.trim();
        if (t.startsWith("[로드맵")) return t;            // 이미 prefix가 있으면 그대로 사용
        t = t.replaceFirst("^\\s*\\d+\\s*일차\\s*[:\\-–~]?\\s*", "").trim();
        if (t.isBlank()) t = "학습 계획";
        if (t.length() > 40) t = t.substring(0, 40).trim() + "…";
        if (week == null || day == null) {
            log.warn("[planner] 로드맵 플래너 week/day 확정 불가 — prefix 미적용. topic={}", t);
            return t;
        }
        return "[로드맵 " + week + "주차 " + day + "일] " + t;
    }

    @Transactional
    public PlannerDTO.Response update(Long userId, Long plannerId, PlannerDTO.Request req) {
        Planner planner = getOwned(userId, plannerId);
        // 수정 시 원천(plannerType)은 절대 바뀌지 않는다. NULL(미보정) 데이터만 추론값으로 고정한다.
        if (planner.getPlannerType() == null) planner.setPlannerType(resolvePlannerType(planner));
        planner.setTitle(req.getTitle() != null && !req.getTitle().isBlank() ? req.getTitle() : "공부 플래너");
        planner.setYear(req.getYear());
        planner.setMonth(req.getMonth());
        planner.setDay(req.getDay());
        planner.setDayOfWeek(req.getDayOfWeek());
        planner.setPlannerDate(req.getPlannerDate());
        planner.setGoalTime(req.getGoalTime());
        planner.setNetStudyTime(req.getNetStudyTime());
        planner.setWakeUpTime(req.getWakeUpTime());
        planner.setDDay(req.getDDay());
        planner.setStudyType(req.getStudyType());
        planner.setPriority(req.getPriority());
        planner.setTerm(req.getTerm());
        planner.setSubject(req.getSubject());
        planner.setContent(req.getContent());
        planner.setTmi(req.getTmi());
        planner.setTimeTableJson(req.getTimeTableJson());
        return toResponse(plannerRepository.save(planner), false);
    }

    public List<PlannerDTO.Response> getMyPlanners(Long userId) {
        return getMyPlanners(userId, null);
    }

    /**
     * 내 플래너 목록 조회. type 이 지정되면 해당 원천만 반환한다.
     * Repository 단순 필터가 아니라 resolver 기반으로 거른다 → backfill 미완료(plannerType NULL) 데이터도 누락되지 않는다.
     */
    public List<PlannerDTO.Response> getMyPlanners(Long userId, PlannerType type) {
        return plannerRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .filter(p -> type == null || resolvePlannerType(p) == type)
                .map(p -> toResponse(p, false))
                .collect(Collectors.toList());
    }

    public PlannerDTO.Response get(Long userId, Long plannerId) {
        return toResponse(getOwned(userId, plannerId), true);
    }

    @Transactional
    public void delete(Long userId, Long plannerId) {
        Planner planner = getOwned(userId, plannerId);
        cleanupAndDelete(planner);
    }

    /**
     * 자료 기반(ROADMAP_AUTO) 플래너 전체삭제.
     * 현재 화면에 표시 중인 plannerIds 만 삭제한다. 수동 플래너/주간일정(todos)/다른 유저 데이터는 절대 건드리지 않는다.
     * 기존 단일 삭제와 동일하게 hard delete + 연결 S3/Material 정리. @Transactional 로 일부 실패 시 전체 rollback.
     */
    @Transactional
    public PlannerDTO.BulkDeleteResponse bulkDelete(Long userId, PlannerDTO.BulkDeleteRequest req) {
        if (req == null) {
            return bulkFail("INVALID_DELETE_SCOPE", "삭제 범위가 올바르지 않습니다.");
        }

        // 1) 삭제 대상 타입 결정 — plannerType(주) 우선, 없으면 레거시 scope/sourceType("ROADMAP_AUTO")을 ROADMAP 으로 해석.
        PlannerType targetType = parsePlannerType(req.getPlannerType());
        if (targetType == null) {
            boolean legacyRoadmap = "VISIBLE_ROADMAP_AUTO".equals(req.getScope())
                    || "ROADMAP_AUTO".equals(req.getSourceType());
            if (legacyRoadmap) targetType = PlannerType.ROADMAP;
        }
        if (targetType == null) {
            return bulkFail("INVALID_DELETE_SCOPE", "삭제할 플래너 유형(plannerType)이 지정되지 않았습니다.");
        }

        java.util.List<Long> ids = req.getPlannerIds();
        if (ids == null || ids.isEmpty()) {
            // 삭제 대상 없음 → 명확한 empty 성공 응답
            return PlannerDTO.BulkDeleteResponse.builder()
                    .success(true).deletedCount(0).message("삭제할 플래너가 없습니다.").build();
        }
        java.util.List<Long> distinctIds = ids.stream().filter(java.util.Objects::nonNull).distinct().collect(Collectors.toList());

        // 2) 인증 사용자 소유 + 지정 id 만 조회 (다른 유저 데이터는 결과에 포함되지 않음)
        List<Planner> planners = plannerRepository.findByUserIdAndIdIn(userId, distinctIds);

        // 3) 요청한 모든 id 가 본인 소유인지 (개수 불일치 = 남의 것이거나 존재하지 않음)
        if (planners.size() != distinctIds.size()) {
            return bulkFail("INVALID_DELETE_SCOPE", "삭제 대상에 본인 소유가 아니거나 존재하지 않는 플래너가 포함되어 있습니다.");
        }

        // 4) 모든 대상이 현재 탭 타입과 동일한지 검증 — 다른 타입이 섞이면 전체 거부(두 타입 동시 삭제 절대 금지)
        for (Planner p : planners) {
            if (resolvePlannerType(p) != targetType) {
                String label = targetType == PlannerType.ROADMAP ? "로드맵" : "사용자";
                String other = targetType == PlannerType.ROADMAP ? "사용자" : "로드맵";
                return bulkFail("INVALID_DELETE_SCOPE",
                        label + " 플래너만 삭제할 수 있습니다. " + other + " 플래너가 포함되어 있습니다.");
            }
            // ROADMAP 일 때만, 지정된 material/roadmap 필터와의 일치를 추가 검증(선택)
            if (targetType == PlannerType.ROADMAP) {
                if (req.getMaterialId() != null
                        && !req.getMaterialId().equals(p.getSourceMaterialId())
                        && !req.getMaterialId().equals(p.getMaterialId())) {
                    return bulkFail("INVALID_DELETE_SCOPE", "삭제 대상이 자료(materialId) 조건과 일치하지 않습니다.");
                }
                if (req.getSourceRoadmapId() != null
                        && !req.getSourceRoadmapId().equals(p.getSourceRoadmapId())) {
                    return bulkFail("INVALID_DELETE_SCOPE", "삭제 대상이 로드맵(sourceRoadmapId) 조건과 일치하지 않습니다.");
                }
            }
        }

        // 5) 삭제 (단일 삭제와 동일 정책: hard delete + S3/Material 정리)
        int deleted = 0;
        for (Planner p : planners) {
            cleanupAndDelete(p);
            deleted++;
        }
        return PlannerDTO.BulkDeleteResponse.builder()
                .success(true).deletedCount(deleted)
                .message(deleted + "개의 플래너를 삭제했습니다.").build();
    }

    /**
     * 사용자가 체크박스로 선택한 플래너만 삭제(선택 삭제).
     * 전체삭제와 달리 ROADMAP_AUTO 제한이 없다(사용자가 명시적으로 고른 본인 소유 플래너).
     * 주간일정(todos)/다른 유저 데이터는 절대 건드리지 않는다. @Transactional 일부 실패 시 전체 rollback.
     */
    @Transactional
    public PlannerDTO.BulkDeleteResponse bulkDeleteSelected(Long userId, java.util.List<Long> plannerIds) {
        if (plannerIds == null || plannerIds.isEmpty()) {
            return PlannerDTO.BulkDeleteResponse.builder()
                    .success(true).deletedCount(0).message("선택한 플래너가 없습니다.").build();
        }
        java.util.List<Long> distinctIds = plannerIds.stream()
                .filter(java.util.Objects::nonNull).distinct().collect(Collectors.toList());

        // 인증 사용자 소유 + 선택 id 만 조회 (다른 유저 데이터는 결과에 포함되지 않음)
        List<Planner> planners = plannerRepository.findByUserIdAndIdIn(userId, distinctIds);
        if (planners.size() != distinctIds.size()) {
            return bulkFail("INVALID_DELETE_SCOPE", "본인 소유가 아니거나 존재하지 않는 플래너가 포함되어 있습니다.");
        }

        int deleted = 0;
        for (Planner p : planners) { cleanupAndDelete(p); deleted++; }
        return PlannerDTO.BulkDeleteResponse.builder()
                .success(true).deletedCount(deleted)
                .message(deleted + "개의 플래너를 삭제했습니다.").build();
    }

    private PlannerDTO.BulkDeleteResponse bulkFail(String code, String message) {
        return PlannerDTO.BulkDeleteResponse.builder()
                .success(false).errorCode(code).message(message).build();
    }

    /**
     * hard delete + 연결 S3 객체 / 자료보관함 Material 정리 (단일/전체삭제 공통).
     * 플래너 삭제 시 자료보관함에 보관된 그 플래너의 항목(PLANNER)도 함께 삭제한다.
     * 단, PDF/학습일지 등 일반 학습자료는 절대 삭제하지 않는다(materialType=PLANNER 로 한정).
     */
    private void cleanupAndDelete(Planner planner) {
        // 연결된 S3 다운로드 PDF 정리
        if (planner.getS3Key() != null) {
            try { s3Service.deleteFile(planner.getS3Key()); } catch (Exception e) { log.warn("플래너 S3 삭제 실패: {}", e.getMessage()); }
        }
        // 삭제 대상 자료보관함 항목을 합집합으로 모아 한 번씩만 삭제(이중삭제 방지).
        java.util.LinkedHashSet<Long> materialIds = new java.util.LinkedHashSet<>();
        // 1) 정방향 링크: planner.materialId 가 가리키는 항목. 단 PLANNER 타입일 때만 삭제 대상에 넣는다.
        //    (레거시 오염으로 materialId 가 출처 PDF 를 가리킬 수 있어, 타입 무관 삭제 시 원본 PDF/학습자료가 사라진다.)
        if (planner.getMaterialId() != null) {
            materialRepository.findById(planner.getMaterialId())
                    .filter(m -> m.getMaterialType() == MaterialType.PLANNER)
                    .ifPresent(m -> materialIds.add(m.getMaterialId()));
        }
        // 2) 역참조 링크(레거시/끊어진 링크 보강): material.plannerId == planner.id 인 PLANNER 자료만.
        //    PDF/학습일지 등 일반 학습자료는 타입 조건으로 절대 포함되지 않는다.
        for (Material m : materialRepository.findByPlannerIdAndMaterialType(planner.getId(), MaterialType.PLANNER)) {
            materialIds.add(m.getMaterialId());
        }
        if (!materialIds.isEmpty()) {
            materialRepository.findAllById(materialIds).forEach(materialRepository::delete);
            log.info("플래너 삭제 cascade: plannerId={} 연결 자료보관함 항목 {}건 정리", planner.getId(), materialIds.size());
        }
        plannerRepository.delete(planner);
    }

    public String getDownloadUrl(Long userId, Long plannerId) {
        Planner planner = getOwned(userId, plannerId);
        if (planner.getS3Key() == null) {
            throw new IllegalStateException("아직 PDF가 생성되지 않았습니다. 먼저 PDF를 생성해주세요.");
        }
        return s3Service.getPresignedUrl(planner.getS3Key(), planner.getTitle() + ".pdf");
    }

    /**
     * 플래너를 자료보관함에 "구조화(PLANNER) 자료"로 보관한다.
     * 플래너는 PDF 가 아니다 — PDF 변환/업로드/파일 메타(.pdf, application/pdf)를 일절 만들지 않고
     * plannerId 참조 + 스냅샷 JSON 으로 데이터 원형을 그대로 저장한다.
     * 기존 PDF 자료보관함과는 materialType=PLANNER 로 분리되어 PDF 파이프라인에 절대 들어가지 않는다.
     */
    @Transactional
    public PlannerDTO.Response archivePlanner(Long userId, Long plannerId) {
        Planner planner = getOwned(userId, plannerId);
        String snapshot = buildSnapshotJson(planner);

        Material material = planner.getMaterialId() != null
                ? materialRepository.findById(planner.getMaterialId()).orElse(null)
                : null;

        if (material == null) {
            material = Material.builder()
                    .userId(userId)
                    .title(planner.getTitle())
                    .materialType(MaterialType.PLANNER)
                    .plannerId(planner.getId())
                    .contentJson(snapshot)
                    .extractionStatus(ExtractionStatus.SUCCESS)
                    .uploadedAt(LocalDateTime.now())
                    .build();
        } else {
            // 재보관(편집 후 재저장) 시에도 타입을 PLANNER 로 고정하고, 과거 PDF 잔재 파일 메타를 모두 제거한다.
            material.setTitle(planner.getTitle());
            material.setMaterialType(MaterialType.PLANNER);
            material.setPlannerId(planner.getId());
            material.setContentJson(snapshot);
            material.setExtractionStatus(ExtractionStatus.SUCCESS);
            material.setOriginalFileName(null);
            material.setStoredFileName(null);
            material.setS3FileUrl(null);
            material.setFileSize(null);
        }
        Material savedMaterial = materialRepository.save(material);

        planner.setMaterialId(savedMaterial.getMaterialId());
        Planner saved = plannerRepository.save(planner);

        log.info("플래너 구조화 보관 완료(PDF 미사용). plannerId={}, materialId={}", plannerId, savedMaterial.getMaterialId());
        return toResponse(saved, false);
    }

    /**
     * "PDF 저장" 버튼 전용: 다운로드용 PDF 를 즉석 생성해 presigned URL 을 돌려준다.
     * 단, 자료보관함 항목은 항상 구조화(PLANNER) 자료로만 유지한다 — 이 PDF 는 다운로드 전용이며 Material 로 등록하지 않는다.
     */
    @Transactional
    public PlannerDTO.Response generatePdfDownload(Long userId, Long plannerId) {
        // 자료보관함에는 항상 구조화 PLANNER 로 보관(없으면 생성, 있으면 정정)
        archivePlanner(userId, plannerId);

        Planner planner = getOwned(userId, plannerId);
        byte[] pdf = buildPdf(planner);
        String s3Key = "planners/downloads/user_" + userId + "/" + plannerId + ".pdf";
        s3Service.uploadBytes(pdf, s3Key, "application/pdf");

        planner.setS3Key(s3Key); // 다운로드 전용 PDF (자료보관함 Material 아님)
        Planner saved = plannerRepository.save(planner);

        log.info("플래너 다운로드 PDF 생성 완료. plannerId={}, s3Key={}", plannerId, s3Key);
        return toResponse(saved, true);
    }

    /** 플래너를 PDF 로 변환하지 않고 데이터 원형으로 보관하기 위한 스냅샷 JSON. */
    private String buildSnapshotJson(Planner p) {
        try {
            java.util.Map<String, Object> m = new java.util.LinkedHashMap<>();
            m.put("plannerId", p.getId());
            m.put("plannerType", resolvePlannerType(p).name());   // ROADMAP_PLANNER / USER_PLANNER 구분 보존
            m.put("title", p.getTitle());
            m.put("subject", p.getSubject());
            m.put("term", p.getTerm());
            m.put("studyType", p.getStudyType());
            m.put("priority", p.getPriority());
            m.put("plannerDate", p.getPlannerDate() != null ? p.getPlannerDate().toString() : null);
            m.put("dDay", p.getDDay());
            m.put("goalTime", p.getGoalTime());
            m.put("netStudyTime", p.getNetStudyTime());
            m.put("content", p.getContent());
            m.put("tmi", p.getTmi());
            m.put("timeTableJson", p.getTimeTableJson());
            m.put("sourceType", p.getSourceType());
            m.put("sourceRoadmapId", p.getSourceRoadmapId());
            m.put("sourceMaterialId", p.getSourceMaterialId());
            m.put("createdAt", p.getCreatedAt() != null ? p.getCreatedAt().toString() : null);
            return objectMapper.writeValueAsString(m);
        } catch (Exception e) {
            log.warn("플래너 스냅샷 직렬화 실패 plannerId={}: {}", p.getId(), e.getMessage());
            return null;
        }
    }

    // ---------- helpers ----------

    /**
     * 플래너 원천 추론(단일 진실 지점). plannerType 이 있으면 그대로, 없으면(레거시 NULL) 메타데이터로 ROADMAP/USER 판정.
     * 응답/필터/삭제 어디서든 NULL 이 새어나가지 않게 한다.
     */
    PlannerType resolvePlannerType(Planner p) {
        if (p.getPlannerType() != null) return p.getPlannerType();
        // 자동 생성(로드맵/복습/소크라테스 등 sourceType 보유)·로드맵 연결은 ROADMAP, 순수 수동 작성만 USER.
        if (p.getSourceType() != null || p.getSourceRoadmapId() != null) {
            return PlannerType.ROADMAP;
        }
        return PlannerType.USER;
    }

    /** 요청 문자열("ROADMAP"/"USER", 대소문자 무관)을 enum 으로. 비거나 알 수 없으면 null. */
    private PlannerType parsePlannerType(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try { return PlannerType.valueOf(raw.trim().toUpperCase()); }
        catch (IllegalArgumentException e) { return null; }
    }

    private static final java.util.regex.Pattern ROADMAP_WD =
            java.util.regex.Pattern.compile("\\[\\s*로드맵\\s*(\\d+)\\s*주차\\s*(\\d+)\\s*일\\s*\\]");

    /** 로드맵 플래너 제목("[로드맵 N주차 M일] ...")에서 [week, day] 추출. 없으면 null 반환. */
    private Integer[] parseRoadmapWeekDay(String title) {
        if (title == null) return null;
        java.util.regex.Matcher m = ROADMAP_WD.matcher(title);
        if (!m.find()) return null;
        try { return new Integer[]{ Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)) }; }
        catch (NumberFormatException e) { return null; }
    }

    private Planner getOwned(Long userId, Long plannerId) {
        Planner planner = plannerRepository.findById(plannerId)
                .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다. id=" + plannerId));
        if (!planner.getUserId().equals(userId)) {
            throw new SecurityException("본인의 플래너만 접근할 수 있습니다.");
        }
        return planner;
    }

    private PlannerDTO.Response toResponse(Planner p, boolean withUrl) {
        String url = null;
        if (withUrl && p.getS3Key() != null) {
            try { url = s3Service.getPresignedUrl(p.getS3Key(), p.getTitle() + ".pdf"); }
            catch (Exception e) { log.warn("플래너 presigned URL 발급 실패 id={}: {}", p.getId(), e.getMessage()); }
        }
        Integer[] wd = parseRoadmapWeekDay(p.getTitle());
        return PlannerDTO.Response.builder()
                .id(p.getId()).userId(p.getUserId()).title(p.getTitle())
                .plannerType(resolvePlannerType(p).name())
                .roadmapWeek(wd != null ? wd[0] : null)
                .roadmapDay(wd != null ? wd[1] : null)
                .year(p.getYear()).month(p.getMonth()).day(p.getDay())
                .dayOfWeek(p.getDayOfWeek()).plannerDate(p.getPlannerDate())
                .goalTime(p.getGoalTime()).netStudyTime(p.getNetStudyTime())
                .wakeUpTime(p.getWakeUpTime()).dDay(p.getDDay())
                .studyType(p.getStudyType()).priority(p.getPriority()).term(p.getTerm())
                .subject(p.getSubject()).content(p.getContent()).tmi(p.getTmi())
                .timeTableJson(p.getTimeTableJson())
                .s3Key(p.getS3Key()).materialId(p.getMaterialId())
                .sourceType(p.getSourceType())
                .sourceMaterialId(p.getSourceMaterialId())
                .sourceRoadmapId(p.getSourceRoadmapId())
                .downloadUrl(url)
                .createdAt(p.getCreatedAt()).updatedAt(p.getUpdatedAt())
                .build();
    }

    private String sanitize(String s) {
        if (s == null || s.isBlank()) return "planner";
        return s.replaceAll("[\\\\/:*?\"<>|]", "_").trim();
    }

    private static synchronized byte[] fontBytes() {
        if (cachedFont == null) {
            try (InputStream is = PlannerService.class.getResourceAsStream("/fonts/NanumGothic.ttf")) {
                if (is == null) throw new IllegalStateException("NanumGothic.ttf 폰트를 찾을 수 없습니다.");
                cachedFont = is.readAllBytes();
            } catch (Exception e) {
                throw new RuntimeException("한글 폰트 로딩 실패", e);
            }
        }
        return cachedFont;
    }

    private Font font(float size, int style, Color color) {
        try {
            BaseFont base = BaseFont.createFont("NanumGothic.ttf", BaseFont.IDENTITY_H, BaseFont.EMBEDDED,
                    BaseFont.CACHED, fontBytes(), null);
            Font f = new Font(base, size, style);
            if (color != null) f.setColor(color);
            return f;
        } catch (Exception e) {
            throw new RuntimeException("한글 폰트 생성 실패", e);
        }
    }

    /** A4 세로 플래너 PDF 생성 (한글 임베드, 표 레이아웃). */
    byte[] buildPdf(Planner p) {
        try (ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            Document doc = new Document(PageSize.A4, 36, 36, 40, 40);
            PdfWriter.getInstance(doc, baos);
            doc.open();

            // 제목
            Paragraph title = new Paragraph(p.getTitle() != null ? p.getTitle() : "공부 플래너", font(20, Font.BOLD, GREEN_DARK));
            title.setSpacingAfter(4);
            doc.add(title);

            String dateLine = String.format("%s년 %s월 %s일 %s",
                    nz(p.getYear()), nz(p.getMonth()), nz(p.getDay()), p.getDayOfWeek() != null ? "(" + p.getDayOfWeek() + ")" : "");
            if (p.getTerm() != null && !p.getTerm().isBlank()) {
                dateLine = dateLine.trim() + "  ·  " + p.getTerm();
            }
            Paragraph dateP = new Paragraph(dateLine.trim(), font(11, Font.NORMAL, new Color(0x4B, 0x55, 0x63)));
            dateP.setSpacingAfter(12);
            doc.add(dateP);

            // 상단 정보 표: 학습 유형/우선순위/목표 학습 시간/마감일·시험일
            PdfPTable info = new PdfPTable(4);
            info.setWidthPercentage(100);
            info.setSpacingAfter(14);
            addInfoCell(info, "학습 유형", str(p.getStudyType()));
            addInfoCell(info, "우선순위", str(p.getPriority()));
            addInfoCell(info, "목표 학습 시간", str(p.getGoalTime()));
            addInfoCell(info, "마감일/시험일", str(p.getDDay()));
            doc.add(info);

            // 과목명 / 학습 목표
            PdfPTable sc = new PdfPTable(new float[]{1f, 3f});
            sc.setWidthPercentage(100);
            sc.setSpacingAfter(14);
            sc.addCell(labelCell("과목명"));
            sc.addCell(valueCell(str(p.getSubject())));
            sc.addCell(labelCell("학습 목표"));
            sc.addCell(valueCell(str(p.getContent())));
            doc.add(sc);

            // 10분 단위 시간 체크표 (6~23시)
            Paragraph ttTitle = new Paragraph("시간 체크표 (10분 단위)", font(12, Font.BOLD, GREEN_DARK));
            ttTitle.setSpacingAfter(6);
            doc.add(ttTitle);
            doc.add(buildTimeTable(p.getTimeTableJson()));

            // 세부 할 일 / 메모
            Paragraph tmiTitle = new Paragraph("세부 할 일 / 메모", font(12, Font.BOLD, GREEN_DARK));
            tmiTitle.setSpacingBefore(14);
            tmiTitle.setSpacingAfter(6);
            doc.add(tmiTitle);
            PdfPTable tmi = new PdfPTable(1);
            tmi.setWidthPercentage(100);
            PdfPCell tmiCell = new PdfPCell(new Phrase(str(p.getTmi()), font(11, Font.NORMAL, Color.BLACK)));
            tmiCell.setMinimumHeight(70);
            tmiCell.setPadding(8);
            tmiCell.setBorderColor(GREY_LINE);
            tmi.addCell(tmiCell);
            doc.add(tmi);

            doc.close();
            return baos.toByteArray();
        } catch (Exception e) {
            throw new RuntimeException("플래너 PDF 생성에 실패했습니다.", e);
        }
    }

    private PdfPTable buildTimeTable(String json) {
        // columns: 시 + 00,10,20,30,40,50
        PdfPTable table = new PdfPTable(7);
        try { table.setWidths(new float[]{1.2f, 1f, 1f, 1f, 1f, 1f, 1f}); } catch (Exception ignored) {}
        table.setWidthPercentage(100);

        String[] headers = {"시", "00", "10", "20", "30", "40", "50"};
        for (String h : headers) {
            PdfPCell c = new PdfPCell(new Phrase(h, font(9, Font.BOLD, GREEN_DARK)));
            c.setBackgroundColor(GREEN_LIGHT);
            c.setBorderColor(GREEN_BORDER);
            c.setHorizontalAlignment(Element.ALIGN_CENTER);
            c.setPadding(3);
            table.addCell(c);
        }

        JsonNode node = null;
        if (json != null && !json.isBlank()) {
            try { node = objectMapper.readTree(json); } catch (Exception e) { log.warn("플래너 시간표 JSON 파싱 실패: {}", e.getMessage()); }
        }

        for (int hour = 6; hour <= 23; hour++) {
            PdfPCell hc = new PdfPCell(new Phrase(String.format("%02d", hour), font(9, Font.NORMAL, Color.BLACK)));
            hc.setHorizontalAlignment(Element.ALIGN_CENTER);
            hc.setBorderColor(GREY_LINE);
            hc.setPadding(3);
            table.addCell(hc);

            for (int slot = 0; slot < 6; slot++) {
                boolean checked = isChecked(node, hour, slot);
                PdfPCell c = new PdfPCell(new Phrase(checked ? "■" : "", font(9, Font.NORMAL, GREEN_DARK)));
                c.setHorizontalAlignment(Element.ALIGN_CENTER);
                c.setBorderColor(GREY_LINE);
                if (checked) c.setBackgroundColor(GREEN_LIGHT);
                c.setMinimumHeight(14);
                c.setPadding(2);
                table.addCell(c);
            }
        }
        return table;
    }

    private boolean isChecked(JsonNode node, int hour, int slot) {
        if (node == null) return false;
        JsonNode row = node.get(String.valueOf(hour));
        if (row == null || !row.isArray() || slot >= row.size()) return false;
        JsonNode v = row.get(slot);
        return v != null && (v.asBoolean(false) || v.asInt(0) == 1);
    }

    private void addInfoCell(PdfPTable table, String label, String value) {
        PdfPCell c = new PdfPCell();
        c.setBorderColor(GREEN_BORDER);
        c.setPadding(8);
        Paragraph l = new Paragraph(label, font(9, Font.BOLD, GREEN_DARK));
        Paragraph v = new Paragraph(value, font(12, Font.BOLD, Color.BLACK));
        c.addElement(l);
        c.addElement(v);
        table.addCell(c);
    }

    private PdfPCell labelCell(String text) {
        PdfPCell c = new PdfPCell(new Phrase(text, font(10, Font.BOLD, GREEN_DARK)));
        c.setBackgroundColor(GREEN_LIGHT);
        c.setBorderColor(GREEN_BORDER);
        c.setPadding(8);
        c.setHorizontalAlignment(Element.ALIGN_CENTER);
        c.setVerticalAlignment(Element.ALIGN_MIDDLE);
        return c;
    }

    private PdfPCell valueCell(String text) {
        PdfPCell c = new PdfPCell(new Phrase(text, font(11, Font.NORMAL, Color.BLACK)));
        c.setBorderColor(GREY_LINE);
        c.setPadding(8);
        c.setMinimumHeight(28);
        return c;
    }

    private String str(String s) { return s == null ? "" : s; }
    private String nz(Integer i) { return i == null ? "____" : String.valueOf(i); }
}
