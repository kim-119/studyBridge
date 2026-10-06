package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.dto.GroupStudyInvitationDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.GroupStudyInvitationRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.List;
import java.util.NoSuchElementException;

/**
 * 비공개 그룹스터디 초대 링크.
 *  · 생성/조회/폐기: 방장(LEADER)만. MEMBER·비회원은 SecurityException(403). (그룹 역할 enum 에 ADMIN 은 없다.)
 *  · 수락: 유효한 토큰 보유자는 승인 절차 없이 즉시 MEMBER 로 가입(공개방 즉시 가입과 같은 경로).
 *    이미 멤버면 멱등(usedCount 증가 없이 그룹 정보만 반환). 정원 초과는 409.
 *  · 무효 토큰(존재X/비활성/만료/사용 횟수 초과)은 400, 삭제된 그룹의 토큰은 cascade 로 사라져 400(존재X).
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class GroupStudyInvitationService {

    static final int DEFAULT_EXPIRES_DAYS = 7;
    static final int MAX_EXPIRES_DAYS = 30;
    static final int TOKEN_BYTES = 32;
    public static final String INVITE_PATH_PREFIX = "/groups/invite/";

    private final GroupStudyInvitationRepository invitationRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository memberRepository;
    private final UserRepository userRepository;
    private final GroupStudyService groupStudyService;
    private final SecureRandom secureRandom = new SecureRandom();

    @Transactional
    public GroupStudyInvitationDTO.Response create(Long userId, Long groupId, GroupStudyInvitationDTO.CreateRequest request) {
        GroupStudy group = requireGroup(groupId);
        requireLeader(group, userId);
        User creator = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

        int days = request == null || request.getExpiresInDays() == null ? DEFAULT_EXPIRES_DAYS : request.getExpiresInDays();
        if (days < 1 || days > MAX_EXPIRES_DAYS) {
            throw new IllegalArgumentException("초대 링크 유효기간은 1~" + MAX_EXPIRES_DAYS + "일 사이여야 합니다.");
        }
        Integer maxUses = request == null ? null : request.getMaxUses();
        if (maxUses != null && maxUses < 1) {
            throw new IllegalArgumentException("최대 사용 횟수는 1 이상이어야 합니다.");
        }

        // 그룹당 활성 링크 1개: 재생성 = 기존 링크 폐기 + 새 토큰
        List<GroupStudyInvitation> actives = invitationRepository.findByGroupStudyIdAndActiveTrueOrderByCreatedAtDesc(groupId);
        for (GroupStudyInvitation prev : actives) {
            prev.setActive(false);
        }
        if (!actives.isEmpty()) invitationRepository.saveAll(actives);

        GroupStudyInvitation invitation = GroupStudyInvitation.builder()
                .groupStudy(group)
                .token(generateToken())
                .createdBy(creator)
                .expiresAt(LocalDateTime.now().plusDays(days))
                .active(true)
                .usedCount(0)
                .maxUses(maxUses)
                .build();
        GroupStudyInvitation saved = invitationRepository.save(invitation);
        log.info("Group invitation created. groupId={}, invitationId={}, by={}", groupId, saved.getId(), userId);
        return toResponse(saved);
    }

    @Transactional(readOnly = true)
    public List<GroupStudyInvitationDTO.Response> listActive(Long userId, Long groupId) {
        GroupStudy group = requireGroup(groupId);
        requireLeader(group, userId);
        LocalDateTime now = LocalDateTime.now();
        return invitationRepository.findByGroupStudyIdAndActiveTrueOrderByCreatedAtDesc(groupId).stream()
                .filter(inv -> inv.isUsable(now))
                .map(this::toResponse)
                .toList();
    }

    @Transactional
    public void revoke(Long userId, Long groupId, Long invitationId) {
        GroupStudy group = requireGroup(groupId);
        requireLeader(group, userId);
        GroupStudyInvitation invitation = invitationRepository.findById(invitationId)
                .orElseThrow(() -> new NoSuchElementException("Invitation not found with ID: " + invitationId));
        if (!invitation.getGroupStudy().getId().equals(groupId)) {
            throw new SecurityException("이 그룹의 초대 링크가 아닙니다.");
        }
        invitation.setActive(false);
        invitationRepository.save(invitation);
        log.info("Group invitation revoked. groupId={}, invitationId={}, by={}", groupId, invitationId, userId);
    }

    @Transactional(readOnly = true)
    public GroupStudyInvitationDTO.Preview preview(Long userId, String token) {
        GroupStudyInvitation invitation = invitationRepository.findByToken(normalizeToken(token)).orElse(null);
        if (invitation == null) {
            return GroupStudyInvitationDTO.Preview.builder().valid(false).reason("존재하지 않거나 폐기된 초대 링크입니다.").build();
        }
        GroupStudy group = invitation.getGroupStudy();
        String reason = invalidReason(invitation, group, LocalDateTime.now());
        boolean alreadyMember = memberRepository.existsByGroupStudyIdAndUserIdAndStatus(group.getId(), userId, GroupStudyMemberStatus.JOINED);
        GroupStudyDTO.Response g = groupStudyService.getGroupStudy(group.getId());
        return GroupStudyInvitationDTO.Preview.builder()
                .valid(reason == null)
                .reason(reason)
                .groupId(group.getId())
                .title(group.getTitle())
                .description(group.getDescription())
                .studyType(g.getStudyType())
                .isPublic(group.getIsPublic())
                .capacity(group.getCapacity())
                .currentCount(group.getCurrentCount())
                .leaderName(group.getLeader().getDisplayName())
                .coverImageUrl(g.getCoverImageUrl())
                .nicknameRuleEnabled(g.getNicknameRuleEnabled())
                .nicknameRule(g.getNicknameRule())
                .alreadyMember(alreadyMember)
                .expiresAt(invitation.getExpiresAt())
                .build();
    }

    @Transactional
    public GroupStudyDTO.Response accept(Long userId, String token, GroupStudyInvitationDTO.AcceptRequest request) {
        GroupStudyInvitation invitation = invitationRepository.findByToken(normalizeToken(token))
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않거나 폐기된 초대 링크입니다."));
        GroupStudy group = invitation.getGroupStudy();
        String reason = invalidReason(invitation, group, LocalDateTime.now());
        if (reason != null) throw new IllegalArgumentException(reason);

        if (memberRepository.existsByGroupStudyIdAndUserIdAndStatus(group.getId(), userId, GroupStudyMemberStatus.JOINED)) {
            // 이미 멤버: 멱등 — 사용 횟수를 올리지 않고 그룹 정보만 돌려준다.
            return groupStudyService.getGroupStudy(group.getId());
        }
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

        boolean nicknameRuleEnabled = Boolean.TRUE.equals(group.getNicknameRuleEnabled());
        String nickname = GroupStudySettingsPolicy.requireNickname(nicknameRuleEnabled, request == null ? null : request.getNickname());
        String introduction = request == null || request.getIntroduction() == null || request.getIntroduction().isBlank()
                ? "초대 링크로 참여" : request.getIntroduction();

        groupStudyService.joinImmediately(user, group, introduction, null, nickname);
        invitation.setUsedCount(invitation.getUsedCount() + 1);
        invitationRepository.save(invitation);
        log.info("Group invitation accepted. groupId={}, userId={}, invitationId={}, usedCount={}",
                group.getId(), userId, invitation.getId(), invitation.getUsedCount());
        return groupStudyService.getGroupStudy(group.getId());
    }

    // ── 내부 ──────────────────────────────────────────────────────────────

    private GroupStudy requireGroup(Long groupId) {
        return groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
    }

    private void requireLeader(GroupStudy group, Long userId) {
        if (group.getLeader() == null || !group.getLeader().getId().equals(userId)) {
            throw new SecurityException("초대 링크는 방장만 관리할 수 있습니다.");
        }
    }

    /** null 이면 유효. */
    static String invalidReason(GroupStudyInvitation invitation, GroupStudy group, LocalDateTime now) {
        if (group == null) return "삭제된 그룹의 초대 링크입니다.";
        if (!invitation.isActive()) return "폐기된 초대 링크입니다.";
        if (invitation.isExpired(now)) return "만료된 초대 링크입니다.";
        if (invitation.isExhausted()) return "사용 횟수를 초과한 초대 링크입니다.";
        if (group.getStatus() == GroupStudyStatus.COMPLETED) return "종료된 스터디입니다.";
        return null;
    }

    private String generateToken() {
        for (int i = 0; i < 5; i++) {
            byte[] bytes = new byte[TOKEN_BYTES];
            secureRandom.nextBytes(bytes);
            String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
            if (!invitationRepository.existsByToken(token)) return token;
        }
        throw new IllegalStateException("초대 토큰 생성에 실패했습니다. 다시 시도해주세요.");
    }

    private static String normalizeToken(String token) {
        if (token == null) return "";
        String t = token.trim();
        if (t.length() > 64) throw new IllegalArgumentException("존재하지 않거나 폐기된 초대 링크입니다.");
        return t;
    }

    private GroupStudyInvitationDTO.Response toResponse(GroupStudyInvitation inv) {
        return GroupStudyInvitationDTO.Response.builder()
                .id(inv.getId())
                .groupId(inv.getGroupStudy().getId())
                .token(inv.getToken())
                .invitePath(INVITE_PATH_PREFIX + inv.getToken())
                .createdBy(inv.getCreatedBy() != null ? inv.getCreatedBy().getId() : null)
                .createdAt(inv.getCreatedAt())
                .expiresAt(inv.getExpiresAt())
                .active(inv.isActive())
                .usedCount(inv.getUsedCount())
                .maxUses(inv.getMaxUses())
                .build();
    }
}
