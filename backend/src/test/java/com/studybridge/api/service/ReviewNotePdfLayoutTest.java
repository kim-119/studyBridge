package com.studybridge.api.service;

import com.lowagie.text.Rectangle;
import com.lowagie.text.pdf.PdfReader;
import com.lowagie.text.pdf.parser.PdfTextExtractor;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 오답노트 PDF 레이아웃 검증.
 *  - A4 세로(portrait) 용지인지
 *  - 틀린 문제 1개당 A4 한 장으로 분리되는지
 *  - com.example.coroutinepractice.data.dto 같은 코드 토큰이 온점 때문에 깨지지 않는지
 */
class ReviewNotePdfLayoutTest {

    private static final String CODE_TOKEN = "com.example.coroutinepractice.data.dto";

    @SuppressWarnings("unchecked")
    private byte[] buildSamplePdf(int problemCount) throws Exception {
        ReviewNoteService svc = new ReviewNoteService(null, null, null, null, null, null);

        Class<?> wiClass = Class.forName("com.studybridge.api.service.ReviewNoteService$WrongItem");
        Constructor<?> ctor = wiClass.getDeclaredConstructor(
                String.class, List.class, Integer.class, Integer.class, String.class, boolean.class, int.class);
        ctor.setAccessible(true);
        Field conceptField = wiClass.getDeclaredField("concept");
        conceptField.setAccessible(true);

        List<Object> items = new ArrayList<>();
        for (int i = 0; i < problemCount; i++) {
            Object wi = ctor.newInstance(
                    CODE_TOKEN + " 패키지 추가 로직을 단위 테스트하기 쉽게 의존성을 분리하고 테스트 케이스 3개를 설계한다.",
                    Arrays.asList("선택지 A java.lang.String", "선택지 B", "선택지 C", "선택지 D"),
                    Integer.valueOf(2), Integer.valueOf(1),
                    "해설: " + CODE_TOKEN + " 의존성을 분리하면 build.gradle.kts 설정이 단순해진다.",
                    false, i + 1);
            conceptField.set(wi, "핵심 개념: org.springframework.stereotype.Service");
            items.add(wi);
        }

        Method m = ReviewNoteService.class.getDeclaredMethod("buildPdf",
                String.class, String.class, String.class, String.class,
                int.class, int.class, String.class, List.class);
        m.setAccessible(true);
        return (byte[]) m.invoke(svc, "HTTP클라이언트 오답노트", "HTTP클라이언트", "hard", "2026.06.14",
                problemCount, 0, "전체 피드백: 의존성 분리와 단위 테스트 설계를 복습하세요.", items);
    }

    @Test
    void a4Portrait_onePagePerProblem_codeTokenPreserved() throws Exception {
        byte[] pdf = buildSamplePdf(3);
        assertNotNull(pdf);
        assertTrue(pdf.length > 2000, "PDF 바이트가 비정상적으로 작음");

        PdfReader reader = new PdfReader(pdf);
        try {
            // 문제 3개 → 최소 3페이지(내용이 길어 분할되면 그 이상일 수 있으나 3 이상이어야 함)
            assertTrue(reader.getNumberOfPages() >= 3,
                    "문제 3개인데 페이지가 " + reader.getNumberOfPages() + "장");

            Rectangle size = reader.getPageSize(1);
            assertEquals(595.27f, size.getWidth(), 2f, "A4 너비(pt)");
            assertEquals(841.89f, size.getHeight(), 2f, "A4 높이(pt)");
            assertTrue(size.getHeight() > size.getWidth(), "세로(portrait) 방향이어야 함");

            // 코드 토큰이 온점 때문에 끊기지 않고 한 덩어리로 들어갔는지(추출 텍스트에서 공백 제거 후 포함 확인)
            String text = new PdfTextExtractor(reader).getTextFromPage(1);
            String collapsed = text.replaceAll("\\s+", "");
            assertTrue(collapsed.contains(CODE_TOKEN),
                    "코드 토큰이 PDF에서 깨졌음. 추출본=" + text);
        } finally {
            reader.close();
        }
    }

    @Test
    void dumpSamplePdfForVisualInspection() throws Exception {
        byte[] pdf = buildSamplePdf(2);
        java.nio.file.Path out = java.nio.file.Paths.get(System.getProperty("user.dir"), "build", "review-note-sample.pdf");
        java.nio.file.Files.createDirectories(out.getParent());
        java.nio.file.Files.write(out, pdf);
        System.out.println("[SAMPLE PDF] " + out.toAbsolutePath() + " (" + pdf.length + " bytes)");
    }

    @Test
    void singleProblem_isSingleA4Page() throws Exception {
        byte[] pdf = buildSamplePdf(1);
        PdfReader reader = new PdfReader(pdf);
        try {
            assertEquals(1, reader.getNumberOfPages(), "문제 1개 → A4 1장");
            Rectangle size = reader.getPageSize(1);
            assertTrue(size.getHeight() > size.getWidth(), "portrait");
        } finally {
            reader.close();
        }
    }
}
