package com.studybridge.api.service;

import com.studybridge.api.dto.AdminDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import com.studybridge.api.security.stomp.GroupAccessRevokedEvent;
import com.studybridge.api.security.stomp.UserAccessRevokedEvent;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

/**
 * 탈퇴·강퇴·그룹 삭제·계정 정지가 성공하면 실시간(STOMP) 세션 차단 이벤트를 발행하고, 실패하면 발행하지 않는다.
 * (이벤트는 커밋 뒤 StompSessionRevoker 가 처리한다 — 통합 테스트 StompSecurityIntegrationTest 참고.)
 */
class GroupAccessRevocationEventTest {

    private static final long LEADER = 1L;
    private static final long MEMBER = 2L;
    private static final long GROUP = 10L;

    private GroupStudyRepository groups;
    private GroupStudyMemberRepository members;
    private GroupStudyJoinApplicationRepository applications;
    private UserRepository users;
    private ApplicationEventPublisher publisher;
    private GroupStudyService service;
    private GroupStudy group;

    @BeforeEach
    void setUp() {
        groups = mock(GroupStudyRepository.class);
        members = mock(GroupStudyMemberRepository.class);
        applications = mock(GroupStudyJoinApplicationRepository.class);
        users = mock(UserRepository.class);
        publisher = mock(ApplicationEventPublisher.class);
        GroupStudyQuizSessionRepository sessions = mock(GroupStudyQuizSessionRepository.class);
        when(sessions.findIdsByGroupStudyId(anyLong())).thenReturn(List.of());
        service = new GroupStudyService(groups, members, applications, mock(GroupStudyAttendanceRepository.class),
                mock(GroupChatMessageRepository.class), sessions, mock(GroupStudyQuizSessionAnswerRepository.class),
                users, mock(S3Service.class), mock(GroupRankingService.class));
        service.setApplicationEventPublisher(publisher);

        User leader = User.builder().id(LEADER).displayName("방장").build();
        group = GroupStudy.builder().id(GROUP).title("t").description("d").capacity(5).currentCount(2)
                .isPublic(true).leader(leader).status(GroupStudyStatus.RECRUITING).build();
        when(groups.findById(GROUP)).thenReturn(Optional.of(group));
        when(groups.save(any(GroupStudy.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    private void memberExists() {
        GroupStudyMember member = GroupStudyMember.builder().groupStudy(group)
                .user(User.builder().id(MEMBER).build()).role(GroupStudyRole.MEMBER).status(GroupStudyMemberStatus.JOINED).build();
        when(members.findByGroupStudyIdAndUserIdAndStatus(GROUP, MEMBER, GroupStudyMemberStatus.JOINED)).thenReturn(Optional.of(member));
    }

    @Test
    void kick_publishesKickedEvent() {
        memberExists();
        service.kickMember(LEADER, GROUP, MEMBER);
        verify(publisher).publishEvent(GroupAccessRevokedEvent.kicked(GROUP, MEMBER));
    }

    @Test
    void kick_byNonLeader_publishesNothing() {
        memberExists();
        assertThrows(SecurityException.class, () -> service.kickMember(MEMBER, GROUP, MEMBER));
        verifyNoInteractions(publisher);
    }

    @Test
    void leave_publishesLeftEvent() {
        memberExists();
        service.leaveGroupStudy(MEMBER, GROUP);
        verify(publisher).publishEvent(GroupAccessRevokedEvent.left(GROUP, MEMBER));
    }

    @Test
    void cancellingPendingApplication_publishesNothing() {
        when(applications.findByGroupStudyIdAndUserIdAndStatus(GROUP, MEMBER, GroupStudyJoinStatus.PENDING))
                .thenReturn(Optional.of(GroupStudyJoinApplication.builder().id(3L).build()));
        service.leaveGroupStudy(MEMBER, GROUP);
        verifyNoInteractions(publisher);
    }

    @Test
    void deleteGroup_publishesGroupDeletedEvent() {
        service.deleteGroupStudy(LEADER, GROUP);
        verify(publisher).publishEvent(GroupAccessRevokedEvent.groupDeleted(GROUP));
    }

    @Test
    void forceDeleteGroup_publishesGroupDeletedEvent() {
        service.deleteGroupStudyForce(GROUP);
        verify(publisher).publishEvent(GroupAccessRevokedEvent.groupDeleted(GROUP));
    }

    @Test
    void serviceBuiltWithoutPublisher_stillWorks() {
        GroupStudyService plain = new GroupStudyService(groups, members, applications, mock(GroupStudyAttendanceRepository.class),
                mock(GroupChatMessageRepository.class), mock(GroupStudyQuizSessionRepository.class),
                mock(GroupStudyQuizSessionAnswerRepository.class), users, mock(S3Service.class), mock(GroupRankingService.class));
        memberExists();
        plain.kickMember(LEADER, GROUP, MEMBER);
        verify(members).delete(any(GroupStudyMember.class));
    }

    @Test
    void adminSuspendAndBan_publishAccountRevokedEvent() {
        AdminService admin = new AdminService(users, mock(BlogService.class), mock(GroupStudyReportService.class), service);
        admin.setApplicationEventPublisher(publisher);
        when(users.findById(MEMBER)).thenAnswer(inv -> Optional.of(User.builder().id(MEMBER).displayName("m").role("USER").build()));
        when(users.save(any(User.class))).thenAnswer(inv -> inv.getArgument(0));

        AdminDTO.UserSuspendRequest suspend = new AdminDTO.UserSuspendRequest();
        suspend.setDays(3);
        suspend.setReason("spam");
        admin.suspendUser(MEMBER, suspend);

        AdminDTO.UserBanRequest ban = new AdminDTO.UserBanRequest();
        ban.setReason("abuse");
        admin.banUserPermanently(MEMBER, ban);

        verify(publisher, times(2)).publishEvent(new UserAccessRevokedEvent(MEMBER));
    }
}
