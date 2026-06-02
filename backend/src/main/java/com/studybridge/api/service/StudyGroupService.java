package com.studybridge.api.service;

import com.studybridge.api.dto.StudyGroupDTO;
import com.studybridge.api.entity.StudyGroup;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.StudyGroupRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class StudyGroupService {

    private final StudyGroupRepository studyGroupRepository;
    private final UserRepository userRepository;

    // 1. 형성된 스터디 그룹 상세 조회
    public StudyGroupDTO.Response getStudyGroup(Long id) {
        StudyGroup studyGroup = studyGroupRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("형성된 스터디 그룹을 찾을 수 없습니다. ID: " + id));
        return convertToResponse(studyGroup);
    }

    // 2. 형성된 스터디 그룹 최종 멤버 목록 조회
    public List<StudyGroupDTO.MemberResponse> getMembers(Long studyGroupId) {
        StudyGroup studyGroup = studyGroupRepository.findById(studyGroupId)
                .orElseThrow(() -> new RuntimeException("형성된 스터디 그룹을 찾을 수 없습니다. ID: " + studyGroupId));

        Long leaderId = studyGroup.getStudyRecruitment().getLeader().getId();

        return studyGroup.getMembers().stream()
                .map(user -> StudyGroupDTO.MemberResponse.builder()
                        .userId(user.getId())
                        .email(user.getEmail())
                        .displayName(user.getDisplayName())
                        .photoUrl(user.getPhotoUrl())
                        .major(user.getMajor())
                        .role(user.getId().equals(leaderId) ? "LEADER" : "MEMBER")
                        .build())
                .collect(Collectors.toList());
    }

    // 3. 형성된 스터디 탈퇴
    @Transactional
    public void leaveStudyGroup(Long userId, Long studyGroupId) {
        StudyGroup studyGroup = studyGroupRepository.findById(studyGroupId)
                .orElseThrow(() -> new RuntimeException("형성된 스터디 그룹을 찾을 수 없습니다. ID: " + studyGroupId));

        Long leaderId = studyGroup.getStudyRecruitment().getLeader().getId();
        if (userId.equals(leaderId)) {
            throw new RuntimeException("스터디 리더는 탈퇴할 수 없습니다. 스터디를 폐쇄해야 합니다.");
        }

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다. ID: " + userId));

        if (!studyGroup.getMembers().contains(user)) {
            throw new RuntimeException("이 스터디 그룹의 소속원이 아닙니다.");
        }

        studyGroup.getMembers().remove(user);
        studyGroupRepository.save(studyGroup);
    }

    private StudyGroupDTO.Response convertToResponse(StudyGroup studyGroup) {
        return StudyGroupDTO.Response.builder()
                .id(studyGroup.getId())
                .studyRecruitmentId(studyGroup.getStudyRecruitment().getId())
                .title(studyGroup.getTitle())
                .status(studyGroup.getStatus())
                .createdAt(studyGroup.getCreatedAt())
                .build();
    }
}
