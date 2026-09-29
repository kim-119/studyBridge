package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.dto.GroupStudyQuizDTO;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMaterial;
import com.studybridge.api.entity.GroupStudyQuiz;
import com.studybridge.api.entity.GroupStudyQuizSessionStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyMaterialRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizQuestionRepository;
import com.studybridge.api.repository.GroupStudyQuizRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.mockito.Mockito;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * 방장 전용 Material/Quiz 삭제(D1~D5) + AI07 degraded 판정(Q9) 단위 테스트.
 *  · 권한의 authoritative source 는 GroupStudy.leader. 요청자가 보낸 role/isHost 는 존재하지 않는다.
 *  · IDOR: 다른 그룹의 리소스 id 는 404 로 거절(존재 유추 방지).
 */
class GroupStudyMaterialDeleteAuthorizationTest {

    private static final long LEADER_A = 1L;
    private static final long MEMBER_A = 2L;
    private static final long LEADER_B = 3L;
    private static final long GROUP_A = 10L;
    private static final long GROUP_B = 20L;
    private static final long MAT_A = 100L;
    private static final long MAT_B = 200L;
    private static final long QUIZ_A = 500L;
    private static final long QUIZ_B = 600L;

    private GroupStudyMaterialRepository materials;
    private GroupStudyQuizRepository quizzes;
    private GroupStudyQuizSessionRepository sessions;
    private GroupStudyQuizSessionAnswerRepository answers;
    private S3Service s3;
    private GroupStudyMaterialService service;

    @BeforeEach
    void setUp() {
        GroupStudy a = GroupStudy.builder().id(GROUP_A).leader(User.builder().id(LEADER_A).build()).build();
        GroupStudy b = GroupStudy.builder().id(GROUP_B).leader(User.builder().id(LEADER_B).build()).build();
        GroupStudyRepository groups = mock(GroupStudyRepository.class);
        Mockito.when(groups.findById(GROUP_A)).thenReturn(Optional.of(a));
        Mockito.when(groups.findById(GROUP_B)).thenReturn(Optional.of(b));

        materials = mock(GroupStudyMaterialRepository.class);
        Mockito.when(materials.findById(MAT_A)).thenReturn(Optional.of(
                GroupStudyMaterial.builder().id(MAT_A).groupStudy(a).s3Key("group/a.pdf").build()));
        Mockito.when(materials.findById(MAT_B)).thenReturn(Optional.of(
                GroupStudyMaterial.builder().id(MAT_B).groupStudy(b).s3Key("group/b.pdf").build()));

        quizzes = mock(GroupStudyQuizRepository.class);
        Mockito.when(quizzes.findById(QUIZ_A)).thenReturn(Optional.of(GroupStudyQuiz.builder().id(QUIZ_A).groupStudy(a).build()));
        Mockito.when(quizzes.findById(QUIZ_B)).thenReturn(Optional.of(GroupStudyQuiz.builder().id(QUIZ_B).groupStudy(b).build()));

        sessions = mock(GroupStudyQuizSessionRepository.class);
        Mockito.when(sessions.findIdsByQuizId(ArgumentMatchers.anyLong())).thenReturn(List.of());
        answers = mock(GroupStudyQuizSessionAnswerRepository.class);
        s3 = mock(S3Service.class);

        service = new GroupStudyMaterialService(materials, groups, mock(GroupStudyMemberRepository.class), quizzes,
                mock(GroupStudyQuizQuestionRepository.class), sessions, answers, mock(UserRepository.class), s3,
                AiFailoverExecutor.single(mock(WebClient.class)), new ObjectMapper());
    }

    @Test
    void d1_owner_deletes_material_and_s3_object() {
        service.deleteMaterial(LEADER_A, GROUP_A, MAT_A);
        verify(materials).delete(any(GroupStudyMaterial.class));
        verify(s3).deleteFile("group/a.pdf"); // 트랜잭션 동기화가 없는 단위 테스트에서는 즉시 실행
    }

    @Test
    void d2_member_material_delete_is_403() {
        assertThrows(SecurityException.class, () -> service.deleteMaterial(MEMBER_A, GROUP_A, MAT_A));
        verify(materials, never()).delete(any(GroupStudyMaterial.class));
        verify(s3, never()).deleteFile(ArgumentMatchers.anyString());
    }

    @Test
    void d3_owner_deletes_quiz_and_purges_completed_sessions() {
        Mockito.when(sessions.existsByQuizIdAndStatusIn(ArgumentMatchers.eq(QUIZ_A), any())).thenReturn(false);
        Mockito.when(sessions.findIdsByQuizId(QUIZ_A)).thenReturn(List.of(7L, 8L));
        service.deleteQuiz(LEADER_A, GROUP_A, QUIZ_A);
        verify(answers).deleteBySessionIdIn(List.of(7L, 8L));
        verify(sessions).deleteByQuizId(QUIZ_A);
        verify(quizzes).delete(any(GroupStudyQuiz.class));
    }

    @Test
    void d4_member_quiz_delete_is_403() {
        assertThrows(SecurityException.class, () -> service.deleteQuiz(MEMBER_A, GROUP_A, QUIZ_A));
        verify(quizzes, never()).delete(any(GroupStudyQuiz.class));
    }

    @Test
    void d5_cross_group_owner_cannot_delete_other_groups_resources() {
        // Group A 방장이 Group B 자료/퀴즈 id 를 A 경로로 넣음 → 404
        assertThrows(NoSuchElementException.class, () -> service.deleteMaterial(LEADER_A, GROUP_A, MAT_B));
        assertThrows(NoSuchElementException.class, () -> service.deleteQuiz(LEADER_A, GROUP_A, QUIZ_B));
        // Group A 방장이 Group B 경로로 직접 요청 → 403(B 의 방장이 아님)
        assertThrows(SecurityException.class, () -> service.deleteMaterial(LEADER_A, GROUP_B, MAT_B));
        assertThrows(SecurityException.class, () -> service.deleteQuiz(LEADER_A, GROUP_B, QUIZ_B));
        verify(materials, never()).delete(any(GroupStudyMaterial.class));
        verify(quizzes, never()).delete(any(GroupStudyQuiz.class));
        verify(s3, never()).deleteFile(ArgumentMatchers.anyString());
    }

    @Test
    void quiz_delete_blocked_while_session_active_409() {
        Mockito.when(sessions.existsByQuizIdAndStatusIn(ArgumentMatchers.eq(QUIZ_A),
                ArgumentMatchers.eq(List.of(GroupStudyQuizSessionStatus.QUESTION, GroupStudyQuizSessionStatus.REVEALING))))
                .thenReturn(true);
        assertThrows(IllegalStateException.class, () -> service.deleteQuiz(LEADER_A, GROUP_A, QUIZ_A));
        verify(quizzes, never()).delete(any(GroupStudyQuiz.class));
    }

    @Test
    void missing_group_or_resource_is_404() {
        assertThrows(NoSuchElementException.class, () -> service.deleteMaterial(LEADER_A, 999L, MAT_A));
        assertThrows(NoSuchElementException.class, () -> service.deleteMaterial(LEADER_A, GROUP_A, 999L));
        assertThrows(NoSuchElementException.class, () -> service.deleteQuiz(LEADER_A, GROUP_A, 999L));
    }

    // ── Q9: AI07 DEGRADED/FAILED 구조화 판정 ──────────────────────────────

    private static GroupStudyQuizDTO.AIQuizResponse resp(String title, String question) {
        return GroupStudyQuizDTO.AIQuizResponse.builder()
                .quizTitle(title)
                .questions(List.of(GroupStudyQuizDTO.AIQuestion.builder()
                        .question(question).options(List.of("a", "b", "c", "d")).correctAnswer(1).build()))
                .build();
    }

    @Test
    void q9_structured_status_drives_unusable_decision() {
        GroupStudyQuizDTO.AIQuizResponse ok = resp("자료 기반 퀴즈", "PDF 3장의 핵심은?");
        ok.setSuccess(true); ok.setStatus("OK");
        assertNull(GroupStudyMaterialService.unusableAiQuizReason(ok));

        GroupStudyQuizDTO.AIQuizResponse failed = resp("x", "y");
        failed.setSuccess(false); failed.setErrorCode("QUIZ_GENERATE_FAILED");
        assertEquals("SUCCESS_FALSE", GroupStudyMaterialService.unusableAiQuizReason(failed));

        GroupStudyQuizDTO.AIQuizResponse degraded = resp("x", "y");
        degraded.setSuccess(true); degraded.setStatus("DEGRADED");
        assertEquals("STATUS_DEGRADED", GroupStudyMaterialService.unusableAiQuizReason(degraded));

        GroupStudyQuizDTO.AIQuizResponse flag = resp("x", "y");
        flag.setSchemaVersion("quiz.v2"); flag.setDegraded(true);
        assertEquals("DEGRADED_FLAG", GroupStudyMaterialService.unusableAiQuizReason(flag));

        GroupStudyQuizDTO.AIQuizResponse fb = resp("x", "y");
        fb.setSuccess(true); fb.setFallbackUsed(true);
        assertEquals("FALLBACK_USED", GroupStudyMaterialService.unusableAiQuizReason(fb));

        // 구조화 필드가 있으면 제목에 "기본 안내형" 이 들어가도 문자열로 판정하지 않는다.
        GroupStudyQuizDTO.AIQuizResponse titled = resp("자료 기반 학습 퀴즈 (기본 안내형)", "PDF 기반 문제");
        titled.setSuccess(true); titled.setStatus("OK");
        assertNull(GroupStudyMaterialService.unusableAiQuizReason(titled));
    }

    @Test
    void q9_legacy_response_without_structured_fields_still_rejects_placeholder() {
        GroupStudyQuizDTO.AIQuizResponse legacy = resp("자료 기반 학습 퀴즈 (기본 안내형)", "다음 중 효과적인 학습 방법으로 알려진 것은?");
        assertEquals("LEGACY_PLACEHOLDER_MARKER", GroupStudyMaterialService.unusableAiQuizReason(legacy));
        GroupStudyQuizDTO.AIQuizResponse legacyOk = resp("자료 기반 퀴즈", "PDF 2장의 정의는?");
        assertNull(GroupStudyMaterialService.unusableAiQuizReason(legacyOk));
    }

    @Test
    void quiz_v2_correct_option_ids_resolve_to_index_and_out_of_range_is_null() {
        GroupStudyQuizDTO.AIQuestion v2 = GroupStudyQuizDTO.AIQuestion.builder()
                .question("q").options(List.of("a", "b", "c", "d"))
                .optionIds(List.of("opt-1", "opt-2", "opt-3", "opt-4")).correctOptionIds(List.of("opt-3")).build();
        assertEquals(2, GroupStudyMaterialService.resolveCorrectAnswer(v2));
        GroupStudyQuizDTO.AIQuestion legacy = GroupStudyQuizDTO.AIQuestion.builder()
                .question("q").options(List.of("a", "b")).correctAnswer(1).build();
        assertEquals(1, GroupStudyMaterialService.resolveCorrectAnswer(legacy));
        GroupStudyQuizDTO.AIQuestion bad = GroupStudyQuizDTO.AIQuestion.builder()
                .question("q").options(List.of("a", "b")).correctAnswer(5).build();
        assertNull(GroupStudyMaterialService.resolveCorrectAnswer(bad));
        GroupStudyQuizDTO.AIQuestion none = GroupStudyQuizDTO.AIQuestion.builder()
                .question("q").options(List.of("a", "b")).build();
        assertNull(GroupStudyMaterialService.resolveCorrectAnswer(none));
    }
}
