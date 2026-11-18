package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

/**
 * 그룹 삭제 권한 + 비공개 그룹 직접 가입 차단 계약(서버가 정본).
 *  · 삭제: 방장(LEADER=OWNER) 만 허용. MEMBER·비회원은 SecurityException(→403). 존재하지 않는 그룹은 404.
 *    (그룹 역할 enum 은 LEADER/MEMBER 뿐이며 그룹 ADMIN 역할은 없다. 플랫폼 ADMIN 은 별도 /api/admin 경로.)
 *  · 삭제 정합성: 비cascade 자식(퀴즈 세션/답변/채팅) 선정리 → 그룹 삭제 → S3 대표 이미지 제거 → Redis 랭킹 키 정리.
 *  · 비공개 그룹 POST /apply: 토큰 없는 직접 가입은 SecurityException(403), 공개 그룹은 즉시 가입 그대로.
 */
class GroupStudyDeletePermissionTest {

    private static final long LEADER = 1L;
    private static final long MEMBER = 2L;
    private static final long STRANGER = 3L;
    private static final long GROUP = 10L;

    private GroupStudyRepository groups;
    private GroupStudyMemberRepository members;
    private GroupStudyJoinApplicationRepository applications;
    private GroupStudyQuizSessionRepository sessions;
    private GroupStudyQuizSessionAnswerRepository answers;
    private GroupChatMessageRepository chats;
    private S3Service s3;
    private GroupRankingService ranking;
    private UserRepository users;
    private GroupStudyService service;
    private GroupStudy group;

    @BeforeEach
    void setUp() {
        groups = mock(GroupStudyRepository.class);
        members = mock(GroupStudyMemberRepository.class);
        applications = mock(GroupStudyJoinApplicationRepository.class);
        sessions = mock(GroupStudyQuizSessionRepository.class);
        answers = mock(GroupStudyQuizSessionAnswerRepository.class);
        chats = mock(GroupChatMessageRepository.class);
        s3 = mock(S3Service.class);
        ranking = mock(GroupRankingService.class);
        users = mock(UserRepository.class);
        service = new GroupStudyService(groups, members, applications, mock(GroupStudyAttendanceRepository.class),
                chats, sessions, answers, users, s3, ranking);

        User leader = User.builder().id(LEADER).displayName("방장").build();
        group = GroupStudy.builder().id(GROUP).title("t").description("d").capacity(5).currentCount(2)
                .isPublic(true).leader(leader).status(GroupStudyStatus.RECRUITING).coverImageKey("study-images/user_1/x.png").build();
        when(groups.findById(GROUP)).thenReturn(Optional.of(group));
        when(groups.save(any(GroupStudy.class))).thenAnswer(inv -> inv.getArgument(0));
        when(users.findById(anyLong())).thenAnswer(inv -> Optional.of(User.builder().id(inv.getArgument(0)).displayName("u").build()));
        when(members.save(any(GroupStudyMember.class))).thenAnswer(inv -> inv.getArgument(0));
        when(applications.save(any(GroupStudyJoinApplication.class))).thenAnswer(inv -> { GroupStudyJoinApplication a = inv.getArgument(0); a.setId(7L); return a; });
        when(sessions.findIdsByGroupStudyId(GROUP)).thenReturn(List.of(5L));
    }

    @Test
    void delete_owner_ok_cleansChildrenS3AndRedis() {
        service.deleteGroupStudy(LEADER, GROUP);
        verify(answers).deleteBySessionIdIn(List.of(5L));
        verify(sessions).deleteByGroupStudyId(GROUP);
        verify(chats).deleteByGroupStudyId(GROUP);
        verify(groups).delete(group);
        verify(s3).deleteFile("study-images/user_1/x.png");
        verify(ranking).clearRanking(GROUP);
    }

    @Test
    void delete_member_forbidden_403_nothingDeleted() {
        assertThrows(SecurityException.class, () -> service.deleteGroupStudy(MEMBER, GROUP));
        verify(groups, never()).delete(any());
        verify(s3, never()).deleteFile(any());
        verify(ranking, never()).clearRanking(anyLong());
    }

    @Test
    void delete_nonMember_forbidden_403() {
        assertThrows(SecurityException.class, () -> service.deleteGroupStudy(STRANGER, GROUP));
        verify(groups, never()).delete(any());
    }

    @Test
    void delete_missingGroup_404() {
        when(groups.findById(99L)).thenReturn(Optional.empty());
        assertThrows(NoSuchElementException.class, () -> service.deleteGroupStudy(LEADER, 99L));
    }

    @Test
    void delete_s3FailureDoesNotBreakDeletion() {
        doThrow(new RuntimeException("s3 down")).when(s3).deleteFile(any());
        assertDoesNotThrow(() -> service.deleteGroupStudy(LEADER, GROUP));
        verify(groups).delete(group);
        verify(ranking).clearRanking(GROUP);
    }

    @Test
    void apply_privateGroup_withoutInvite_forbidden_403() {
        group.setIsPublic(false);
        GroupStudyDTO.JoinApplyRequest req = new GroupStudyDTO.JoinApplyRequest();
        req.setIntroduction("가입하고 싶어요");
        assertThrows(SecurityException.class, () -> service.applyToGroupStudy(STRANGER, GROUP, req));
        verify(members, never()).save(any());
        verify(applications, never()).save(any());
        assertEquals(2, group.getCurrentCount());
    }

    @Test
    void apply_publicGroup_joinsImmediately_unchanged() {
        GroupStudyDTO.JoinApplyRequest req = new GroupStudyDTO.JoinApplyRequest();
        req.setIntroduction("공개 참여");
        GroupStudyDTO.ApplicationResponse res = service.applyToGroupStudy(STRANGER, GROUP, req);
        assertEquals(GroupStudyJoinStatus.APPROVED, res.getStatus());
        verify(members).save(any(GroupStudyMember.class));
        assertEquals(3, group.getCurrentCount());
    }

    @Test
    void joinImmediately_capacityFull_409() {
        group.setCurrentCount(5);
        assertThrows(IllegalStateException.class,
                () -> service.joinImmediately(User.builder().id(STRANGER).build(), group, "x", null, null));
        verify(members, never()).save(any());
    }
}
