package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyReportDTO;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.GroupStudyReport;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyReportRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.NoSuchElementException;

@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class GroupStudyReportService {

    private final GroupStudyReportRepository groupStudyReportRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final UserRepository userRepository;

    @Transactional
    public GroupStudyReportDTO.Response fileReport(Long reporterId, Long groupId, GroupStudyReportDTO.Request request) {
        log.info("Filing report in group study. reporterId={}, groupId={}", reporterId, groupId);

        User reporter = userRepository.findById(reporterId)
                .orElseThrow(() -> new NoSuchElementException("Reporter user not found with ID: " + reporterId));

        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, reporterId, GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("정식 그룹 멤버만 신고 접수가 가능합니다.");
        }

        User reportedUser = null;
        if (request.getReportedUserId() != null) {
            reportedUser = userRepository.findById(request.getReportedUserId()).orElse(null);
        }

        GroupStudyReport report = GroupStudyReport.builder()
                .groupStudy(groupStudy)
                .reporter(reporter)
                .reportedUser(reportedUser)
                .reason(request.getReason())
                .build();

        GroupStudyReport savedReport = groupStudyReportRepository.save(report);
        log.info("Report filed successfully. reportId={}", savedReport.getId());

        return GroupStudyReportDTO.Response.builder()
                .id(savedReport.getId())
                .groupStudyId(groupId)
                .reporterId(reporterId)
                .reporterName(reporter.getDisplayName())
                .reportedUserId(reportedUser != null ? reportedUser.getId() : null)
                .reportedUserName(reportedUser != null ? reportedUser.getDisplayName() : null)
                .reason(savedReport.getReason())
                .createdAt(savedReport.getCreatedAt())
                .build();
    }
}
