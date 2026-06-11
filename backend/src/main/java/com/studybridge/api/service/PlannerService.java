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
                .subject(req.getSubject())
                .content(req.getContent())
                .tmi(req.getTmi())
                .timeTableJson(req.getTimeTableJson())
                .build();
        return toResponse(plannerRepository.save(planner), false);
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
                .subject(p.getSubject()).content(p.getContent()).tmi(p.getTmi())
                .timeTableJson(p.getTimeTableJson())
                .s3Key(p.getS3Key()).materialId(p.getMaterialId())
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
            Paragraph dateP = new Paragraph(dateLine.trim(), font(11, Font.NORMAL, new Color(0x4B, 0x55, 0x63)));
            dateP.setSpacingAfter(12);
            doc.add(dateP);

            // 상단 정보 표: 목표/순공부/기상/디데이
            PdfPTable info = new PdfPTable(4);
            info.setWidthPercentage(100);
            info.setSpacingAfter(14);
            addInfoCell(info, "목표 시간", str(p.getGoalTime()));
            addInfoCell(info, "순공부 시간", str(p.getNetStudyTime()));
            addInfoCell(info, "기상 시간", str(p.getWakeUpTime()));
            addInfoCell(info, "디데이", str(p.getDDay()));
            doc.add(info);

            // 과목 / 내용
            PdfPTable sc = new PdfPTable(new float[]{1f, 3f});
            sc.setWidthPercentage(100);
            sc.setSpacingAfter(14);
            sc.addCell(labelCell("과목"));
            sc.addCell(valueCell(str(p.getSubject())));
            sc.addCell(labelCell("내용"));
            sc.addCell(valueCell(str(p.getContent())));
            doc.add(sc);

            // 10분 단위 시간 체크표 (6~23시)
            Paragraph ttTitle = new Paragraph("시간 체크표 (10분 단위)", font(12, Font.BOLD, GREEN_DARK));
            ttTitle.setSpacingAfter(6);
            doc.add(ttTitle);
            doc.add(buildTimeTable(p.getTimeTableJson()));

            // 오늘의 TMI
            Paragraph tmiTitle = new Paragraph("오늘의 TMI", font(12, Font.BOLD, GREEN_DARK));
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
