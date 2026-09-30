package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyJoinApplication;
import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.GroupStudyStatus;
import com.studybridge.api.entity.GroupStudyType;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupChatMessageRepository;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyJoinApplicationRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 그룹스터디 운영 정책(스터디 타입·목표시간·가입 질문·닉네임 규칙) 서비스 계약 테스트.
 *  · 생성: GENERAL/CAM, 목표시간 범위, 토글 ON/OFF 정규화, 구 클라이언트(정책 미전송) 기본값
 *  · 수정: 방장만 가능(SecurityException→403), 부분 수정 유지, 토글 OFF 시 문구 null
 *  · 가입: 질문 ON 그룹은 답변 필수, 닉네임 규칙 ON 그룹은 닉네임 필수, OFF 그룹은 기존 플로우 그대로
 *  · 하위 호환: 정책 컬럼이 null 인 기존 row 도 응답에서 GENERAL/240/false 로 보정
 */
class GroupStudySettingsServiceTest {

    private static final long LEADER = 1L;
    private static final long MEMBER = 2L;
    private static final long GROUP = 10L;

    private GroupStudyRepository groups;
    private GroupStudyMemberRepository members;
    private GroupStudyJoinApplicationRepository applications;
    private GroupStudyAttendanceRepository attendances;
    private UserRepository users;
    private GroupStudyService service;

    private User leader;
    private User member;

    @BeforeEach
    void setUp() {
        groups = mock(GroupStudyRepository.class);
        members = mock(GroupStudyMemberRepository.class);
        applications = mock(GroupStudyJoinApplicationRepository.class);
        attendances = mock(GroupStudyAttendanceRepository.class);
        users = mock(UserRepository.class);
        S3Service s3 = mock(S3Service.class);
        GroupRankingService ranking = mock(GroupRankingService.class);

        leader = User.builder().id(LEADER).displayName("방장").build();
        member = User.builder().id(MEMBER).displayName("멤버").build();
        when(users.findById(LEADER)).thenReturn(Optional.of(leader));
        when(users.findById(MEMBER)).thenReturn(Optional.of(member));

        // save 는 전달 객체를 그대로 돌려주고 id 를 채운다.
        when(groups.save(any(GroupStudy.class))).thenAnswer(inv -> {
            GroupStudy g = inv.getArgument(0);
            if (g.getId() == null) g.setId(GROUP);
            return g;
        });
        when(members.save(any(GroupStudyMember.class))).thenAnswer(inv -> inv.getArgument(0));
        when(applications.save(any(GroupStudyJoinApplication.class))).thenAnswer(inv -> inv.getArgument(0));
        when(attendances.aggregateByGroupIdsAndDateBetween(anyCollection(), any(), any())).thenReturn(List.of());

        service = new GroupStudyService(groups, members, applications, attendances,
                mock(GroupChatMessageRepository.class), mock(GroupStudyQuizSessionRepository.class),
                mock(GroupStudyQuizSessionAnswerRepository.class), users, s3, ranking);
    }

    private GroupStudyDTO.CreateRequest.CreateRequestBuilder baseCreate() {
        return GroupStudyDTO.CreateRequest.builder()
                .title("알고리즘 취업 준비방").description("매일 4시간")
                .startDate(LocalDate.of(2026, 9, 30)).endDate(LocalDate.of(2026, 12, 31))
                .capacity(10).isPublic(true);
    }

    private GroupStudy existingGroup(boolean isPublic) {
        return GroupStudy.builder()
                .id(GROUP).title("기존").description("d").startDate(LocalDate.of(2026, 1, 1)).endDate(LocalDate.of(2026, 12, 31))
                .capacity(10).currentCount(1).isPublic(isPublic).leader(leader).status(GroupStudyStatus.RECRUITING)
                .build();
    }

    // ── 생성 ─────────────────────────────────────────────────────────────────────

    @Test
    void create_general_withDefaults_whenLegacyClientOmitsPolicyFields() {
        GroupStudyDTO.Response res = service.createGroupStudy(LEADER, baseCreate().build(), null);

        assertEquals(GroupStudyType.GENERAL, res.getStudyType());
        assertEquals(240, res.getTargetStudyMinutes());
        assertFalse(res.getJoinQuestionEnabled());
        assertNull(res.getJoinQuestion());
        assertFalse(res.getNicknameRuleEnabled());
        assertNull(res.getNicknameRule());
        assertNull(res.getStudyIconId());
        assertEquals(1, res.getMemberCount());
        assertEquals(10, res.getMaxMembers());
        assertEquals(0.0, res.getAttendanceRate());
        assertEquals(0L, res.getAvgStudySeconds());
        assertEquals(7, res.getActivityWindowDays());
    }

    @Test
    void create_cam_withJoinQuestionAndNicknameRule() {
        GroupStudyDTO.CreateRequest req = baseCreate()
                .studyType(GroupStudyType.CAM).targetStudyMinutes(480)
                .joinQuestionEnabled(true).joinQuestion(" 어떤 목표를 가지고 있나요? ")
                .nicknameRuleEnabled(true).nicknameRule("학교/학년/닉네임")
                .build();

        GroupStudyDTO.Response res = service.createGroupStudy(LEADER, req, null);

        assertEquals(GroupStudyType.CAM, res.getStudyType());
        assertEquals(480, res.getTargetStudyMinutes());
        assertTrue(res.getJoinQuestionEnabled());
        assertEquals("어떤 목표를 가지고 있나요?", res.getJoinQuestion());
        assertTrue(res.getNicknameRuleEnabled());
        assertEquals("학교/학년/닉네임", res.getNicknameRule());
    }

    @Test
    void create_toggleOff_dropsTextEvenIfSent() {
        GroupStudyDTO.CreateRequest req = baseCreate()
                .joinQuestionEnabled(false).joinQuestion("보내긴 했지만")
                .nicknameRuleEnabled(false).nicknameRule("보내긴 했지만")
                .build();
        GroupStudyDTO.Response res = service.createGroupStudy(LEADER, req, null);
        assertNull(res.getJoinQuestion());
        assertNull(res.getNicknameRule());
    }

    @Test
    void create_rejectsInvalidPolicyValues_beforeSaving() {
        assertThrows(IllegalArgumentException.class,
                () -> service.createGroupStudy(LEADER, baseCreate().targetStudyMinutes(180).build(), null));
        assertThrows(IllegalArgumentException.class,
                () -> service.createGroupStudy(LEADER, baseCreate().targetStudyMinutes(630).build(), null));
        assertThrows(IllegalArgumentException.class,
                () -> service.createGroupStudy(LEADER, baseCreate().studyType(null).build(), null));
        assertThrows(IllegalArgumentException.class,
                () -> service.createGroupStudy(LEADER, baseCreate().joinQuestionEnabled(true).joinQuestion("").build(), null));
        assertThrows(IllegalArgumentException.class,
                () -> service.createGroupStudy(LEADER, baseCreate().nicknameRuleEnabled(true).nicknameRule(null).build(), null));
        verify(groups, never()).save(any());
    }

    // ── 수정 ─────────────────────────────────────────────────────────────────────

    @Test
    void update_rejectsNonLeader_evenWithValidPayload() {
        when(groups.findById(GROUP)).thenReturn(Optional.of(existingGroup(true)));
        GroupStudyDTO.UpdateRequest req = GroupStudyDTO.UpdateRequest.builder().studyType(GroupStudyType.CAM).build();

        assertThrows(SecurityException.class, () -> service.updateGroupStudy(MEMBER, GROUP, req, null, false));
        verify(groups, never()).save(any());
    }

    @Test
    void update_partial_keepsUntouchedFields_andNormalizesToggleOff() {
        GroupStudy g = existingGroup(true);
        g.setStudyType(GroupStudyType.CAM);
        g.setTargetStudyMinutes(360);
        g.setJoinQuestionEnabled(true);
        g.setJoinQuestion("목표?");
        g.setNicknameRuleEnabled(true);
        g.setNicknameRule("학교/학년");
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));

        // 목표시간만 바꾸고 가입 질문은 끈다. 닉네임 규칙은 건드리지 않는다.
        GroupStudyDTO.UpdateRequest req = GroupStudyDTO.UpdateRequest.builder()
                .targetStudyMinutes(600).joinQuestionEnabled(false).build();
        GroupStudyDTO.Response res = service.updateGroupStudy(LEADER, GROUP, req, null, false);

        assertEquals(GroupStudyType.CAM, res.getStudyType());
        assertEquals(600, res.getTargetStudyMinutes());
        assertFalse(res.getJoinQuestionEnabled());
        assertNull(res.getJoinQuestion());
        assertNull(g.getJoinQuestion()); // 저장 값도 null 정규화
        assertTrue(res.getNicknameRuleEnabled());
        assertEquals("학교/학년", res.getNicknameRule());
    }

    @Test
    void update_enableToggleWithoutText_rejected_butReusesExistingText() {
        GroupStudy g = existingGroup(true);
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));

        // 기존 문구 없음 + 토글 ON 만 → 400
        assertThrows(IllegalArgumentException.class, () -> service.updateGroupStudy(LEADER, GROUP,
                GroupStudyDTO.UpdateRequest.builder().joinQuestionEnabled(true).build(), null, false));

        // 기존 문구가 있으면 토글만 켜도 유지된다.
        g.setJoinQuestion("예전 질문");
        GroupStudyDTO.Response res = service.updateGroupStudy(LEADER, GROUP,
                GroupStudyDTO.UpdateRequest.builder().joinQuestionEnabled(true).build(), null, false);
        assertTrue(res.getJoinQuestionEnabled());
        assertEquals("예전 질문", res.getJoinQuestion());
    }

    @Test
    void update_rejectsOutOfRangeTargetMinutes() {
        when(groups.findById(GROUP)).thenReturn(Optional.of(existingGroup(true)));
        assertThrows(IllegalArgumentException.class, () -> service.updateGroupStudy(LEADER, GROUP,
                GroupStudyDTO.UpdateRequest.builder().targetStudyMinutes(720).build(), null, false));
    }

    // ── 가입 ─────────────────────────────────────────────────────────────────────

    @Test
    void apply_publicGroupWithJoinQuestion_requiresAnswer_andStoresIt() {
        GroupStudy g = existingGroup(true);
        g.setJoinQuestionEnabled(true);
        g.setJoinQuestion("어떤 목표를 가지고 있나요?");
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, MEMBER, GroupStudyMemberStatus.JOINED)).thenReturn(false);

        assertThrows(IllegalArgumentException.class, () -> service.applyToGroupStudy(MEMBER, GROUP,
                GroupStudyDTO.JoinApplyRequest.builder().introduction("안녕하세요").build()));
        verify(members, never()).save(any());

        GroupStudyDTO.ApplicationResponse res = service.applyToGroupStudy(MEMBER, GROUP,
                GroupStudyDTO.JoinApplyRequest.builder().introduction("안녕하세요").joinAnswer("취업 준비").build());
        assertEquals("어떤 목표를 가지고 있나요?", res.getJoinQuestion());
        assertEquals("취업 준비", res.getJoinAnswer());
        assertEquals(2, g.getCurrentCount());
    }

    @Test
    void apply_nicknameRuleGroup_requiresNickname_andCopiesToMember() {
        GroupStudy g = existingGroup(true);
        g.setNicknameRuleEnabled(true);
        g.setNicknameRule("학교/학년/닉네임");
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));

        assertThrows(IllegalArgumentException.class, () -> service.applyToGroupStudy(MEMBER, GROUP,
                GroupStudyDTO.JoinApplyRequest.builder().introduction("hi").build()));

        service.applyToGroupStudy(MEMBER, GROUP,
                GroupStudyDTO.JoinApplyRequest.builder().introduction("hi").nickname("한양대/3/도현").build());

        ArgumentCaptor<GroupStudyMember> captor = ArgumentCaptor.forClass(GroupStudyMember.class);
        verify(members).save(captor.capture());
        assertEquals("한양대/3/도현", captor.getValue().getNickname());
    }

    @Test
    void apply_legacyGroupWithoutPolicy_keepsImmediateJoinFlow() {
        GroupStudy g = existingGroup(true);
        g.setJoinQuestionEnabled(null); // 컬럼 default 적용 전 캐시/구 row 시뮬레이션
        g.setNicknameRuleEnabled(null);
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));

        GroupStudyDTO.ApplicationResponse res = service.applyToGroupStudy(MEMBER, GROUP,
                GroupStudyDTO.JoinApplyRequest.builder().introduction("공개 스터디 바로 참가").build());
        assertNull(res.getJoinQuestion());
        assertNull(res.getJoinAnswer());
        verify(members).save(any(GroupStudyMember.class));
    }

    @Test
    void approve_copiesApplicationNicknameToMember() {
        GroupStudy g = existingGroup(false);
        GroupStudyJoinApplication app = GroupStudyJoinApplication.builder()
                .id(77L).groupStudy(g).user(member).introduction("hi").nickname("규칙닉")
                .status(com.studybridge.api.entity.GroupStudyJoinStatus.PENDING).build();
        when(applications.findById(77L)).thenReturn(Optional.of(app));

        service.approveApplication(LEADER, 77L);

        ArgumentCaptor<GroupStudyMember> captor = ArgumentCaptor.forClass(GroupStudyMember.class);
        verify(members).save(captor.capture());
        assertEquals("규칙닉", captor.getValue().getNickname());
    }

    // ── 하위 호환 / 지표 ──────────────────────────────────────────────────────────

    @Test
    void legacyRow_withNullPolicyColumns_readsAsDefaults() {
        GroupStudy g = existingGroup(true);
        g.setStudyType(null);
        g.setTargetStudyMinutes(null);
        g.setJoinQuestionEnabled(null);
        g.setNicknameRuleEnabled(null);
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));

        GroupStudyDTO.Response res = service.getGroupStudy(GROUP);
        assertEquals(GroupStudyType.GENERAL, res.getStudyType());
        assertEquals(240, res.getTargetStudyMinutes());
        assertFalse(res.getJoinQuestionEnabled());
        assertFalse(res.getNicknameRuleEnabled());
        assertEquals("기존", res.getTitle());
    }

    @Test
    void list_computesMetricsFromAttendanceAggregate_inSingleQuery() {
        GroupStudy g = existingGroup(true);
        g.setCurrentCount(3);
        when(groups.findAll()).thenReturn(List.of(g));
        // 3명 × 7일 = 21 → 출석 16행(76.2%), 공부 합 10800초 → 514초
        when(attendances.aggregateByGroupIdsAndDateBetween(anyCollection(), any(), any()))
                .thenReturn(List.<Object[]>of(new Object[]{GROUP, 16L, 10800L}));

        List<GroupStudyDTO.Response> list = service.getAllGroupStudies();

        assertEquals(1, list.size());
        assertEquals(76.2, list.get(0).getAttendanceRate());
        assertEquals(514L, list.get(0).getAvgStudySeconds());
        assertEquals(3, list.get(0).getMemberCount());
        verify(attendances, Mockito.times(1)).aggregateByGroupIdsAndDateBetween(anyCollection(), any(), any());
    }

    @Test
    void list_survivesAggregateFailure_withZeroMetrics() {
        when(groups.findAll()).thenReturn(List.of(existingGroup(true)));
        when(attendances.aggregateByGroupIdsAndDateBetween(anyCollection(), any(), any()))
                .thenThrow(new RuntimeException("column missing"));

        List<GroupStudyDTO.Response> list = service.getAllGroupStudies();
        assertEquals(0.0, list.get(0).getAttendanceRate());
        assertEquals(0L, list.get(0).getAvgStudySeconds());
    }

    // ── 닉네임 자가 변경 ───────────────────────────────────────────────────────────

    @Test
    void updateMyNickname_requiresMembership_andRespectsRule() {
        GroupStudy g = existingGroup(true);
        g.setNicknameRuleEnabled(true);
        g.setNicknameRule("학교/학년");
        when(groups.findById(GROUP)).thenReturn(Optional.of(g));
        when(members.findByGroupStudyIdAndUserIdAndStatus(GROUP, 99L, GroupStudyMemberStatus.JOINED)).thenReturn(Optional.empty());

        assertThrows(SecurityException.class, () -> service.updateMyNickname(99L, GROUP,
                GroupStudyDTO.MemberNicknameRequest.builder().nickname("x").build()));

        GroupStudyMember me = GroupStudyMember.builder().id(5L).groupStudy(g).user(member)
                .role(com.studybridge.api.entity.GroupStudyRole.MEMBER).status(GroupStudyMemberStatus.JOINED).build();
        when(members.findByGroupStudyIdAndUserIdAndStatus(GROUP, MEMBER, GroupStudyMemberStatus.JOINED)).thenReturn(Optional.of(me));
        when(members.findByGroupStudyIdAndStatus(GROUP, GroupStudyMemberStatus.JOINED)).thenReturn(List.of(me));
        when(attendances.findByGroupStudyIdAndUserId(anyLong(), anyLong())).thenReturn(List.of());

        // 규칙 ON → 빈 값으로 해제 불가
        assertThrows(IllegalArgumentException.class, () -> service.updateMyNickname(MEMBER, GROUP,
                GroupStudyDTO.MemberNicknameRequest.builder().nickname("").build()));

        GroupStudyDTO.MemberResponse res = service.updateMyNickname(MEMBER, GROUP,
                GroupStudyDTO.MemberNicknameRequest.builder().nickname("한양대/3").build());
        assertEquals("한양대/3", res.getNickname());
        assertEquals("멤버", res.getDisplayName());
    }
}
