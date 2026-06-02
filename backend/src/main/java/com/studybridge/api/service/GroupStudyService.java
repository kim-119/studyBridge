package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.GroupStudyJoinApplicationRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.NoSuchElementException;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class GroupStudyService {

    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final GroupStudyJoinApplicationRepository groupStudyJoinApplicationRepository;
    private final UserRepository userRepository;

    // 그룹스터디 생성. 방장이 자동 가입 처리됨
    @Transactional
    public GroupStudyDTO.Response createGroupStudy(Long leaderId, GroupStudyDTO.CreateRequest request) {
        log.info("Creating group study. leaderId={}, title={}", leaderId, request.getTitle());

        User leader = userRepository.findById(leaderId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + leaderId));

        if (request.getCapacity() > 10) {
            throw new IllegalArgumentException("그룹 정원은 최대 10명까지만 가능합니다. (WebRTC SFU 서비스 성능 보장)");
        }

        GroupStudy groupStudy = GroupStudy.builder()
                .title(request.getTitle())
                .goal(request.getGoal())
                .description(request.getDescription())
                .startDate(request.getStartDate())
                .endDate(request.getEndDate())
                .capacity(request.getCapacity())
                .currentCount(1) // 방장 1명 기본 추가
                .isPublic(request.getIsPublic())
                .leader(leader)
                .status(GroupStudyStatus.RECRUITING)
                .build();

        GroupStudy savedGroupStudy = groupStudyRepository.save(groupStudy);

        // 방장을 그룹 멤버로 등록
        GroupStudyMember leaderMember = GroupStudyMember.builder()
                .groupStudy(savedGroupStudy)
                .user(leader)
                .role(GroupStudyRole.LEADER)
                .status(GroupStudyMemberStatus.JOINED)
                .points(0)
                .build();
        groupStudyMemberRepository.save(leaderMember);

        log.info("Group study created successfully. groupId={}", savedGroupStudy.getId());
        return toResponseDTO(savedGroupStudy);
    }

    // 특정 그룹스터디의 상세 정보를 조회합니다.

    public GroupStudyDTO.Response getGroupStudy(Long groupId) {
        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
        return toResponseDTO(groupStudy);
    }

    // 모든 모집 중인 혹은 활성화된 그룹스터디 목록을 조회합니다.

    public List<GroupStudyDTO.Response> getAllGroupStudies() {
        return groupStudyRepository.findAll().stream()
                .map(this::toResponseDTO)
                .collect(Collectors.toList());
    }

    // 그룹스터디 가입을 신청합니다.

    @Transactional
    public GroupStudyDTO.ApplicationResponse applyToGroupStudy(Long userId, Long groupId,
            GroupStudyDTO.JoinApplyRequest request) {
        log.info("User applied to group study. userId={}, groupId={}", userId, groupId);

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        // 1. 이미 소속된 멤버인지 체크
        if (groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyMemberStatus.JOINED)) {
            throw new IllegalStateException("이미 가입된 그룹 스터디입니다.");
        }

        // 2. 이미 대기 중인 신청서가 있는지 체크
        if (groupStudyJoinApplicationRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyJoinStatus.PENDING)) {
            throw new IllegalStateException("이미 승인 대기 중인 신청이 존재합니다.");
        }

        // 3. 공개방인 경우: 승인 절차 없이 즉시 가입
        if (groupStudy.getIsPublic()) {
            if (groupStudy.getCurrentCount() >= groupStudy.getCapacity()) {
                throw new IllegalStateException("정원이 가득 찬 그룹스터디입니다.");
            }

            GroupStudyMember member = GroupStudyMember.builder()
                    .groupStudy(groupStudy)
                    .user(user)
                    .role(GroupStudyRole.MEMBER)
                    .status(GroupStudyMemberStatus.JOINED)
                    .points(0)
                    .build();
            groupStudyMemberRepository.save(member);

            groupStudy.setCurrentCount(groupStudy.getCurrentCount() + 1);
            groupStudyRepository.save(groupStudy);

            log.info("Public group study: Joined immediately. userId={}, groupId={}", userId, groupId);

            GroupStudyJoinApplication dummyApp = GroupStudyJoinApplication.builder()
                    .groupStudy(groupStudy)
                    .user(user)
                    .introduction(request.getIntroduction())
                    .status(GroupStudyJoinStatus.APPROVED)
                    .build();
            GroupStudyJoinApplication savedDummy = groupStudyJoinApplicationRepository.save(dummyApp);

            return toApplicationResponseDTO(savedDummy);
        }

        // 4. 비공개방인 경우: 승인제 가입 신청서 생성
        GroupStudyJoinApplication application = GroupStudyJoinApplication.builder()
                .groupStudy(groupStudy)
                .user(user)
                .introduction(request.getIntroduction())
                .status(GroupStudyJoinStatus.PENDING)
                .build();

        GroupStudyJoinApplication savedApplication = groupStudyJoinApplicationRepository.save(application);
        log.info("Private group study: Application submitted. applicationId={}", savedApplication.getId());
        return toApplicationResponseDTO(savedApplication);
    }

    // 그룹장 전용: 대기 중인 모든 지원서 목록을 조회합니다.

    public List<GroupStudyDTO.ApplicationResponse> getApplications(Long leaderId, Long groupId) {
        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        if (!groupStudy.getLeader().getId().equals(leaderId)) {
            throw new SecurityException("가입 대기 목록 조회 권한이 없습니다. (방장만 조회 가능)");
        }

        return groupStudyJoinApplicationRepository.findByGroupStudyIdAndStatus(groupId, GroupStudyJoinStatus.PENDING)
                .stream()
                .map(this::toApplicationResponseDTO)
                .collect(Collectors.toList());
    }

    // 그룹장 전용: 가입 지원서를 승인하여 정식 멤버로 가입시킵니다.

    @Transactional
    public GroupStudyDTO.ApplicationResponse approveApplication(Long leaderId, Long applicationId) {
        log.info("Approving application. leaderId={}, applicationId={}", leaderId, applicationId);

        GroupStudyJoinApplication application = groupStudyJoinApplicationRepository.findById(applicationId)
                .orElseThrow(() -> new NoSuchElementException("Application not found with ID: " + applicationId));

        GroupStudy groupStudy = application.getGroupStudy();

        if (!groupStudy.getLeader().getId().equals(leaderId)) {
            throw new SecurityException("지원서 승인 권한이 없습니다. (방장만 가능)");
        }

        if (application.getStatus() != GroupStudyJoinStatus.PENDING) {
            throw new IllegalStateException("대기 상태의 지원서만 처리할 수 있습니다.");
        }

        if (groupStudy.getCurrentCount() >= groupStudy.getCapacity()) {
            throw new IllegalStateException("정원이 가득 찬 그룹스터디입니다. 더 이상 승인할 수 없습니다.");
        }

        // 지원서 상태 변경
        application.setStatus(GroupStudyJoinStatus.APPROVED);
        groupStudyJoinApplicationRepository.save(application);

        // 정식 그룹 멤버 등록
        GroupStudyMember newMember = GroupStudyMember.builder()
                .groupStudy(groupStudy)
                .user(application.getUser())
                .role(GroupStudyRole.MEMBER)
                .status(GroupStudyMemberStatus.JOINED)
                .points(0)
                .build();
        groupStudyMemberRepository.save(newMember);

        // 방 인원 수 증가
        groupStudy.setCurrentCount(groupStudy.getCurrentCount() + 1);
        groupStudyRepository.save(groupStudy);

        log.info("Application approved. memberId={}, groupId={}", application.getUser().getId(), groupStudy.getId());
        return toApplicationResponseDTO(application);
    }

    // 그룹장 전용: 가입 지원서를 거절합니다.
    @Transactional
    public GroupStudyDTO.ApplicationResponse rejectApplication(Long leaderId, Long applicationId) {
        log.info("Rejecting application. leaderId={}, applicationId={}", leaderId, applicationId);

        GroupStudyJoinApplication application = groupStudyJoinApplicationRepository.findById(applicationId)
                .orElseThrow(() -> new NoSuchElementException("Application not found with ID: " + applicationId));

        GroupStudy groupStudy = application.getGroupStudy();

        if (!groupStudy.getLeader().getId().equals(leaderId)) {
            throw new SecurityException("지원서 거절 권한이 없습니다. (방장만 가능)");
        }

        if (application.getStatus() != GroupStudyJoinStatus.PENDING) {
            throw new IllegalStateException("대기 상태의 지원서만 처리할 수 있습니다.");
        }

        application.setStatus(GroupStudyJoinStatus.REJECTED);
        groupStudyJoinApplicationRepository.save(application);

        log.info("Application rejected. applicantId={}", application.getUser().getId());
        return toApplicationResponseDTO(application);
    }

    public List<GroupStudyDTO.MemberResponse> getGroupMembers(Long groupId) {
        return groupStudyMemberRepository.findByGroupStudyIdAndStatus(groupId, GroupStudyMemberStatus.JOINED)
                .stream()
                .map(member -> GroupStudyDTO.MemberResponse.builder()
                        .userId(member.getUser().getId())
                        .displayName(member.getUser().getDisplayName())
                        .photoUrl(member.getUser().getPhotoUrl())
                        .major(member.getUser().getMajor())
                        .role(member.getRole())
                        .points(member.getPoints())
                        .joinedAt(member.getJoinedAt())
                        .build())
                .collect(Collectors.toList());
    }

    // 그룹스터디 삭제

    @Transactional
    public void deleteGroupStudy(Long userId, Long groupId) {
        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        if (!groupStudy.getLeader().getId().equals(userId)) {
            throw new SecurityException("그룹스터디 삭제 권한이 없습니다. (방장만 삭제 가능)");
        }

        groupStudyRepository.delete(groupStudy);
        log.info("Group study deleted successfully. groupId={}, deletedBy={}", groupId, userId);
    }

    // 그룹스터디 관리자 강제 삭제 (소유권 검증 없음)
    @Transactional
    public void deleteGroupStudyForce(Long groupId) {
        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
        groupStudyRepository.delete(groupStudy);
        log.info("Group study force-deleted successfully by admin. groupId={}", groupId);
    }

    @Transactional
    public GroupStudyDTO.Response startGroupStudy(Long leaderId, Long groupId) {
        log.info("Starting group study (activating). leaderId={}, groupId={}", leaderId, groupId);

        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        if (!groupStudy.getLeader().getId().equals(leaderId)) {
            throw new SecurityException("스터디를 시작할 권한이 없습니다. (방장만 가능)");
        }

        if (groupStudy.getStatus() != GroupStudyStatus.RECRUITING) {
            throw new IllegalStateException("모집 중인 스터디그룹만 시작할 수 있습니다.");
        }

        groupStudy.setStatus(GroupStudyStatus.ACTIVE);
        GroupStudy saved = groupStudyRepository.save(groupStudy);

        log.info("Group study activated. groupId={}", groupId);
        return toResponseDTO(saved);
    }

    private GroupStudyDTO.Response toResponseDTO(GroupStudy groupStudy) {
        return GroupStudyDTO.Response.builder()
                .id(groupStudy.getId())
                .title(groupStudy.getTitle())
                .goal(groupStudy.getGoal())
                .description(groupStudy.getDescription())
                .startDate(groupStudy.getStartDate())
                .endDate(groupStudy.getEndDate())
                .capacity(groupStudy.getCapacity())
                .currentCount(groupStudy.getCurrentCount())
                .isPublic(groupStudy.getIsPublic())
                .leaderId(groupStudy.getLeader().getId())
                .leaderName(groupStudy.getLeader().getDisplayName())
                .status(groupStudy.getStatus())
                .createdAt(groupStudy.getCreatedAt())
                .build();
    }

    private GroupStudyDTO.ApplicationResponse toApplicationResponseDTO(GroupStudyJoinApplication app) {
        return GroupStudyDTO.ApplicationResponse.builder()
                .applicationId(app.getId())
                .groupStudyId(app.getGroupStudy().getId())
                .applicantId(app.getUser().getId())
                .applicantName(app.getUser().getDisplayName())
                .applicantPhotoUrl(app.getUser().getPhotoUrl())
                .introduction(app.getIntroduction())
                .status(app.getStatus())
                .createdAt(app.getCreatedAt())
                .build();
    }
}
