package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
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
        Planner planner = Planner.builder()
                .userId(userId)
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
        for (int i = 0; i < items.size(); i++) {
            PlannerDTO.RoadmapItem it = items.get(i);
            java.time.LocalDate date = start.plusDays(i);
            java.util.List<String> tasks = it.getTasks() != null ? it.getTasks() : java.util.Collections.emptyList();

            StringBuilder content = new StringBuilder();
            if (it.getObjective() != null && !it.getObjective().isBlank()) content.append("[오늘 목표] ").append(it.getObjective()).append("\n\n");
            if (!tasks.isEmpty()) {
                content.append("[할 일]\n");
                for (int t = 0; t < tasks.size(); t++) content.append(t + 1).append(". ").append(tasks.get(t)).append("\n");
            }

            StringBuilder memo = new StringBuilder();
            if (it.getCoreConcepts() != null && !it.getCoreConcepts().isEmpty()) memo.append("핵심 개념: ").append(String.join(", ", it.getCoreConcepts())).append("\n");
            if (it.getReviewQuestions() != null && !it.getReviewQuestions().isEmpty()) {
                memo.append("복습 질문:\n");
                for (String q : it.getReviewQuestions()) memo.append("- ").append(q).append("\n");
            }
            if (it.getCheckpoint() != null && !it.getCheckpoint().isBlank()) memo.append("체크포인트: ").append(it.getCheckpoint()).append("\n");
            if (it.getDeliverable() != null && !it.getDeliverable().isBlank()) memo.append("산출물: ").append(it.getDeliverable()).append("\n");

            String targetTime = it.getTargetMinutes() != null && it.getTargetMinutes() > 0 ? (it.getTargetMinutes() + "분") : null;
            int weekNo = it.getWeek() != null ? it.getWeek() : (i / 7 + 1);

            Planner planner = Planner.builder()
                    .userId(userId)
                    .title(it.getTitle() != null && !it.getTitle().isBlank() ? it.getTitle() : ((it.getDayIndex() != null ? it.getDayIndex() : i + 1) + "일차 학습"))
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

        return PlannerDTO.FromRoadmapResponse.builder()
                .createdCount(created).duplicate(false).existingCount(existing)
                .message(created + "개의 플래너가 생성되었습니다.")
                .build();
    }

    @Transactional
    public PlannerDTO.Response update(Long userId, Long plannerId, PlannerDTO.Request req) {
        Planner planner = getOwned(userId, plannerId);
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
        return plannerRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
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
        final String AUTO = "ROADMAP_AUTO";

        // 1) scope 검증
        if (req == null || !"VISIBLE_ROADMAP_AUTO".equals(req.getScope())) {
            return bulkFail("INVALID_DELETE_SCOPE", "삭제 범위가 올바르지 않습니다.");
        }
        // 2) sourceType 검증 (지정 시 ROADMAP_AUTO 만 허용)
        if (req.getSourceType() != null && !AUTO.equals(req.getSourceType())) {
            return bulkFail("INVALID_DELETE_SCOPE", "삭제 범위가 올바르지 않습니다.");
        }

        java.util.List<Long> ids = req.getPlannerIds();
        if (ids == null || ids.isEmpty()) {
            // 삭제 대상 없음 → 명확한 empty 성공 응답
            return PlannerDTO.BulkDeleteResponse.builder()
                    .success(true).deletedCount(0).message("삭제할 플래너가 없습니다.").build();
        }
        java.util.List<Long> distinctIds = ids.stream().filter(java.util.Objects::nonNull).distinct().collect(Collectors.toList());

        // 3) 인증 사용자 소유 + 지정 id 만 조회 (다른 유저 데이터는 결과에 포함되지 않음)
        List<Planner> planners = plannerRepository.findByUserIdAndIdIn(userId, distinctIds);

        // 4) 요청한 모든 id 가 본인 소유인지 (개수 불일치 = 남의 것이거나 존재하지 않음)
        if (planners.size() != distinctIds.size()) {
            return bulkFail("INVALID_DELETE_SCOPE", "삭제 대상에 본인 소유가 아니거나 존재하지 않는 플래너가 포함되어 있습니다.");
        }

        // 5) 모든 대상이 ROADMAP_AUTO 인지 + (지정 시) material/roadmap 조건 일치 검증
        for (Planner p : planners) {
            if (!AUTO.equals(p.getSourceType())) {
                // 수동(MANUAL/null) 플래너가 섞이면 전체 거부 → 수동 플래너는 절대 삭제되지 않음
                return bulkFail("INVALID_DELETE_SCOPE", "자료 기반 플래너만 삭제할 수 있습니다. 수동으로 작성한 플래너가 포함되어 있습니다.");
            }
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

        // 6) 삭제 (단일 삭제와 동일 정책: hard delete + S3/Material 정리)
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

    /** hard delete + 연결 S3 객체 / 자료보관함 Material 정리 (단일/전체삭제 공통). */
    private void cleanupAndDelete(Planner planner) {
        // 연결된 자료보관함 PDF(Material)와 S3 객체도 함께 정리
        if (planner.getS3Key() != null) {
            try { s3Service.deleteFile(planner.getS3Key()); } catch (Exception e) { log.warn("플래너 S3 삭제 실패: {}", e.getMessage()); }
        }
        if (planner.getMaterialId() != null) {
            materialRepository.findById(planner.getMaterialId()).ifPresent(materialRepository::delete);
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
     * 플래너 PDF 생성 → S3 저장 → 자료보관함(Material, type=PLANNER) 연결.
     * (PDF 저장 / 자료보관함 저장 두 동작 모두 이 메서드를 사용)
     */
    @Transactional
    public PlannerDTO.Response generateAndArchive(Long userId, Long plannerId) {
        Planner planner = getOwned(userId, plannerId);

        byte[] pdf = buildPdf(planner);
        String s3Key = "planners/user_" + userId + "/" + plannerId + ".pdf";
        s3Service.uploadBytes(pdf, s3Key, "application/pdf");

        String fileName = sanitize(planner.getTitle()) + ".pdf";

        // 자료보관함 Material 생성/갱신 (type=PLANNER) — 기존 자료보관함 목록과 충돌하지 않게 type 으로 구분
        Material material;
        if (planner.getMaterialId() != null) {
            material = materialRepository.findById(planner.getMaterialId()).orElse(null);
        } else {
            material = null;
        }
        if (material == null) {
            material = Material.builder()
                    .userId(userId)
                    .title(planner.getTitle())
                    .materialType(MaterialType.PLANNER)
                    .originalFileName(fileName)
                    .storedFileName(s3Key)
                    .s3FileUrl(s3Key)
                    .fileSize((long) pdf.length)
                    .extractionStatus(ExtractionStatus.SUCCESS)
                    .uploadedAt(LocalDateTime.now())
                    .build();
        } else {
            material.setTitle(planner.getTitle());
            material.setOriginalFileName(fileName);
            material.setStoredFileName(s3Key);
            material.setS3FileUrl(s3Key);
            material.setFileSize((long) pdf.length);
        }
        Material savedMaterial = materialRepository.save(material);

        planner.setS3Key(s3Key);
        planner.setMaterialId(savedMaterial.getMaterialId());
        Planner saved = plannerRepository.save(planner);

        log.info("플래너 PDF 생성/보관 완료. plannerId={}, materialId={}, s3Key={}", plannerId, savedMaterial.getMaterialId(), s3Key);
        return toResponse(saved, true);
    }

    // ---------- helpers ----------

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
        return PlannerDTO.Response.builder()
                .id(p.getId()).userId(p.getUserId()).title(p.getTitle())
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
