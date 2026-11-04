package com.studybridge.api.ai.memory;

import static com.studybridge.api.ai.memory.LearningMemoryFixtures.LEGACY_CANARY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.MAT;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.OTHER_CANARY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.OTHER_MAT;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.OTHER_ROOM;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.QUESTION;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.REJECTED_CANARY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.REQ;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.ROOM;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.SCOPE_KEY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.UNAPPROVED_CONCEPT_CANARY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.UNAPPROVED_SUMMARY_CANARY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.studybridge.api.ai.contract.v1.AiContractException;
import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.LearningContextV1;
import com.studybridge.api.ai.contract.v1.LearningContextV1.ContextItem;
import com.studybridge.api.ai.contract.v1.LearningContextV1.Kind;
import com.studybridge.api.ai.contract.v1.LearningContextV1.SourceType;
import com.studybridge.api.ai.contract.v1.LearningContextV1.TrustLevel;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.MaterialSummary;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.entity.Todo;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.repository.query.parser.PartTree;

/**
 * Learning Memory 조립 규칙(Phase D5): 계약 검증 통과·역할 보존·미승인 AI 답변/요약/개념 제외·다른 사용자 자료·방 제외(소유권)·예산·
 * 페이지 provenance·scope 토큰(rid 바인딩)·키 없으면 미전송·플래그 OFF 무호출.
 */
class LearningMemoryAssemblerTest {

    static final Instant NOW = Instant.parse("2026-11-04T01:00:00Z");
    static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    static LearningMemoryAssembler fixed(LearningMemoryAssembler a) {
        a.setClock(Clock.fixed(NOW, ZoneId.of("UTC")), SEOUL);
        return a;
    }

    static String json(LearningContextV1 c) throws Exception {
        return ContractJson.STRICT.writeValueAsString(c);
    }

    /** 직렬화 → 엄격 파서(모르는 필드·타입 강제변환 거부) 재파싱 → 재검증까지 통과해야 ai07 로 보낼 수 있는 형태다. */
    static LearningContextV1 roundTrip(LearningContextV1 c) throws Exception {
        LearningContextV1 back = ContractJson.STRICT.readValue(json(c), LearningContextV1.class);
        assertTrue(LearningContextV1.validate(back).ok(), () -> "재파싱 검증 실패: " + LearningContextV1.validate(back).list());
        return back;
    }

    static List<ContextItem> of(LearningContextV1 c, Kind k) {
        return c.contextItems().stream().filter(i -> i.kind() == k).toList();
    }

    @Test
    void assemblesValidContextWithRolesTrustAndProvenance() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertNotNull(c);
        assertTrue(LearningContextV1.validate(c).ok(), () -> String.valueOf(LearningContextV1.validate(c).list()));
        roundTrip(c);
        assertEquals(LearningContextV1.SCHEMA_VERSION, c.schemaVersion());
        assertEquals(REQ, c.requestId());
        assertEquals(new PseudonymousUserKeys(LearningMemoryFixtures.keys(true, true)).of(USER), c.pseudonymousUserKey());
        assertFalse(c.pseudonymousUserKey().contains(String.valueOf(USER)), "가명 키에 PK 가 그대로 들어가면 안 된다");
        assertEquals(MAT, c.materialId());
        assertEquals(QUESTION, c.currentQuestion());

        // 모든 항목: 주장 신뢰 == 적용 신뢰(상한 초과 주장 없음) + sourceType 별 기대 신뢰
        Map<SourceType, TrustLevel> expected = Map.of(SourceType.PDF_ORIGINAL, TrustLevel.SOURCE_PRIMARY,
                SourceType.CHAT_MESSAGE, TrustLevel.USER_ASSERTED, SourceType.AI_ANSWER, TrustLevel.AI_GENERATED,
                SourceType.AI_SUMMARY, TrustLevel.AI_GENERATED, SourceType.USER_MEMO, TrustLevel.USER_ASSERTED,
                SourceType.SYSTEM_RECORD, TrustLevel.SYSTEM_RECORD, SourceType.USER_PROVIDED_TEXT, TrustLevel.USER_ASSERTED);
        for (ContextItem it : c.contextItems()) {
            assertEquals(it.trustLevel(), it.effectiveTrust(), it.id());
            assertEquals(expected.get(it.sourceType()), it.trustLevel(), it.id());
            if (it.sourceType() == SourceType.AI_ANSWER || it.sourceType() == SourceType.AI_SUMMARY) {
                assertEquals("APPROVED", it.qualityStatus(), "AI 생성 항목은 승인분만: " + it.id());
            }
        }

        // 대화: 이번 질문 제외, 역할 보존(user/assistant), 승인 AI 답변만, 시간순
        List<ContextItem> chat = of(c, Kind.CHAT_TURN);
        assertEquals(List.of("chat:6", "chat:9"), chat.stream().map(ContextItem::id).toList());
        assertEquals("user", chat.get(0).role());
        assertEquals(SourceType.CHAT_MESSAGE, chat.get(0).sourceType());
        assertEquals("assistant", chat.get(1).role());
        assertEquals(SourceType.AI_ANSWER, chat.get(1).sourceType());
        String all = json(c);
        for (String leaked : List.of(LEGACY_CANARY, REJECTED_CANARY, UNAPPROVED_CONCEPT_CANARY, OTHER_CANARY)) {
            assertFalse(all.contains(leaked), "미승인/타인 내용 누출: " + leaked);
        }

        // PDF 원문: 질문과 가장 겹치는 2쪽이 먼저, 원문 부분 문자열 그대로 + 페이지·청크·리비전
        List<ContextItem> pdf = of(c, Kind.PDF_CHUNK);
        assertEquals(2, pdf.size());
        ContextItem top = pdf.get(0);
        assertEquals(2, top.page());
        assertEquals("m345-p2-c0", top.chunkId());
        assertEquals(PAGE2(), top.content());
        assertTrue(LearningMemoryFixtures.EXTRACTED.contains(top.content()), "요약·의역 없이 원문 그대로");
        assertEquals(SourceType.PDF_ORIGINAL, top.sourceType());
        assertEquals(TrustLevel.SOURCE_PRIMARY, top.trustLevel());
        assertEquals("material:345", top.sourceId());
        assertEquals(64, top.sourceRevisionHash().length());
        assertEquals(top.sourceRevisionHash(), top.provenance().documentRevision());
        assertNotNull(top.provenance().retrievalScore());

        // 승인 요약 = AI_GENERATED, 메모 = USER_ASSERTED
        assertEquals(1, of(c, Kind.SUMMARY).size());
        assertEquals(TrustLevel.AI_GENERATED, of(c, Kind.SUMMARY).get(0).trustLevel());
        assertEquals(SourceType.USER_MEMO, of(c, Kind.USER_MEMO).get(0).sourceType());

        // 반복 오답 개념: 승인 노트만, 공백 정규화 후 같은 개념 2회
        List<ContextItem> wrong = of(c, Kind.WRONG_NOTE);
        assertEquals(2, wrong.size());
        assertTrue(wrong.get(0).content().contains("3-way handshake") && wrong.get(0).content().contains("2회"), wrong.get(0).content());
        assertEquals("review_note:31", wrong.get(0).sourceId());
        assertTrue(wrong.get(0).provenance().notes().contains("count=2"));

        // 퀴즈 정답률: 숫자만(SYSTEM_RECORD)
        ContextItem quiz = of(c, Kind.QUIZ_RESULT).get(0);
        assertEquals(SourceType.SYSTEM_RECORD, quiz.sourceType());
        assertTrue(quiz.content().contains("7/10") && quiz.content().contains("70점") && quiz.content().contains("최고 80점"),
                quiz.content());

        // 일정: 직접 입력 할 일 = USER_ASSERTED, 시스템 등록 복습 일정 = SYSTEM_RECORD, 같은 오답노트 복습 예정일은 중복 제외
        List<ContextItem> plan = of(c, Kind.PLANNER_REVIEW);
        assertEquals(List.of("todo:41", "todo:42"), plan.stream().map(ContextItem::id).toList());
        assertEquals(SourceType.USER_PROVIDED_TEXT, plan.get(0).sourceType());
        assertEquals(SourceType.SYSTEM_RECORD, plan.get(1).sourceType());

        int total = c.contextItems().stream().mapToInt(i -> ContractJson.len(i.content())).sum();
        assertTrue(total <= 6000, "기본 예산 6000 초과: " + total);
    }

    static String PAGE2() {
        return LearningMemoryFixtures.PAGE2;
    }

    @Test
    void otherUsersMaterialAndRoomAreNeverIncluded() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        // 다른 사용자 소유 자료 + 다른 사용자 방을 요청에 넣어도
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, OTHER_ROOM, OTHER_MAT, REQ, QUESTION);
        assertNotNull(c, "사용자 본인 기록(오답 개념·일정)은 남는다");
        assertNull(c.materialId(), "소유하지 않은 materialId 는 컨텍스트 범위에 넣지 않는다");
        assertFalse(json(c).contains(OTHER_CANARY));
        assertTrue(of(c, Kind.PDF_CHUNK).isEmpty() && of(c, Kind.SUMMARY).isEmpty() && of(c, Kind.USER_MEMO).isEmpty()
                && of(c, Kind.CHAT_TURN).isEmpty());
        verify(f.summaries, never()).findByMaterial_MaterialId(OTHER_MAT);
        verify(f.memos, never()).findByMaterial_MaterialId(OTHER_MAT);
        verify(f.quizzes, never()).findByMaterial_MaterialIdOrderByCreatedAtDesc(OTHER_MAT);
        verify(f.messages, never()).findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(OTHER_ROOM);
        verify(f.reviewNotes, never()).findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(eq(USER), eq(OTHER_MAT));
        // 사용자 전체 범위 오답노트는 userId 로만 조회
        verify(f.reviewNotes).findTop20ByUserIdOrderByCreatedAtDesc(USER);
        roundTrip(c);
    }

    @Test
    void foreignRowsReturnedByStoreAreFilteredByOwner() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        ReviewNote foreign = ReviewNote.builder().reviewNoteId(77L).userId(LearningMemoryFixtures.OTHER).sourceMaterialId(MAT)
                .qualityStatus("APPROVED").title("남의 노트").createdAt(LocalDateTime.of(2026, 11, 3, 9, 0))
                .retryJson("[{\"concept\":\"" + OTHER_CANARY + "\"}]").build();
        when(f.reviewNotes.findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(USER, MAT)).thenReturn(List.of(foreign));
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertFalse(json(c).contains(OTHER_CANARY), "저장소가 타인 행을 돌려줘도 userId 로 다시 거른다");
    }

    @Test
    void unapprovedSummaryAndLegacyAnswersAreExcludedEvenWhenTheyAreAllThereIs() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        when(f.summaries.findByMaterial_MaterialId(MAT)).thenReturn(Optional.of(MaterialSummary.builder().summaryId(5L)
                .overview(UNAPPROVED_SUMMARY_CANARY).qualityStatus(null).build()));
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertTrue(of(c, Kind.SUMMARY).isEmpty());
        assertFalse(json(c).contains(UNAPPROVED_SUMMARY_CANARY));
        // 방 기록이 미승인 AI 답변뿐이면 대화 항목은 사용자 발화만
        when(f.messages.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(ROOM)).thenReturn(List.of(
                LearningMemoryFixtures.msg(3L, "AI", LEGACY_CANARY, "r1", null, LocalDateTime.of(2026, 11, 1, 9, 0)),
                LearningMemoryFixtures.msg(2L, "USER", "처음 질문", "r1", null, LocalDateTime.of(2026, 11, 1, 8, 59))));
        LearningContextV1 c2 = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertEquals(List.of("user"), of(c2, Kind.CHAT_TURN).stream().map(ContextItem::role).toList());
        assertFalse(json(c2).contains(LEGACY_CANARY));
    }

    @Test
    void retryEchoOfSameQuestionIsNotRepeatedAsHistory() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        LocalDateTime t = LocalDateTime.of(2026, 11, 3, 10, 0);
        when(f.messages.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(ROOM)).thenReturn(List.of(
                LearningMemoryFixtures.msg(12L, "USER", QUESTION, REQ, null, t.plusMinutes(2)),
                LearningMemoryFixtures.msg(11L, "USER", "  " + QUESTION + " ", "req-failed", null, t.plusMinutes(1)),
                LearningMemoryFixtures.msg(10L, "USER", "예전 질문", "req-a", null, t)));
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertEquals(List.of("chat:10"), of(c, Kind.CHAT_TURN).stream().map(ContextItem::id).toList());
    }

    /** 예산을 넘치게 만드는 픽스처: 긴 대화 20건(짝수 id = 승인 AI 답변), 긴 PDF 2쪽, 긴 승인 요약. */
    static LearningMemoryFixtures overBudget() {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        LocalDateTime t = LocalDateTime.of(2026, 11, 3, 10, 0);
        List<ChatMessage> longChat = new ArrayList<>();
        for (int i = 20; i >= 1; i--) {
            longChat.add(LearningMemoryFixtures.msg(i, i % 2 == 0 ? "AI" : "USER", "대화" + i + " " + "가".repeat(700), "r" + i,
                    i % 2 == 0 ? "APPROVED" : null, t.plusMinutes(i)));
        }
        when(f.messages.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(ROOM)).thenReturn(longChat);
        f.material.setExtractedText("[Page 1]\n" + "TCP handshake ".repeat(300) + "\n[Page 2]\n" + "SYN ACK ".repeat(400));
        when(f.summaries.findByMaterial_MaterialId(MAT)).thenReturn(Optional.of(MaterialSummary.builder().summaryId(5L)
                .overview("요약 ".repeat(500)).qualityStatus("APPROVED").build()));
        return f;
    }

    @Test
    void budgetIsEnforcedWithPriorityAndTruncationMarks() throws Exception {
        LearningMemoryFixtures f = overBudget();
        LearningMemoryAssembler a = fixed(f.assembler(LearningMemorySettings.forTest(true, 1500, 500),
                LearningMemoryFixtures.keys(true, true)));
        LearningContextV1 c = a.assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertNotNull(c);
        roundTrip(c);
        int total = c.contextItems().stream().mapToInt(i -> ContractJson.len(i.content())).sum();
        assertTrue(total <= 1500, "예산 초과: " + total);
        for (ContextItem it : c.contextItems()) {
            assertTrue(ContractJson.len(it.content()) <= 500, "항목 상한 초과: " + it.id());
            boolean marked = it.content().endsWith(LearningMemoryAssembler.TRUNCATION_MARK);
            assertEquals(marked, it.provenance().notes().contains("truncated"), "잘림 표식과 notes 일치: " + it.id());
        }
        assertTrue(c.contextItems().stream().anyMatch(i -> i.provenance().notes().contains("truncated")), "잘림 표시가 있어야 한다");
        // 우선순위: 작은 기록(퀴즈·오답 개념)과 PDF 원문이 먼저 남고, 대화는 최신 턴이 먼저 예산을 받는다
        assertFalse(of(c, Kind.QUIZ_RESULT).isEmpty());
        assertFalse(of(c, Kind.WRONG_NOTE).isEmpty());
        assertFalse(of(c, Kind.PDF_CHUNK).isEmpty());
        List<ContextItem> chat = of(c, Kind.CHAT_TURN);
        assertFalse(chat.isEmpty());
        assertEquals("chat:20", chat.get(chat.size() - 1).id(), "가장 최근 턴이 남아야 한다(시간순 끝)");
        assertTrue(of(c, Kind.PDF_CHUNK).stream().allMatch(i -> f.material.getExtractedText().contains(i.content())),
                "PDF 조각은 원문 부분 문자열");
        // 역할은 잘려도 보존
        for (ContextItem it : chat) {
            assertEquals(Integer.parseInt(it.id().substring("chat:".length())) % 2 == 0 ? "assistant" : "user", it.role(), it.id());
        }
    }

    @Test
    void contractCapsHoldForMaximumSettings() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        f.material.setExtractedText("[Page 1]\n" + "핸드셰이크 ".repeat(5000));
        LearningMemoryAssembler a = fixed(f.assembler(new LearningMemorySettings(true, 999999, 999999, 99, 99, 9999),
                LearningMemoryFixtures.keys(true, true)));
        LearningContextV1 c = a.assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertNotNull(c);
        roundTrip(c);
        assertTrue(c.contextItems().size() <= LearningContextV1.MAX_CONTEXT_ITEMS);
        assertTrue(c.contextItems().stream().allMatch(i -> ContractJson.len(i.content()) <= LearningContextV1.MAX_ITEM_CHARS));
        assertTrue(c.contextItems().stream().mapToInt(i -> ContractJson.len(i.content())).sum() <= LearningContextV1.MAX_TOTAL_CHARS);
    }

    @Test
    void noPageBoundaryMeansNoPdfExcerptButFormFeedPagesWork() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        f.material.setExtractedText("TCP 3-way handshake 는 SYN, SYN-ACK, ACK 로 이뤄진다. 페이지 정보 없음.");
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        assertTrue(of(c, Kind.PDF_CHUNK).isEmpty(), "페이지를 모르면 추측하지 않고 PDF 원문을 싣지 않는다");

        f.material.setExtractedText("표지\fTCP 3-way handshake 는 SYN 으로 시작한다.\f\fUDP 는 비연결형이다.");
        LearningContextV1 c2 = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        List<ContextItem> pdf = of(c2, Kind.PDF_CHUNK);
        assertEquals(2, pdf.get(0).page());
        assertEquals("TCP 3-way handshake 는 SYN 으로 시작한다.", pdf.get(0).content());
        assertTrue(pdf.stream().noneMatch(i -> i.page() == 3), "빈 쪽은 건너뛴다");
        assertEquals(List.of(1, 2, 4), LearningMemoryAssembler.pages("표지\fTCP 3-way handshake 는 SYN 으로 시작한다.\f\fUDP 는 비연결형이다.")
                .stream().map(LearningMemoryAssembler.Page::number).toList(), "빈 쪽을 건너뛰어도 번호는 유지(UDP 는 4쪽)");
        assertEquals(List.of(3, 9), LearningMemoryAssembler.pages("머리말(쪽 미상)\n[Page 3]\n셋째 쪽\n  [Page 9]  \n아홉째 쪽")
                .stream().map(LearningMemoryAssembler.Page::number).toList(), "표식 앞 머리말은 쪽을 모르므로 버린다");
    }

    @Test
    void loneSurrogatesAndControlCharsAreRemoved() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        when(f.messages.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(ROOM)).thenReturn(List.of(
                LearningMemoryFixtures.msg(5L, "USER", "깨진\ud800문자\u0000와 이모지😀", "r1", null, LocalDateTime.of(2026, 11, 1, 9, 0))));
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION);
        String content = of(c, Kind.CHAT_TURN).get(0).content();
        assertFalse(ContractJson.hasLoneSurrogate(content));
        assertEquals("깨진문자 와 이모지😀", content);
        roundTrip(c);
    }

    @Test
    void quizEventsUseOnlyServerRecordsWithoutMaterial() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        LearningLoopEvent server = LearningLoopEvent.builder().id(501L).userId(USER).score(85).quizId(75L).difficulty("hard")
                .origin(com.studybridge.api.entity.LearningEventOrigin.SERVER).createdAt(LocalDateTime.of(2026, 11, 2, 9, 0)).build();
        LearningLoopEvent client = LearningLoopEvent.builder().id(502L).userId(USER).score(100)
                .origin(com.studybridge.api.entity.LearningEventOrigin.CLIENT).createdAt(LocalDateTime.of(2026, 11, 2, 9, 1)).build();
        LearningLoopEvent legacy = LearningLoopEvent.builder().id(503L).userId(USER).score(99).origin(null)
                .createdAt(LocalDateTime.of(2026, 11, 2, 9, 2)).build();
        when(f.events.findByUserIdAndEventTypeOrderByCreatedAtDesc(eq(USER), eq(com.studybridge.api.entity.LearningEventType.QUIZ_SUBMITTED),
                org.mockito.ArgumentMatchers.any())).thenReturn(List.of(legacy, client, server));
        LearningContextV1 c = fixed(f.assembler(true)).assemble(USER, ROOM, null, REQ, QUESTION);
        assertEquals(List.of("quiz-event:501"), of(c, Kind.QUIZ_RESULT).stream().map(ContextItem::id).toList());
        assertTrue(of(c, Kind.QUIZ_RESULT).get(0).content().contains("85점"));
        verify(f.quizzes, never()).findByMaterial_MaterialIdOrderByCreatedAtDesc(anyLong());
    }

    // ── attach: 플래그·키·scope 토큰 ──────────────────────────────────────────────────

    @Test
    void flagOffTouchesNothing() {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        LearningMemoryAssembler a = f.assembler(false);
        assertFalse(a.enabled());
        assertNull(a.attach(USER, ROOM, MAT, REQ, QUESTION));
        verifyNoInteractions(f.allMocks());
    }

    @Test
    void attachSignsScopeTokenBoundToRequestIdAndSubject() throws Exception {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        LearningMemoryAssembler a = fixed(f.assembler(true));
        LearningMemoryAssembler.Attachment att = a.attach(USER, ROOM, MAT, REQ, QUESTION);
        assertNotNull(att);
        JsonNode body = att.body();
        assertEquals(LearningContextV1.SCHEMA_VERSION, body.path("schemaVersion").asText());
        LearningContextV1 parsed = ContractJson.STRICT.treeToValue(body, LearningContextV1.class);
        assertTrue(LearningContextV1.validate(parsed).ok());
        String token = att.headers().get().get(AiContractSigning.HEADER_SCOPE);
        assertNotNull(token);
        byte[] key = SCOPE_KEY.getBytes(StandardCharsets.UTF_8);
        String sub = new PseudonymousUserKeys(LearningMemoryFixtures.keys(true, true)).of(USER);
        AiContractSigning.ScopeClaims claims = AiContractSigning.verifyScopeToken(key, token, REQ, sub, NOW.getEpochSecond());
        assertEquals(REQ, claims.rid());
        assertEquals(sub, claims.sub());
        assertEquals(java.util.Set.of(MAT), claims.materialIds());
        assertTrue(claims.documentIds().isEmpty());
        assertTrue(claims.exp() - claims.iat() <= 120, "TTL ≤ 120s");
        assertEquals(parsed.pseudonymousUserKey(), claims.sub());
        AiContractException rid = assertThrows(AiContractException.class,
                () -> AiContractSigning.verifyScopeToken(key, token, "req-other-0002", sub, NOW.getEpochSecond()));
        assertEquals("SCOPE_REQUEST_MISMATCH", rid.code());
        AiContractException subj = assertThrows(AiContractException.class,
                () -> AiContractSigning.verifyScopeToken(key, token, REQ, "pk_someoneelse000000000000000000", NOW.getEpochSecond()));
        assertEquals("SCOPE_SUBJECT_MISMATCH", subj.code());
        AiContractException expired = assertThrows(AiContractException.class,
                () -> AiContractSigning.verifyScopeToken(key, token, REQ, sub, NOW.getEpochSecond() + 121));
        assertEquals("SCOPE_TOKEN_EXPIRED", expired.code());
        // 소유하지 않은 자료는 토큰 범위에도 없다
        String t2 = fixed(f.assembler(true)).attach(USER, ROOM, OTHER_MAT, REQ, QUESTION).headers().get().get(AiContractSigning.HEADER_SCOPE);
        assertTrue(AiContractSigning.verifyScopeToken(key, t2, REQ, sub, NOW.getEpochSecond()).materialIds().isEmpty());
    }

    @Test
    void missingKeysMeanNoContext() {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        assertNull(f.assembler(LearningMemorySettings.forTest(true), LearningMemoryFixtures.keys(false, true))
                .attach(USER, ROOM, MAT, REQ, QUESTION), "scope 키 없음 → 미전송");
        assertNull(f.assembler(LearningMemorySettings.forTest(true), LearningMemoryFixtures.keys(true, false))
                .attach(USER, ROOM, MAT, REQ, QUESTION), "가명 키 없음 → 미전송");
        assertNull(f.assembler(LearningMemorySettings.forTest(true), LearningMemoryFixtures.keys(true, false))
                .assemble(USER, ROOM, MAT, REQ, QUESTION));
        // 같은 값 재사용(scope 키 == 가명 키)도 fail-closed
        com.studybridge.api.ai.contract.v1.AiSigningKeys reused = new com.studybridge.api.ai.contract.v1.AiSigningKeys(SCOPE_KEY, "", "",
                SCOPE_KEY, "");
        assertNull(f.assembler(LearningMemorySettings.forTest(true), reused).attach(USER, ROOM, MAT, REQ, QUESTION));
    }

    @Test
    void invalidRequestIdOrNothingToSayYieldsNull() {
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        assertNull(f.assembler(true).assemble(USER, ROOM, MAT, "bad id\n", QUESTION));
        LearningMemoryFixtures empty = new LearningMemoryFixtures();
        when(empty.reviewNotes.findTop20ByUserIdOrderByCreatedAtDesc(USER)).thenReturn(List.of());
        when(empty.todos.findTop20ByUserIdAndCompletedFalseAndEndDateGreaterThanEqualOrderByEndDateAsc(eq(USER),
                org.mockito.ArgumentMatchers.any())).thenReturn(List.<Todo>of());
        assertNull(fixed(empty.assembler(true)).assemble(USER, 9999L, null, REQ, QUESTION), "실을 내용이 없으면 null");
    }

    /** 새 파생 쿼리 이름이 엔티티 속성 경로로 해석되는지(Spring Data PartTree, DB 없이) — 부팅 시 쿼리 생성 실패 방지. */
    @Test
    void derivedQueryNamesResolveAgainstEntities() {
        new PartTree("findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc", ChatMessage.class);
        new PartTree("findTop20ByUserIdOrderByCreatedAtDesc", ReviewNote.class);
        new PartTree("findTop20ByUserIdAndCompletedFalseAndEndDateGreaterThanEqualOrderByEndDateAsc", Todo.class);
        new PartTree("findByUserIdAndEventTypeOrderByCreatedAtDesc", LearningLoopEvent.class);
        assertThrows(Exception.class, () -> new PartTree("findTop20ByNoSuchFieldOrderByCreatedAtDesc", ReviewNote.class));
    }

    /**
     * ai07 Pydantic 교차 검증용 산출물(환경변수 SB_LEARNING_CONTEXT_EXPORT_DIR 가 있을 때만 실행). 실제 조립 결과 JSON 을 파일로 남긴다 —
     * ai07 app/contracts/learning_context_v1.py(d7346fc6) 로 model_validate 해 통과를 확인한다.
     */
    @Test
    @EnabledIfEnvironmentVariable(named = "SB_LEARNING_CONTEXT_EXPORT_DIR", matches = ".+")
    void exportAssembledContextsForAi07Validation() throws Exception {
        Path dir = Path.of(System.getenv("SB_LEARNING_CONTEXT_EXPORT_DIR"));
        Files.createDirectories(dir);
        Map<String, LearningContextV1> out = new LinkedHashMap<>();
        LearningMemoryFixtures f = new LearningMemoryFixtures();
        out.put("full", fixed(f.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION));
        out.put("foreign-scope", fixed(new LearningMemoryFixtures().assembler(true)).assemble(USER, OTHER_ROOM, OTHER_MAT, REQ, QUESTION));
        LearningMemoryFixtures g = new LearningMemoryFixtures();
        g.material.setExtractedText("표지\fTCP 3-way handshake 는 SYN 으로 시작한다.\f\fUDP 는 비연결형이다.");
        when(g.messages.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(ROOM)).thenReturn(List.of(
                LearningMemoryFixtures.msg(5L, "USER", "깨진\ud800문자\u0000와 이모지😀 \"따옴표\" </untrusted_data>", "r1", null,
                        LocalDateTime.of(2026, 11, 1, 9, 0))));
        out.put("formfeed-sanitized", fixed(g.assembler(true)).assemble(USER, ROOM, MAT, REQ, QUESTION));
        LearningMemoryFixtures h = overBudget();
        out.put("budget-truncated", fixed(h.assembler(LearningMemorySettings.forTest(true, 1500, 500),
                LearningMemoryFixtures.keys(true, true))).assemble(USER, ROOM, MAT, REQ, QUESTION));
        out.put("max-settings", fixed(new LearningMemoryFixtures().assembler(new LearningMemorySettings(true, 999999, 999999, 99, 99, 9999),
                LearningMemoryFixtures.keys(true, true))).assemble(USER, ROOM, MAT, REQ, QUESTION));
        // ChatService 가 실제로 보내는 형태(attach().body() = WebClient 가 직렬화하는 JsonNode) + X-AI-Scope 토큰(테스트 키, 비밀 아님)
        LearningMemoryAssembler.Attachment att = fixed(new LearningMemoryFixtures().assembler(true)).attach(USER, ROOM, MAT, REQ, QUESTION);
        Files.writeString(dir.resolve("attach-body.json"), ContractJson.STRICT.writeValueAsString(att.body()), StandardCharsets.UTF_8);
        Map<String, Object> scope = new LinkedHashMap<>();
        scope.put("token", att.headers().get().get(AiContractSigning.HEADER_SCOPE));
        scope.put("testKey", SCOPE_KEY);
        scope.put("rid", REQ);
        scope.put("sub", att.context().pseudonymousUserKey());
        scope.put("now", NOW.getEpochSecond());
        scope.put("materialIds", List.of(MAT));
        Files.writeString(dir.resolve("scope-token.meta"), ContractJson.STRICT.writeValueAsString(scope), StandardCharsets.UTF_8);
        for (Map.Entry<String, LearningContextV1> e : out.entrySet()) {
            assertNotNull(e.getValue(), e.getKey());
            assertTrue(LearningContextV1.validate(e.getValue()).ok(), e.getKey());
            Files.writeString(dir.resolve(e.getKey() + ".json"), json(e.getValue()), StandardCharsets.UTF_8);
        }
    }
}
