package com.studybridge.api.service;

import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.GroundingEvidence;
import lombok.extern.slf4j.Slf4j;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 그룹스터디 퀴즈 품질 게이트의 평가 근거(원문) 추출. 그룹 자료(group_study_materials)는 개인 자료와 달리 extracted_text 가 없고
 * ai07 이 S3 원본을 직접 읽어 퀴즈를 만든다. 그래서 게이트 ON 일 때만 Spring 이 가진 원본 파일 바이트(업로드 본문 또는 S3 객체)에서
 * 결정적으로(AI 없이) 텍스트를 뽑아 GroundingEvidence 로 보낸다.
 *
 *  · PDF: OpenPDF(이미 의존성) PdfTextExtractor, 앞쪽 최대 {@value #MAX_PDF_PAGES}쪽. 스캔(이미지) PDF 는 텍스트가 없다 → 근거 없음.
 *  · TXT: UTF-8. DOCX: word/document.xml 의 w:t 텍스트(압축 해제 상한 {@value #MAX_DOCX_XML_BYTES} 바이트).
 *  · 실패/빈 결과는 빈 문자열 — 근거 없이 평가기로 가고, PDF_QUIZ 는 근거 필수라 평가기가 거절한다(Spring 이 임의 승인하지 않음).
 * 원문은 평가기에만 보내고 로그에 남기지 않는다.
 */
@Slf4j
public final class GroupStudyQuizSourceText {

    static final int MAX_PDF_PAGES = 60;
    static final int MAX_DOCX_XML_BYTES = 8 * 1024 * 1024;
    static final String SOURCE_TYPE = "PDF_ORIGINAL";
    private static final Pattern DOCX_TEXT = Pattern.compile("<w:t(?:\\s[^>]*)?>([^<]*)</w:t>|</w:p>");

    private GroupStudyQuizSourceText() {
    }

    /** 평가 근거 문서 id(개인 자료 materialId 와 id 공간이 달라 documentId 로 구분한다). */
    public static String documentId(Long groupMaterialId) {
        return "group-material-" + groupMaterialId;
    }

    public static String extract(byte[] bytes, String contentType, String fileName, int maxChars) {
        if (bytes == null || bytes.length == 0 || maxChars <= 0) {
            return "";
        }
        String ct = contentType == null ? "" : contentType.toLowerCase();
        String name = fileName == null ? "" : fileName.toLowerCase();
        try {
            String raw;
            if (ct.contains("pdf") || name.endsWith(".pdf") || startsWith(bytes, "%PDF")) {
                raw = pdf(bytes, maxChars);
            } else if (ct.contains("wordprocessingml") || name.endsWith(".docx")) {
                raw = docx(bytes, maxChars);
            } else if (ct.startsWith("text/") || name.endsWith(".txt")) {
                raw = new String(bytes, StandardCharsets.UTF_8);
            } else {
                raw = "";
            }
            return normalize(raw, maxChars);
        } catch (Exception | StackOverflowError e) {
            log.warn("[GROUP_QUIZ_GATE] 근거 원문 추출 실패 type={} error={} → 근거 없이 평가(거절됨)", ct, e.getClass().getSimpleName());
            return "";
        }
    }

    /** 원문을 PDF_ORIGINAL 근거 청크로 나눈다(AiResponseQualityGate.pdfEvidence 와 같은 규칙, materialId 대신 documentId). */
    public static List<GroundingEvidence> evidence(String documentId, String text, int chunkChars, int maxTotalChars) {
        List<GroundingEvidence> out = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return out;
        }
        int size = Math.max(1, Math.min(chunkChars, ResponseQualityV1.MAX_EVIDENCE_CHARS));
        int total = 0;
        for (int i = 0, n = 0; i < text.length() && n < ResponseQualityV1.MAX_EVIDENCE_ITEMS && total < maxTotalChars; n++) {
            int end = Math.min(text.length(), i + Math.min(size, maxTotalChars - total));
            String chunk = text.substring(i, end);
            out.add(new GroundingEvidence(null, SOURCE_TYPE, null, documentId, null, null, documentId + "-c" + n, chunk));
            total += chunk.length();
            i = end;
        }
        return out;
    }

    private static String pdf(byte[] bytes, int maxChars) throws Exception {
        com.lowagie.text.pdf.PdfReader reader = new com.lowagie.text.pdf.PdfReader(bytes);
        try {
            com.lowagie.text.pdf.parser.PdfTextExtractor ex = new com.lowagie.text.pdf.parser.PdfTextExtractor(reader);
            StringBuilder sb = new StringBuilder();
            int pages = Math.min(reader.getNumberOfPages(), MAX_PDF_PAGES);
            for (int p = 1; p <= pages && sb.length() < maxChars; p++) {
                try {
                    sb.append(ex.getTextFromPage(p)).append('\n');
                } catch (Exception pageError) {
                    // 한 쪽 해석 실패는 건너뛴다(나머지 쪽 근거는 유지)
                }
            }
            return sb.toString();
        } finally {
            reader.close();
        }
    }

    private static String docx(byte[] bytes, int maxChars) throws Exception {
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(bytes))) {
            ZipEntry e;
            while ((e = zip.getNextEntry()) != null) {
                if (!"word/document.xml".equals(e.getName())) {
                    continue;
                }
                String xml = readCapped(zip, MAX_DOCX_XML_BYTES);
                StringBuilder sb = new StringBuilder();
                Matcher m = DOCX_TEXT.matcher(xml);
                while (m.find() && sb.length() < maxChars) {
                    sb.append(m.group(1) != null ? unescape(m.group(1)) : "\n");
                }
                return sb.toString();
            }
        }
        return "";
    }

    private static String readCapped(InputStream in, int cap) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int r;
        while ((r = in.read(buf)) > 0) {
            int room = cap - out.size();
            if (room <= 0) {
                break;
            }
            out.write(buf, 0, Math.min(r, room));
        }
        return out.toString(StandardCharsets.UTF_8);
    }

    private static String unescape(String s) {
        return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&");
    }

    private static String normalize(String raw, int maxChars) {
        if (raw == null) {
            return "";
        }
        String s = raw.replace('\u0000', ' ').replaceAll("[ \\t\\x0B\\f\\r]+", " ").replaceAll("\\n\\s*\\n+", "\n").strip();
        return s.length() > maxChars ? s.substring(0, maxChars) : s;
    }

    private static boolean startsWith(byte[] b, String prefix) {
        byte[] p = prefix.getBytes(StandardCharsets.US_ASCII);
        if (b.length < p.length) {
            return false;
        }
        for (int i = 0; i < p.length; i++) {
            if (b[i] != p[i]) {
                return false;
            }
        }
        return true;
    }
}
