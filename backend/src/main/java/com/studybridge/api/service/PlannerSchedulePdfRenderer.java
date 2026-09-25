package com.studybridge.api.service;

import com.studybridge.api.dto.PlannerSemanticDTO.Schedule;
import com.studybridge.api.dto.PlannerSemanticDTO.ScheduleRow;
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
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.awt.Color;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/**
 * 하루 학습 시간표 PDF 렌더러.
 * S3 템플릿(planner/templates/daily_schedule_v1.pdf)의 디자인 정체성(초록 상단 제목 / 시간·내용·비고 표)을 유지하되,
 * 고정 06:00~24:00 빈 행을 쓰지 않고 실제 학습 Task 만 동적 표로 렌더링한다.
 * 한글은 NanumGothic 임베드(IDENTITY_H) — Windows 폰트 경로 하드코딩 없음, EC2 Linux 에서 동일 동작.
 */
@Slf4j
@Component
public class PlannerSchedulePdfRenderer {

    private static final Color GREEN_DARK = new Color(0x15, 0x80, 0x3D);
    private static final Color GREEN_MID = new Color(0x22, 0xC5, 0x5E);
    private static final Color GREEN_LIGHT = new Color(0xEC, 0xFD, 0xF3);
    private static final Color GREEN_BORDER = new Color(0xBB, 0xF7, 0xD0);
    private static final Color GREY_LINE = new Color(0xD1, 0xD5, 0xDB);
    private static final Color GREY_TEXT = new Color(0x4B, 0x55, 0x63);

    private static byte[] cachedFont;

    public byte[] render(Schedule schedule, String plannerTitle, String dateLabel) {
        try (ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            Document doc = new Document(PageSize.A4, 40, 40, 44, 44);
            PdfWriter.getInstance(doc, baos);
            doc.open();

            // 초록 상단 제목 바
            PdfPTable header = new PdfPTable(1);
            header.setWidthPercentage(100);
            PdfPCell hc = new PdfPCell(new Phrase("하루 일정표", font(20, Font.BOLD, Color.WHITE)));
            hc.setBackgroundColor(GREEN_DARK);
            hc.setBorder(0);
            hc.setPadding(12);
            hc.setHorizontalAlignment(Element.ALIGN_CENTER);
            header.addCell(hc);
            header.setSpacingAfter(10);
            doc.add(header);

            // 날짜 · 플래너 제목 · 총 학습시간
            Paragraph date = new Paragraph(dateLabel, font(11, Font.NORMAL, GREY_TEXT));
            date.setSpacingAfter(2);
            doc.add(date);
            Paragraph title = new Paragraph(plannerTitle == null ? "학습 플래너" : plannerTitle, font(15, Font.BOLD, GREEN_DARK));
            title.setSpacingAfter(2);
            doc.add(title);
            Paragraph total = new Paragraph("총 학습시간 " + schedule.totalMinutes() + "분", font(12, Font.BOLD, GREEN_MID));
            total.setSpacingAfter(12);
            doc.add(total);

            // 시간 / 내용 / 비고 표 (동적 행)
            PdfPTable table = new PdfPTable(3);
            table.setWidthPercentage(100);
            try { table.setWidths(new float[]{2.1f, 5.2f, 1.4f}); } catch (Exception ignored) {}
            table.setHeaderRows(1);
            for (String h : new String[]{"시간", "내용", "비고"}) {
                PdfPCell c = new PdfPCell(new Phrase(h, font(11, Font.BOLD, GREEN_DARK)));
                c.setBackgroundColor(GREEN_LIGHT);
                c.setBorderColor(GREEN_BORDER);
                c.setHorizontalAlignment(Element.ALIGN_CENTER);
                c.setPadding(8);
                table.addCell(c);
            }
            for (ScheduleRow r : schedule.rows()) {
                table.addCell(timeCell(r));
                table.addCell(bodyCell(r.title(), Element.ALIGN_LEFT, Font.NORMAL, Color.BLACK));
                table.addCell(bodyCell(PlannerSemanticAnalyzer.typeLabel(r.type()), Element.ALIGN_CENTER, Font.BOLD, GREEN_DARK));
            }
            doc.add(table);

            doc.close();
            return baos.toByteArray();
        } catch (Exception e) {
            throw new RuntimeException("시간표 PDF 생성에 실패했습니다.", e);
        }
    }

    private PdfPCell timeCell(ScheduleRow r) {
        String span = r.startTime() + " ~ " + r.endTime() + (r.endDayOffset() > 0 ? " (익일)" : "");
        PdfPCell c = new PdfPCell(new Phrase(span, font(10.5f, Font.NORMAL, GREY_TEXT)));
        c.setBorderColor(GREY_LINE);
        c.setPadding(8);
        c.setHorizontalAlignment(Element.ALIGN_CENTER);
        c.setVerticalAlignment(Element.ALIGN_MIDDLE);
        return c;
    }

    // 내용/비고 셀: Phrase 는 셀 폭에 맞춰 자동 줄바꿈되고, 셀 높이도 내용에 맞춰 늘어난다(클리핑 없음).
    private PdfPCell bodyCell(String textValue, int align, int style, Color color) {
        PdfPCell c = new PdfPCell(new Phrase(textValue == null ? "" : textValue, font(11, style, color)));
        c.setBorderColor(GREY_LINE);
        c.setPadding(8);
        c.setMinimumHeight(26);
        c.setHorizontalAlignment(align);
        c.setVerticalAlignment(Element.ALIGN_MIDDLE);
        return c;
    }

    private static synchronized byte[] fontBytes() {
        if (cachedFont == null) {
            try (InputStream is = PlannerSchedulePdfRenderer.class.getResourceAsStream("/fonts/NanumGothic.ttf")) {
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
}
