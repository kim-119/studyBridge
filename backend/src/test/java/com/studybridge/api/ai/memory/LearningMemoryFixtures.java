package com.studybridge.api.ai.memory;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.studybridge.api.ai.contract.v1.AiSigningKeys;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialMemo;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.MaterialSummary;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import com.studybridge.api.repository.LearningLoopEventRepository;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.service.MaterialQuizScoreService;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * Learning Memory 테스트 픽스처(전부 Mockito 저장소, PG 불필요).
 *  · USER(55) 소유: 방 ROOM(201), 자료 MAT(345, "[Page N]" 표식 원문), 승인 요약·메모·퀴즈 점수·오답노트(승인 1 + 미승인 1)·할 일.
 *  · OTHER(66) 소유: 방 OTHER_ROOM(202), 자료 OTHER_MAT(999) — 본문에 OTHER_CANARY. 어떤 경우에도 USER 컨텍스트에 실리면 안 된다.
 *  · 미승인·레거시 AI 답변/개념에는 *_CANARY 문자열을 넣어 누출을 문자열 검색으로 확인한다.
 */
public final class LearningMemoryFixtures {

    public static final long USER = 55L;
    public static final long OTHER = 66L;
    public static final long ROOM = 201L;
    public static final long OTHER_ROOM = 202L;
    public static final long MAT = 345L;
    public static final long OTHER_MAT = 999L;
    public static final String REQ = "req-mem-0001";
    public static final String QUESTION = "TCP 3-way handshake 단계는?";
    public static final String SCOPE_KEY = "scope-signing-key-for-learning-memory-tests-0001";
    public static final String PSEUDONYM_SECRET = "pseudonym-secret-for-learning-memory-tests-0001";
    public static final String LEGACY_CANARY = "LEGACYCANARY";
    public static final String REJECTED_CANARY = "REJECTEDCANARY";
    public static final String UNAPPROVED_CONCEPT_CANARY = "UNAPPROVEDCONCEPTCANARY";
    public static final String UNAPPROVED_SUMMARY_CANARY = "UNAPPROVEDSUMMARYCANARY";
    public static final String OTHER_CANARY = "OTHERUSERCANARY";
    public static final String PAGE2 = "TCP 3-way handshake 는 SYN, SYN-ACK, ACK 세 단계로 연결을 수립한다. 이때 순서 번호를 교환한다.";
    public static final String EXTRACTED = "[Page 1]\n네트워크 개론 강의 자료. OSI 7계층과 TCP/IP 모델을 다룬다.\n\n[Page 2]\n" + PAGE2
            + "\n\n[Page 3]\nUDP 는 비연결형 프로토콜이며 신뢰성을 보장하지 않는다.";

    public final AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
    public final ChatMessageRepository messages = mock(ChatMessageRepository.class);
    public final MaterialRepository materials = mock(MaterialRepository.class);
    public final MaterialSummaryRepository summaries = mock(MaterialSummaryRepository.class);
    public final MaterialMemoRepository memos = mock(MaterialMemoRepository.class);
    public final ReviewNoteRepository reviewNotes = mock(ReviewNoteRepository.class);
    public final MaterialQuizRepository quizzes = mock(MaterialQuizRepository.class);
    public final MaterialQuizScoreService scores = mock(MaterialQuizScoreService.class);
    public final LearningLoopEventRepository events = mock(LearningLoopEventRepository.class);
    public final TodoRepository todos = mock(TodoRepository.class);

    public final Material material;
    public final MaterialSummary summary;
    public final ReviewNote approvedNote;
    public final ReviewNote unapprovedNote;

    public LearningMemoryFixtures() {
        LocalDateTime t0 = LocalDateTime.of(2026, 11, 3, 10, 0);
        AgentChatRoom room = room(ROOM, USER);
        AgentChatRoom otherRoom = room(OTHER_ROOM, OTHER);
        when(rooms.findById(ROOM)).thenReturn(Optional.of(room));
        when(rooms.findById(OTHER_ROOM)).thenReturn(Optional.of(otherRoom));
        // 방 메시지는 생성자 끝의 thenAnswer(최신순: 이번 질문 → 승인 답 → 레거시 답 → 거절 답(가상) → 이전 질문)로 스텁한다.

        material = Material.builder().materialId(MAT).userId(USER).title("네트워크").materialType(MaterialType.PDF)
                .extractedText(EXTRACTED).uploadedAt(t0).updatedAt(t0).build();
        Material otherMaterial = Material.builder().materialId(OTHER_MAT).userId(OTHER).title("남의 자료").materialType(MaterialType.PDF)
                .extractedText("[Page 1]\n" + OTHER_CANARY + " TCP handshake 비밀 자료").uploadedAt(t0).build();
        when(materials.findById(MAT)).thenReturn(Optional.of(material));
        when(materials.findById(OTHER_MAT)).thenReturn(Optional.of(otherMaterial));

        summary = MaterialSummary.builder().summaryId(5L).overview("TCP 는 연결 지향 프로토콜이다.")
                .coreContents("{\"key_points\":[\"3-way handshake\",\"흐름 제어\"]}").qualityStatus("APPROVED").createdAt(t0).build();
        when(summaries.findByMaterial_MaterialId(MAT)).thenReturn(Optional.of(summary));
        when(summaries.findByMaterial_MaterialId(OTHER_MAT)).thenReturn(Optional.of(MaterialSummary.builder().summaryId(6L)
                .overview(OTHER_CANARY).qualityStatus("APPROVED").createdAt(t0).build()));
        when(memos.findByMaterial_MaterialId(MAT)).thenReturn(Optional.of(MaterialMemo.builder().memoId(7L)
                .content("시험 범위: 4장까지. handshake 순서 꼭 외우기").createdAt(t0).updatedAt(t0).build()));
        when(memos.findByMaterial_MaterialId(OTHER_MAT)).thenReturn(Optional.of(MaterialMemo.builder().memoId(8L)
                .content(OTHER_CANARY).createdAt(t0).build()));

        approvedNote = ReviewNote.builder().reviewNoteId(31L).userId(USER).sourceMaterialId(MAT).title("네트워크 오답노트")
                .qualityStatus("APPROVED").wrongCount(3).unansweredCount(1).difficulty("hard")
                .recommendedReviewDate(LocalDate.of(2026, 11, 6)).createdAt(t0)
                .retryJson("[{\"question\":\"q1\",\"concept\":\"3-way handshake\"},{\"question\":\"q2\",\"concept\":\"3-way  handshake\"},"
                        + "{\"question\":\"q3\",\"concept\":\"흐름 제어\"},{\"question\":\"q4\"}]").build();
        unapprovedNote = ReviewNote.builder().reviewNoteId(32L).userId(USER).sourceMaterialId(MAT).title("네트워크 오답노트 2")
                .qualityStatus(null).wrongCount(2).unansweredCount(0).createdAt(t0.minusDays(1))
                .retryJson("[{\"question\":\"q9\",\"concept\":\"" + UNAPPROVED_CONCEPT_CANARY + "\"}]").build();
        when(reviewNotes.findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(USER, MAT)).thenReturn(List.of(approvedNote, unapprovedNote));
        when(reviewNotes.findTop20ByUserIdOrderByCreatedAtDesc(USER)).thenReturn(List.of(approvedNote, unapprovedNote));

        MaterialQuiz quiz = MaterialQuiz.builder().quizId(75L).difficulty("보통").questionCount(10).createdAt(t0).build();
        when(quizzes.findByMaterial_MaterialIdOrderByCreatedAtDesc(MAT)).thenReturn(List.of(quiz));
        when(scores.find(75L, USER)).thenReturn(MaterialQuizScoreService.StoredScore.builder().quizId(75L).userId(USER).score(70)
                .correctCount(7).totalQuestions(10).attempt(2).bestScore(80).submittedAt(t0.plusHours(1)).build());
        when(events.findByUserIdAndEventTypeOrderByCreatedAtDesc(eq(USER), any(), any())).thenReturn(List.of());

        User u = new User();
        u.setId(USER);
        when(todos.findTop20ByUserIdAndCompletedFalseAndEndDateGreaterThanEqualOrderByEndDateAsc(eq(USER), any())).thenReturn(List.of(
                Todo.builder().id(41L).user(u).text("4장 연습문제 풀기").completed(false).endDate(LocalDateTime.of(2026, 11, 5, 23, 59))
                        .createdAt(t0).build(),
                Todo.builder().id(42L).user(u).text("네트워크 오답노트 복습").completed(false).sourceType("REVIEW_NOTE").sourceId(31L)
                        .scheduleDate(LocalDate.of(2026, 11, 6)).endDate(LocalDateTime.of(2026, 11, 6, 23, 59)).createdAt(t0).build()));
        when(messages.findTop20ByAgentChatRoomIdOrderByCreatedAtDescIdDesc(anyLong())).thenAnswer(inv -> {
            long id = inv.getArgument(0);
            if (id == ROOM) {
                return List.of(msg(10L, "USER", QUESTION, REQ, null, t0.plusMinutes(10)),
                        msg(9L, "AI", "승인된 답변: 핸드셰이크는 연결 수립 절차다.", "req-old-1", "APPROVED", t0.plusMinutes(9)),
                        msg(8L, "AI", "레거시 답변 " + LEGACY_CANARY, "req-old-1", null, t0.plusMinutes(8)),
                        msg(7L, "AI", "거절 답변 " + REJECTED_CANARY, "req-old-1", "REJECTED", t0.plusMinutes(7)),
                        msg(6L, "USER", "핸드셰이크가 왜 3번이야?", "req-old-1", null, t0.plusMinutes(6)));
            }
            return id == OTHER_ROOM ? List.of(msg(99L, "USER", "남의 질문 " + OTHER_CANARY, "req-x", null, t0)) : List.of();
        });
    }

    static AgentChatRoom room(long id, long owner) {
        AgentChatRoom r = new AgentChatRoom();
        r.setId(id);
        User u = new User();
        u.setId(owner);
        r.setUser(u);
        return r;
    }

    public static ChatMessage msg(long id, String sender, String content, String requestId, String quality, LocalDateTime at) {
        return ChatMessage.builder().id(id).sender(sender).content(content).requestId(requestId).qualityStatus(quality).createdAt(at)
                .build();
    }

    public static AiSigningKeys keys(boolean scope, boolean pseudonym) {
        return new AiSigningKeys(scope ? SCOPE_KEY : "", "", "", pseudonym ? PSEUDONYM_SECRET : "", "");
    }

    public LearningMemoryAssembler assembler(LearningMemorySettings settings, AiSigningKeys keys) {
        return new LearningMemoryAssembler(settings, keys, new PseudonymousUserKeys(keys), rooms, messages, materials, summaries, memos,
                reviewNotes, quizzes, scores, events, todos);
    }

    public LearningMemoryAssembler assembler(boolean enabled) {
        return assembler(LearningMemorySettings.forTest(enabled), keys(true, true));
    }

    /** 조립기가 쓰는 저장소 전부(OFF 경로 무호출 검증용). */
    public Object[] allMocks() {
        return new Object[]{rooms, messages, materials, summaries, memos, reviewNotes, quizzes, scores, events, todos};
    }
}
