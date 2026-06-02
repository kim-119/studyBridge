package com.studybridge.api.service;

import com.studybridge.api.dto.StudyGroupDTO;
import com.studybridge.api.dto.StudyRecruitmentDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class StudyRecruitmentService {

    private final StudyRecruitmentRepository studyRecruitmentRepository;
    private final StudyApplicationRepository studyApplicationRepository;
    private final StudyGroupRepository studyGroupRepository;
    private final UserRepository userRepository;

    // 1. 모집글 생성
    @Transactional
    public StudyRecruitmentDTO.Response createRecruitment(Long userId, StudyRecruitmentDTO.Request request) {
        User leader = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

        StudyRecruitment recruitment = StudyRecruitment.builder()
                .title(request.getTitle())
                .objective(request.getObjective())
                .deadline(request.getDeadline())
                .maxMembers(request.getMaxMembers())
                .currentMembers(1)
                .leader(leader)
                .status("RECRUITING")
                .build();

        StudyRecruitment saved = studyRecruitmentRepository.save(recruitment);
        return convertToResponse(saved);
    }

    // 2. 전체 모집글 조회
    public List<StudyRecruitmentDTO.Response> getRecruitments() {
        return studyRecruitmentRepository.findAllByOrderByCreatedAtDesc().stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    // 3. 모집글 키워드 검색
    public List<StudyRecruitmentDTO.Response> searchRecruitments(String keyword) {
        if (keyword == null || keyword.trim().isEmpty()) {
            return getRecruitments();
        }
        return studyRecruitmentRepository.searchByKeyword(keyword.trim()).stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    // 4. 모집글 상세 조회
    public StudyRecruitmentDTO.Response getRecruitment(Long id) {
        StudyRecruitment recruitment = studyRecruitmentRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("스터디 모집글을 찾을 수 없습니다. ID: " + id));
        return convertToResponse(recruitment);
    }

    // 5. 모집글 수정
    @Transactional
    public StudyRecruitmentDTO.Response updateRecruitment(Long userId, Long id, StudyRecruitmentDTO.Request request) {
        StudyRecruitment recruitment = studyRecruitmentRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("스터디 모집글을 찾을 수 없습니다."));

        if (!recruitment.getLeader().getId().equals(userId)) {
            throw new RuntimeException("권한이 없습니다. 모집글 리더만 수정할 수 있습니다.");
        }

        if (!"RECRUITING".equals(recruitment.getStatus())) {
            throw new RuntimeException("이미 완료되었거나 취소된 모집글은 수정할 수 없습니다.");
        }

        recruitment.setTitle(request.getTitle());
        recruitment.setObjective(request.getObjective());
        recruitment.setDeadline(request.getDeadline());
        recruitment.setMaxMembers(request.getMaxMembers());

        StudyRecruitment updated = studyRecruitmentRepository.save(recruitment);
        return convertToResponse(updated);
    }

    // 6. 모집글 삭제
    @Transactional
    public void deleteRecruitment(Long userId, Long id) {
        StudyRecruitment recruitment = studyRecruitmentRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("스터디 모집글을 찾을 수 없습니다."));

        if (!recruitment.getLeader().getId().equals(userId)) {
            throw new RuntimeException("권한이 없습니다. 모집글 리더만 삭제할 수 있습니다.");
        }

        studyRecruitmentRepository.delete(recruitment);
    }

    // 7. 모집 완료 및 스터디 자동 개설
    @Transactional
    public StudyGroupDTO.Response completeRecruitment(Long userId, Long id) {
        StudyRecruitment recruitment = studyRecruitmentRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("스터디 모집글을 찾을 수 없습니다."));

        if (!recruitment.getLeader().getId().equals(userId)) {
            throw new RuntimeException("권한이 없습니다. 모집글 리더만 모집 완료하고 스터디를 시작할 수 있습니다.");
        }

        if (!"RECRUITING".equals(recruitment.getStatus())) {
            throw new RuntimeException("이미 완료되었거나 취소된 모집글입니다.");
        }

        recruitment.setStatus("COMPLETED");
        studyRecruitmentRepository.save(recruitment);

        // 스터디 개설 및 멤버 세팅
        List<User> members = new ArrayList<>();
        members.add(recruitment.getLeader());

        List<StudyApplication> approvedApplications = studyApplicationRepository.findByStudyRecruitmentIdAndStatus(id,
                "APPROVED");
        for (StudyApplication app : approvedApplications) {
            members.add(app.getUser());
        }

        StudyGroup studyGroup = StudyGroup.builder()
                .studyRecruitment(recruitment)
                .title(recruitment.getTitle())
                .members(members)
                .status("ACTIVE")
                .build();

        StudyGroup savedGroup = studyGroupRepository.save(studyGroup);

        return StudyGroupDTO.Response.builder()
                .id(savedGroup.getId())
                .studyRecruitmentId(recruitment.getId())
                .title(savedGroup.getTitle())
                .status(savedGroup.getStatus())
                .createdAt(savedGroup.getCreatedAt())
                .build();
    }

    private StudyRecruitmentDTO.Response convertToResponse(StudyRecruitment recruitment) {
        return StudyRecruitmentDTO.Response.builder()
                .id(recruitment.getId())
                .title(recruitment.getTitle())
                .objective(recruitment.getObjective())
                .deadline(recruitment.getDeadline())
                .maxMembers(recruitment.getMaxMembers())
                .currentMembers(recruitment.getCurrentMembers())
                .leaderId(recruitment.getLeader().getId())
                .leaderName(recruitment.getLeader().getDisplayName())
                .leaderPhotoUrl(recruitment.getLeader().getPhotoUrl())
                .status(recruitment.getStatus())
                .createdAt(recruitment.getCreatedAt())
                .build();
    }
}
