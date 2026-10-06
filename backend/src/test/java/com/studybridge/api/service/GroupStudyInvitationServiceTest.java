package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.dto.GroupStudyInvitationDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.GroupStudyInvitationRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * 비공개 그룹 초대 링크 계약.
 *  · 생성/폐기: 방장(LEADER)만. MEMBER·비회원은 SecurityException(403). 재생성 시 기존 활성 링크 폐기.
 *  · 토큰: 43자 base64url(32바이트 SecureRandom), 매번 다름.
 *  · 수락: 유효 토큰 → 즉시 가입(joinImmediately) + usedCount+1. 무효/만료/폐기/횟수초과 → IllegalArgumentException(400).
 *    이미 멤버 → 멱등(가입 호출 없음, usedCount 불변). 종료된 그룹 → 거부.
 */
class GroupStudyInvitationServiceTest {

    private static final long LEADER = 1L;
    private static final long MEMBER = 2L;
    private static final long STRANGER = 3L;
    private static final long GROUP = 10L;

    private GroupStudyInvitationRepository invitations;
    private GroupStudyRepository groups;
    private GroupStudyMemberRepository members;
    private UserRepository users;
    private GroupStudyService groupStudyService;
    private GroupStudyInvitationService service;
    private GroupStudy group;

    private static User user(long id) {
        User u = new User();
        u.setId(id);
        u.setDisplayName("u" + id);
        return u;
    }

    @BeforeEach
    void setUp() {
        invitations = mock(GroupStudyInvitationRepository.class);
        groups = mock(GroupStudyRepository.class);
        members = mock(GroupStudyMemberRepository.class);
        users = mock(UserRepository.class);
        groupStudyService = mock(GroupStudyService.class);
        service = new GroupStudyInvitationService(invitations, groups, members, users, groupStudyService);

        group = GroupStudy.builder().id(GROUP).title("비공개방").description("d").capacity(5).currentCount(1)
                .isPublic(false).leader(user(LEADER)).status(GroupStudyStatus.RECRUITING).build();
        when(groups.findById(GROUP)).thenReturn(Optional.of(group));
        when(users.findById(anyLong())).thenAnswer(inv -> Optional.of(user(inv.getArgument(0))));
        when(invitations.save(any(GroupStudyInvitation.class))).thenAnswer(inv -> { GroupStudyInvitation i = inv.getArgument(0); if (i.getId() == null) i.setId(100L); return i; });
        when(invitations.existsByToken(anyString())).thenReturn(false);
        when(invitations.findByGroupStudyIdAndActiveTrueOrderByCreatedAtDesc(GROUP)).thenReturn(List.of());
        when(groupStudyService.getGroupStudy(GROUP)).thenReturn(GroupStudyDTO.Response.builder().id(GROUP).title("비공개방").isPublic(false).build());
    }

    private GroupStudyInvitation validInvitation() {
        return GroupStudyInvitation.builder().id(100L).groupStudy(group).token("tok").createdBy(user(LEADER))
                .expiresAt(LocalDateTime.now().plusDays(7)).active(true).usedCount(0).maxUses(null).build();
    }

    @Test
    void create_leader_ok_tokenIsStrongAndUnique() {
        GroupStudyInvitationDTO.Response r1 = service.create(LEADER, GROUP, null);
        GroupStudyInvitationDTO.Response r2 = service.create(LEADER, GROUP, GroupStudyInvitationDTO.CreateRequest.builder().expiresInDays(3).maxUses(5).build());
        assertEquals(43, r1.getToken().length());
        assertTrue(r1.getToken().matches("[A-Za-z0-9_-]+"));
        assertNotEquals(r1.getToken(), r2.getToken());
        assertEquals("/groups/invite/" + r1.getToken(), r1.getInvitePath());
        assertEquals(5, r2.getMaxUses());
        assertTrue(r2.getExpiresAt().isAfter(LocalDateTime.now().plusDays(2)));
        assertTrue(r1.isActive());
    }

    @Test
    void create_regenerate_deactivatesPreviousActive() {
        GroupStudyInvitation prev = validInvitation();
        when(invitations.findByGroupStudyIdAndActiveTrueOrderByCreatedAtDesc(GROUP)).thenReturn(List.of(prev));
        service.create(LEADER, GROUP, null);
        assertFalse(prev.isActive());
        verify(invitations).saveAll(List.of(prev));
    }

    @Test
    void create_member_forbidden_403() {
        assertThrows(SecurityException.class, () -> service.create(MEMBER, GROUP, null));
        assertThrows(SecurityException.class, () -> service.create(STRANGER, GROUP, null));
        verify(invitations, never()).save(any());
    }

    @Test
    void create_invalidParams_400() {
        assertThrows(IllegalArgumentException.class, () -> service.create(LEADER, GROUP, GroupStudyInvitationDTO.CreateRequest.builder().expiresInDays(0).build()));
        assertThrows(IllegalArgumentException.class, () -> service.create(LEADER, GROUP, GroupStudyInvitationDTO.CreateRequest.builder().expiresInDays(31).build()));
        assertThrows(IllegalArgumentException.class, () -> service.create(LEADER, GROUP, GroupStudyInvitationDTO.CreateRequest.builder().maxUses(0).build()));
    }

    @Test
    void revoke_leaderOnly_andMustBelongToGroup() {
        GroupStudyInvitation inv = validInvitation();
        when(invitations.findById(100L)).thenReturn(Optional.of(inv));
        assertThrows(SecurityException.class, () -> service.revoke(MEMBER, GROUP, 100L));
        service.revoke(LEADER, GROUP, 100L);
        assertFalse(inv.isActive());

        GroupStudy other = GroupStudy.builder().id(99L).leader(user(LEADER)).isPublic(false).build();
        GroupStudyInvitation foreign = validInvitation(); foreign.setGroupStudy(other);
        when(invitations.findById(101L)).thenReturn(Optional.of(foreign));
        assertThrows(SecurityException.class, () -> service.revoke(LEADER, GROUP, 101L));
    }

    @Test
    void accept_validToken_joinsImmediately_andCountsUse() {
        GroupStudyInvitation inv = validInvitation();
        when(invitations.findByToken("tok")).thenReturn(Optional.of(inv));
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, STRANGER, GroupStudyMemberStatus.JOINED)).thenReturn(false);

        GroupStudyDTO.Response res = service.accept(STRANGER, "tok", null);

        assertEquals(GROUP, res.getId());
        ArgumentCaptor<String> intro = ArgumentCaptor.forClass(String.class);
        verify(groupStudyService).joinImmediately(any(User.class), eq(group), intro.capture(), eq(null), eq(null));
        assertEquals("초대 링크로 참여", intro.getValue());
        assertEquals(1, inv.getUsedCount());
    }

    @Test
    void accept_alreadyMember_idempotent_noDoubleJoin() {
        GroupStudyInvitation inv = validInvitation();
        when(invitations.findByToken("tok")).thenReturn(Optional.of(inv));
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, MEMBER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
        service.accept(MEMBER, "tok", null);
        verify(groupStudyService, never()).joinImmediately(any(), any(), any(), any(), any());
        assertEquals(0, inv.getUsedCount());
    }

    @Test
    void accept_invalidToken_400() {
        when(invitations.findByToken("nope")).thenReturn(Optional.empty());
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "nope", null));
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "x".repeat(65), null));
        verify(groupStudyService, never()).joinImmediately(any(), any(), any(), any(), any());
    }

    @Test
    void accept_expired_inactive_exhausted_completed_rejected() {
        GroupStudyInvitation expired = validInvitation(); expired.setExpiresAt(LocalDateTime.now().minusMinutes(1));
        when(invitations.findByToken("expired")).thenReturn(Optional.of(expired));
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "expired", null));

        GroupStudyInvitation inactive = validInvitation(); inactive.setActive(false);
        when(invitations.findByToken("inactive")).thenReturn(Optional.of(inactive));
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "inactive", null));

        GroupStudyInvitation exhausted = validInvitation(); exhausted.setMaxUses(2); exhausted.setUsedCount(2);
        when(invitations.findByToken("exhausted")).thenReturn(Optional.of(exhausted));
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "exhausted", null));

        GroupStudyInvitation ok = validInvitation();
        when(invitations.findByToken("done")).thenReturn(Optional.of(ok));
        group.setStatus(GroupStudyStatus.COMPLETED);
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "done", null));
        verify(groupStudyService, never()).joinImmediately(any(), any(), any(), any(), any());
    }

    @Test
    void accept_nicknameRuleEnabled_requiresNickname() {
        group.setNicknameRuleEnabled(true);
        group.setNicknameRule("학번-이름");
        GroupStudyInvitation inv = validInvitation();
        when(invitations.findByToken("tok")).thenReturn(Optional.of(inv));
        assertThrows(IllegalArgumentException.class, () -> service.accept(STRANGER, "tok", null));
        service.accept(STRANGER, "tok", GroupStudyInvitationDTO.AcceptRequest.builder().nickname("20261234-홍길동").build());
        verify(groupStudyService).joinImmediately(any(User.class), eq(group), anyString(), eq(null), eq("20261234-홍길동"));
    }

    @Test
    void preview_reportsValidityAndMembership() {
        GroupStudyInvitation inv = validInvitation();
        when(invitations.findByToken("tok")).thenReturn(Optional.of(inv));
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, MEMBER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
        GroupStudyInvitationDTO.Preview p = service.preview(MEMBER, "tok");
        assertTrue(p.isValid()); assertTrue(p.isAlreadyMember()); assertEquals("비공개방", p.getTitle()); assertEquals("u1", p.getLeaderName());

        when(invitations.findByToken("nope")).thenReturn(Optional.empty());
        GroupStudyInvitationDTO.Preview bad = service.preview(STRANGER, "nope");
        assertFalse(bad.isValid()); assertNotNull(bad.getReason());
    }

    @Test
    void listActive_filtersUnusable_andLeaderOnly() {
        GroupStudyInvitation ok = validInvitation();
        GroupStudyInvitation expired = validInvitation(); expired.setId(101L); expired.setExpiresAt(LocalDateTime.now().minusDays(1));
        when(invitations.findByGroupStudyIdAndActiveTrueOrderByCreatedAtDesc(GROUP)).thenReturn(List.of(ok, expired));
        assertEquals(1, service.listActive(LEADER, GROUP).size());
        assertThrows(SecurityException.class, () -> service.listActive(MEMBER, GROUP));
    }
}
