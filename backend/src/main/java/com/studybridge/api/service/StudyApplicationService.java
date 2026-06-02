package com.studybridge.api.service;

import com.studybridge.api.dto.StudyApplicationDTO;
import com.studybridge.api.entity.StudyApplication;
import com.studybridge.api.entity.StudyRecruitment;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.StudyApplicationRepository;
import com.studybridge.api.repository.StudyRecruitmentRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class StudyApplicationService {

    private final StudyRecruitmentRepository studyRecruitmentRepository;
    private final StudyApplicationRepository studyApplicationRepository;
    private final UserRepository userRepository;

    // 1. 참가 신청
    @Transactional
    public StudyApplicationDTO.Response applyToJoin(Long userId, Long recruitmentId) {
        StudyRecruitment recruitment = studyRecruitmentRepository.findById(recruitmentId)
                .orElseThrow(() -> new RuntimeException("스터디 모집글을 찾을 수 없습니다."));

        if (!"RECRUITING".equals(recruitment.getStatus())) {
            throw new RuntimeException("모집 중인 스터디가 아닙니다.");
        }

        if (recruitment.getLeader().getId().equals(userId)) {
            throw new RuntimeException("스터디 리더는 본인 스터디에 참여 신청을 할 수 없습니다.");
        }

        studyApplicationRepository.findByStudyRecruitmentIdAndUserId(recruitmentId, userId)
                .ifPresent(app -> {
                    throw new RuntimeException("이미 이 스터디에 참여 신청을 보냈거나 처리되었습니다.");
                });

        if (recruitment.getCurrentMembers() >= recruitment.getMaxMembers()) {
            throw new RuntimeException("모집 정원이 마감되었습니다.");
        }

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

        StudyApplication application = StudyApplication.builder()
                .studyRecruitment(recruitment)
                .user(user)
                .status("PENDING")
                .build();

        StudyApplication saved = studyApplicationRepository.save(application);
        return convertToResponse(saved);
    }

    // 2. 신청 취소 또는 탈퇴
    @Transactional
    public void leaveRecruitment(Long userId, Long recruitmentId) {
        StudyRecruitment recruitment = studyRecruitmentRepository.findById(recruitmentId)
                .orElseThrow(() -> new RuntimeException("스터디 모집글을 찾을 수 없습니다."));

        StudyApplication application = studyApplicationRepository.findByStudyRecruitmentIdAndUserId(recruitmentId, userId)
                .orElseThrow(() -> new RuntimeException("참여 신청 내역을 찾을 수 없습니다."));

        if ("APPROVED".equals(application.getStatus())) {
            // 이미 수락된 상태였으면 현재 수락 정원에서 제외
            recruitment.setCurrentMembers(Math.max(1, recruitment.getCurrentMembers() - 1));
            studyRecruitmentRepository.save(recruitment);
        }

        studyApplicationRepository.delete(application);
    }

    // 3. 리더용 - 해당 모집글의 신청자 리스트 조회
    public List<StudyApplicationDTO.Response> getApplications(Long recruitmentId) {
        return studyApplicationRepository.findByStudyRecruitmentId(recruitmentId).stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    // 4. 리더용 - 지원자 승인/거절 처리
    @Transactional
    public StudyApplicationDTO.Response updateApplicationStatus(Long leaderId, Long applicationId, String status) {
        StudyApplication application = studyApplicationRepository.findById(applicationId)
                .orElseThrow(() -> new RuntimeException("신청 내역을 찾을 수 없습니다."));

        StudyRecruitment recruitment = application.getStudyRecruitment();

        if (!recruitment.getLeader().getId().equals(leaderId)) {
            throw new RuntimeException("권한이 없습니다. 모집글 리더만 승인 여부를 변경할 수 있습니다.");
        }

        if (!"RECRUITING".equals(recruitment.getStatus())) {
            throw new RuntimeException("모집 중인 스터디에 대해서만 승인할 수 있습니다.");
        }

        String oldStatus = application.getStatus();

        if ("APPROVED".equals(status) && !"APPROVED".equals(oldStatus)) {
            // 수락할 때 정원 초과 여부 확인
            if (recruitment.getCurrentMembers() >= recruitment.getMaxMembers()) {
                throw new RuntimeException("모집 정원이 가득 차서 더 승인할 수 없습니다.");
            }
            recruitment.setCurrentMembers(recruitment.getCurrentMembers() + 1);
            studyRecruitmentRepository.save(recruitment);
        } else if (!"APPROVED".equals(status) && "APPROVED".equals(oldStatus)) {
            // 기존 승인되었다가 거절 등으로 변경될 때 정원 차감
            recruitment.setCurrentMembers(Math.max(1, recruitment.getCurrentMembers() - 1));
            studyRecruitmentRepository.save(recruitment);
        }

        application.setStatus(status);
        StudyApplication updated = studyApplicationRepository.save(application);

        return convertToResponse(updated);
    }

    private StudyApplicationDTO.Response convertToResponse(StudyApplication application) {
        return StudyApplicationDTO.Response.builder()
                .id(application.getId())
                .studyRecruitmentId(application.getStudyRecruitment().getId())
                .userId(application.getUser().getId())
                .userDisplayName(application.getUser().getDisplayName())
                .userEmail(application.getUser().getEmail())
                .userMajor(application.getUser().getMajor())
                .status(application.getStatus())
                .appliedAt(application.getAppliedAt())
                .build();
    }
}
