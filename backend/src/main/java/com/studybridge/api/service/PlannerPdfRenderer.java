package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lowagie.text.Chunk;
import com.lowagie.text.Document;
import com.lowagie.text.Element;
import com.lowagie.text.Font;
import com.lowagie.text.PageSize;
import com.lowagie.text.Paragraph;
import com.lowagie.text.SplitCharacter;
import com.lowagie.text.pdf.BaseFont;
import com.lowagie.text.pdf.PdfChunk;
import com.lowagie.text.pdf.PdfPCell;
import com.lowagie.text.pdf.PdfPTable;
import com.lowagie.text.pdf.PdfWriter;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.util.LearningDayNormalizer.DayContent;
import lombok.extern.slf4j.Slf4j;

import java.awt.Color;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * 플래너 A4 PDF 렌더러(OpenPDF, 한글 임베드).
 *
 * <p>레이아웃 원칙
 * <ul>
 *   <li>모든 텍스트 블록은 흐름 레이아웃(Paragraph / 1열 표)이다. 고정 Y 좌표·고정 높이를 쓰지 않으므로
 *       내용 높이에 따라 다음 영역이 자연히 내려가고, 한 페이지를 넘으면 다음 페이지로 이어진다(표 행 분할 허용).</li>
 *   <li>줄바꿈은 실제 렌더링 폭 기준으로 공백/어절 경계에서만 일어난다({@link #WORD_BOUNDARY}). OpenPDF 기본값은
 *       한글 음절마다 줄바꿈을 허용해 단어 중간이 잘리므로 이를 끈다. 폭보다 긴 단일 어절만 폭에서 안전하게 나뉜다.</li>
 *   <li>문자열을 글자 수 기준으로 자르거나 "…"로 줄이지 않는다. 문장은 전부 출력된다.</li>
 *   <li>로드맵 플래너는 정규화된 {@link DayContent}(오늘 목표 / 할 일 / 핵심 개념 / 복습 질문 / 체크포인트 / 산출물)를
 *       우선 사용하고, 자유 입력 플래너는 content/tmi 원문을 줄 단위로 출력한다.</li>
 * </ul>
 */
@Slf4j
final class PlannerPdfRenderer {

    static final Color GREEN_DARK = new Color(0x15, 0x80, 0x3D);
    static final Color GREEN_LIGHT = new Color(0xEC, 0xFD, 0xF3);
    static final Color GREEN_BORDER = new Color(0xBB, 0xF7, 0xD0);
    static final Color GREY_LINE = new Color(0xD1, 0xD5, 0xDB);
    static final Color GREY_TEXT = new Color(0x4B, 0x55, 0x63);

    private static final float BODY_SIZE = 10.5f;
    private static final float LEADING = 1.55f;

    /** 공백·하이픈·슬래시 뒤에서만 줄을 나눈다(한글 음절 단위 분리 금지). */
    static final SplitCharacter WORD_BOUNDARY = new SplitCharacter() {
        @Override
        public boolean isSplitCharacter(int start, int current, int end, char[] cc, PdfChunk[] ck) {
            char c = ck == null ? cc[current] : (char) ck[Math.min(current, ck.length - 1)].getUnicodeEquivalent(cc[current]);
            return c <= ' ' || c == '-' || c == '‐' || c == '/' || c == '\u200B';
        }
    };

    private static volatile BaseFont baseFont;
    private final ObjectMapper json;

    PlannerPdfRenderer(ObjectMapper json) { this.json = json; }

    byte[] render(Planner p, DayContent day) {
        try (ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            Document doc = new Document(PageSize.A4, 40, 40, 44, 44);
            PdfWriter.getInstance(doc, baos);
            doc.open();

            Paragraph title = para(p.getTitle() != null && !p.getTitle().isBlank() ? p.getTitle() : "공부 플래너", font(19, Font.BOLD, GREEN_DARK));
            title.setSpacingAfter(4);
            doc.add(title);

            String dateLine = String.format("%s년 %s월 %s일 %s", nz(p.getYear()), nz(p.getMonth()), nz(p.getDay()),
                    p.getDayOfWeek() != null ? "(" + p.getDayOfWeek() + ")" : "").trim();
            if (p.getTerm() != null && !p.getTerm().isBlank()) dateLine = dateLine + "  ·  " + p.getTerm();
            Paragraph dateP = para(dateLine, font(10.5f, Font.NORMAL, GREY_TEXT));
            dateP.setSpacingAfter(12);
            doc.add(dateP);

            PdfPTable info = new PdfPTable(4);
            info.setWidthPercentage(100);
            info.setSpacingAfter(12);
            addInfoCell(info, "학습 유형", str(p.getStudyType()));
            addInfoCell(info, "우선순위", str(p.getPriority()));
            addInfoCell(info, "목표 학습 시간", str(p.getGoalTime()));
            addInfoCell(info, "마감일/시험일", str(p.getDDay()));
            doc.add(info);

            if (p.getSubject() != null && !p.getSubject().isBlank()) {
                doc.add(section("과목명", List.of(p.getSubject())));
            }

            if (day != null) {
                if (!day.objective().isBlank()) doc.add(section("오늘 목표", List.of(day.objective())));
                if (!day.tasks().isEmpty()) doc.add(listSection("할 일", day.tasks(), true));
                if (!day.concepts().isEmpty()) doc.add(section("핵심 개념", List.of(String.join(", ", day.concepts()))));
                if (!day.reviewQuestions().isEmpty()) doc.add(listSection("복습 질문", day.reviewQuestions(), false));
                if (!day.checkpoint().isBlank()) doc.add(section("체크포인트", List.of(day.checkpoint())));
                if (!day.deliverable().isBlank()) doc.add(section("산출물", List.of(day.deliverable())));
            } else {
                List<String> goal = lines(p.getContent());
                if (!goal.isEmpty()) doc.add(section("학습 목표", goal));
                List<String> memo = lines(p.getTmi());
                if (!memo.isEmpty()) doc.add(section("세부 할 일 / 메모", memo));
            }

            Paragraph ttTitle = heading("시간 체크표 (10분 단위)");
            ttTitle.setSpacingBefore(6);
            doc.add(ttTitle);
            doc.add(buildTimeTable(p.getTimeTableJson()));

            doc.close();
            return baos.toByteArray();
        } catch (Exception e) {
            throw new RuntimeException("플래너 PDF 생성에 실패했습니다.", e);
        }
    }

    // ---------------- 블록 ----------------

    /** 제목 + 1열 표(본문 줄 단위 Paragraph). 높이는 내용에 따라 결정되고 페이지를 넘으면 행이 분할되어 이어진다. */
    private PdfPTable section(String label, List<String> textLines) {
        PdfPCell cell = bodyCell();
        for (String line : textLines) {
            for (String l : lines(line)) cell.addElement(body(l));
        }
        return wrap(label, cell);
    }

    /** 번호/불릿 목록. 각 항목은 내어쓰기(hanging indent) 로 접힌 줄이 번호 아래로 들어가지 않게 한다. */
    private PdfPTable listSection(String label, List<String> items, boolean numbered) {
        PdfPCell cell = bodyCell();
        for (int i = 0; i < items.size(); i++) {
            String prefix = numbered ? (i + 1) + ". " : "- ";
            Paragraph para = body(prefix + items.get(i));
            para.setIndentationLeft(numbered ? 16 : 12);
            para.setFirstLineIndent(numbered ? -16 : -12);
            para.setSpacingAfter(2);
            cell.addElement(para);
        }
        return wrap(label, cell);
    }

    private PdfPTable wrap(String label, PdfPCell cell) {
        PdfPTable table = new PdfPTable(1);
        table.setWidthPercentage(100);
        table.setSpacingBefore(4);
        table.setSpacingAfter(10);
        table.setSplitRows(true);
        table.setSplitLate(false);          // 행이 페이지에 안 들어가면 그 자리에서 나눠 다음 페이지로 잇는다.
        PdfPCell head = new PdfPCell();
        head.setBorder(0);
        head.setPadding(0);
        head.setPaddingBottom(4);
        head.addElement(heading(label));
        table.addCell(head);
        table.addCell(cell);
        return table;
    }

    private PdfPCell bodyCell() {
        PdfPCell cell = new PdfPCell();
        cell.setBorderColor(GREY_LINE);
        cell.setPadding(9);
        cell.setPaddingBottom(11);
        cell.setUseAscender(true);
        cell.setUseDescender(true);
        return cell;
    }

    private Paragraph heading(String text) {
        Paragraph h = para(text, font(12, Font.BOLD, GREEN_DARK));
        h.setSpacingAfter(4);
        return h;
    }

    private Paragraph body(String text) {
        Paragraph para = para(text, font(BODY_SIZE, Font.NORMAL, Color.BLACK));
        para.setLeading(BODY_SIZE * LEADING);
        return para;
    }

    /** 어절 경계 줄바꿈 Chunk 로 이루어진 Paragraph. 문자열은 자르지 않는다. */
    static Paragraph para(String text, Font font) {
        Chunk chunk = new Chunk(text == null ? "" : text, font);
        chunk.setSplitCharacter(WORD_BOUNDARY);
        Paragraph p = new Paragraph(chunk);
        p.setLeading(font.getSize() * LEADING);
        return p;
    }

    static List<String> lines(String s) {
        List<String> out = new ArrayList<>();
        if (s == null) return out;
        for (String l : s.split("\\R")) if (!l.isBlank()) out.add(l.trim());
        return out;
    }

    // ---------------- 시간 체크표 ----------------

    private PdfPTable buildTimeTable(String timeTableJson) {
        PdfPTable table = new PdfPTable(7);
        try { table.setWidths(new float[]{1.2f, 1f, 1f, 1f, 1f, 1f, 1f}); } catch (Exception ignored) {}
        table.setWidthPercentage(100);
        table.setKeepTogether(true);
        String[] headers = {"시", "00", "10", "20", "30", "40", "50"};
        for (String h : headers) {
            PdfPCell c = new PdfPCell(para(h, font(9, Font.BOLD, GREEN_DARK)));
            c.setBackgroundColor(GREEN_LIGHT);
            c.setBorderColor(GREEN_BORDER);
            c.setHorizontalAlignment(Element.ALIGN_CENTER);
            c.setPadding(3);
            table.addCell(c);
        }
        JsonNode node = null;
        if (timeTableJson != null && !timeTableJson.isBlank()) {
            try { node = json.readTree(timeTableJson); } catch (Exception e) { log.warn("플래너 시간표 JSON 파싱 실패: {}", e.getMessage()); }
        }
        for (int hour = 6; hour <= 23; hour++) {
            PdfPCell hc = new PdfPCell(para(String.format("%02d", hour), font(9, Font.NORMAL, Color.BLACK)));
            hc.setHorizontalAlignment(Element.ALIGN_CENTER);
            hc.setBorderColor(GREY_LINE);
            hc.setPadding(3);
            table.addCell(hc);
            for (int slot = 0; slot < 6; slot++) {
                boolean checked = isChecked(node, hour, slot);
                PdfPCell c = new PdfPCell(para(checked ? "■" : "", font(9, Font.NORMAL, GREEN_DARK)));
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
        c.addElement(para(label, font(9, Font.BOLD, GREEN_DARK)));
        c.addElement(para(value, font(11.5f, Font.BOLD, Color.BLACK)));
        table.addCell(c);
    }

    // ---------------- 폰트 ----------------

    static Font font(float size, int style, Color color) {
        Font f = new Font(baseFont(), size, style);
        if (color != null) f.setColor(color);
        return f;
    }

    private static BaseFont baseFont() {
        BaseFont bf = baseFont;
        if (bf == null) {
            synchronized (PlannerPdfRenderer.class) {
                bf = baseFont;
                if (bf == null) {
                    try (InputStream is = PlannerPdfRenderer.class.getResourceAsStream("/fonts/NanumGothic.ttf")) {
                        if (is == null) throw new IllegalStateException("NanumGothic.ttf 폰트를 찾을 수 없습니다.");
                        bf = BaseFont.createFont("NanumGothic.ttf", BaseFont.IDENTITY_H, BaseFont.EMBEDDED, BaseFont.CACHED, is.readAllBytes(), null);
                    } catch (Exception e) {
                        throw new RuntimeException("한글 폰트 로딩 실패", e);
                    }
                    baseFont = bf;
                }
            }
        }
        return bf;
    }

    private static String str(String s) { return s == null ? "" : s; }
    private static String nz(Integer i) { return i == null ? "____" : String.valueOf(i); }
}
