package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lowagie.text.pdf.PdfReader;
import com.lowagie.text.pdf.parser.PdfTextExtractor;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.util.LearningDayNormalizer;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 플래너 PDF: 글자 수 절단 없음(E), 페이지 초과 시 다음 페이지로 이어짐(F), 어절 경계 줄바꿈, 마지막 문장 보존.
 */
class PlannerPdfRendererTest {

    private final ObjectMapper json = new ObjectMapper();

    private static String extractAll(byte[] pdf) throws Exception {
        PdfReader reader = new PdfReader(pdf);
        PdfTextExtractor ex = new PdfTextExtractor(reader);
        StringBuilder sb = new StringBuilder();
        for (int i = 1; i <= reader.getNumberOfPages(); i++) sb.append(ex.getTextFromPage(i)).append('\n');
        reader.close();
        return sb.toString();
    }

    private static String compact(String s) { return s.replaceAll("\\s+", ""); }

    private static Planner roadmapPlanner(String content, String tmi) {
        return Planner.builder().id(7L).userId(1L).plannerType(PlannerType.ROADMAP).sourceType("ROADMAP_AUTO")
                .title("[로드맵 11주차 2일] 고급 회귀 기법").subject("선형회귀").year(2026).month(9).day(8).dayOfWeek("화")
                .term("11주차").studyType("자료 기반 학습").priority("보통").goalTime("115분")
                .content(content).tmi(tmi).build();
    }

    @Test void E_longKoreanSentencesAreFullyRenderedWithoutTruncation() throws Exception {
        String lastSentence = "마지막으로 릿지 회귀와 라쏘 회귀의 규제 강도를 바꿔 가며 검증 오차가 어떻게 달라지는지 표로 정리하고 결론을 한 문장으로 적는다.";
        StringBuilder objective = new StringBuilder("선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으로 학습한다.");
        for (int i = 0; i < 6; i++) objective.append(" 이 문장은 PDF 박스 폭보다 훨씬 길어서 여러 줄로 접히는지 확인하기 위한 긴 한국어 문장이며 단어 중간이 잘리면 안 된다.");
        objective.append(' ').append(lastSentence);
        Planner p = roadmapPlanner("[오늘 목표] " + objective + "\n\n[할 일]\n1. 고급 회귀 기법 코드 흐름 추적: 호출 순서와 데이터 변화를 메모한다.",
                "핵심 개념: 고급 회귀 기법, 선형회귀\n복습 질문:\n- 고급 회귀 기법의 핵심 구성 요소는 무엇인가?\n체크포인트: 고급 회귀 기법의 핵심을 본인 말로 설명할 수 있다.\n산출물: 고급 회귀 기법 정리 노트");
        LearningDayNormalizer.DayContent day = PlannerDayContent.normalizeStored(p);
        assertNotNull(day);
        byte[] pdf = new PlannerPdfRenderer(json).render(p, day);
        String text = extractAll(pdf);

        assertTrue(compact(text).contains(compact(lastSentence)), "마지막 문장이 잘림:\n" + text);
        assertFalse(text.contains("…") || text.contains("..."), text);
        for (String must : List.of("오늘 목표", "할 일", "핵심 개념", "복습 질문", "체크포인트", "산출물", "시간 체크표"))
            assertTrue(text.contains(must), must);
        assertWordBoundaryWrapping(text, objective.toString());
        Files.write(Path.of("/tmp/planner_pdf_long.pdf"), pdf);
    }

    @Test void F_overflowContinuesOnNextPageInsteadOfTruncating() throws Exception {
        StringBuilder content = new StringBuilder("[오늘 목표] 선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으로 학습한다.\n\n[할 일]\n");
        for (int i = 1; i <= 40; i++) {
            content.append(i).append(". 고급 회귀 기법 단계 ").append(i)
                   .append(": 이 항목은 페이지를 넘기기 위한 긴 설명이며 호출 순서와 데이터 변화를 따라가며 관찰한 내용을 빠짐없이 기록한다.\n");
        }
        String finalTask = "고급 회귀 기법 최종 단계: 모든 단계가 끝난 뒤 전체 흐름을 한 장의 그림으로 정리하고 결론을 적는다.";
        content.append("41. ").append(finalTask).append('\n');
        StringBuilder tmi = new StringBuilder("핵심 개념: 고급 회귀 기법, 선형회귀\n복습 질문:\n");
        for (int i = 1; i <= 12; i++) tmi.append("- 고급 회귀 기법 질문 ").append(i).append(": 이 질문은 두 번째 페이지까지 이어지는지 확인하기 위한 것이다. 답을 완결된 문장으로 적을 수 있는가?\n");
        tmi.append("체크포인트: 고급 회귀 기법의 핵심을 본인 말로 설명할 수 있다.\n산출물: 고급 회귀 기법 정리 노트 최종본");
        Planner p = roadmapPlanner(content.toString(), tmi.toString());
        LearningDayNormalizer.DayContent day = PlannerDayContent.normalizeStored(p);
        assertEquals(41, day.tasks().size());
        byte[] pdf = new PlannerPdfRenderer(json).render(p, day);
        PdfReader reader = new PdfReader(pdf);
        int pages = reader.getNumberOfPages();
        reader.close();
        String text = extractAll(pdf);

        assertTrue(pages >= 2, "pages=" + pages);
        assertTrue(compact(text).contains(compact(finalTask)), "마지막 할 일이 사라짐:\n" + text);
        assertTrue(compact(text).contains(compact("고급 회귀 기법 정리 노트 최종본")), text);
        assertTrue(compact(text).contains(compact("고급 회귀 기법 질문 12")), text);
        assertFalse(text.contains("…") || text.contains("..."), text);
        Files.write(Path.of("/tmp/planner_pdf_multipage.pdf"), pdf);
    }

    @Test void freeTextPlannerRendersRawLines() throws Exception {
        Planner p = Planner.builder().id(8L).userId(1L).plannerType(PlannerType.USER).title("자유 메모").subject("자료구조")
                .year(2026).month(9).day(8).content("오늘은 스택과 큐를 복습한다.\n연결 리스트도 본다.").tmi("퇴근 후 1시간").build();
        byte[] pdf = new PlannerPdfRenderer(json).render(p, PlannerDayContent.normalizeStored(p));
        String text = extractAll(pdf);
        assertTrue(compact(text).contains(compact("오늘은 스택과 큐를 복습한다.")) && compact(text).contains(compact("연결 리스트도 본다.")), text);
        assertTrue(compact(text).contains(compact("퇴근 후 1시간")), text);
        assertTrue(text.contains("학습 목표") && text.contains("세부 할 일 / 메모"), text);
    }

    /**
     * 추출된 줄들을 원문에 대응시켜, 줄이 끝나는 위치가 원문의 공백(어절 경계)이거나 문장 끝인지 확인한다.
     * (폭보다 긴 단일 어절만 예외적으로 폭에서 나뉠 수 있으나 이 테스트 문장에는 없다.)
     */
    private static void assertWordBoundaryWrapping(String extracted, String source) {
        String srcCompact = compact(source);
        List<String> lines = new ArrayList<>();
        for (String l : extracted.split("\\R")) if (!l.isBlank()) lines.add(l.trim());
        int pos = 0; boolean started = false; int matchedLines = 0;
        for (String line : lines) {
            String lc = compact(line);
            if (lc.isEmpty()) continue;
            if (!started) {
                if (lc.length() < 8 || !srcCompact.startsWith(lc)) continue;   // 과목명 등 짧은 동일 접두 줄은 건너뛴다
                started = true;
            } else if (!srcCompact.startsWith(lc, pos)) {
                break;
            }
            pos += lc.length(); matchedLines++;
            if (pos >= srcCompact.length()) break;
            // 원문에서 이 위치(공백 제거 기준 pos)에 해당하는 다음 글자 앞이 공백이어야 한다
            int idx = indexInSource(source, pos);
            assertTrue(idx > 0 && Character.isWhitespace(source.charAt(idx - 1)),
                    "단어 중간 줄바꿈: '" + line + "' 다음 글자='" + source.charAt(idx) + "'");
        }
        assertTrue(matchedLines >= 3, "줄 매칭 실패(matched=" + matchedLines + ")\n" + extracted);
        assertTrue(pos >= srcCompact.length(), "원문 끝까지 매칭되지 않음 pos=" + pos + "/" + srcCompact.length());
    }

    /** 공백 제거 기준 n번째 글자가 원문에서 시작하는 인덱스. */
    private static int indexInSource(String source, int compactPos) {
        int seen = 0;
        for (int i = 0; i < source.length(); i++) {
            if (Character.isWhitespace(source.charAt(i))) continue;
            if (seen == compactPos) return i;
            seen++;
        }
        return source.length();
    }
}
