package com.studybridge.api.service;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ReportRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ReportService {

    private final ReportRepository reportRepository;
    private final UserRepository userRepository;
    private final AgentChatRoomRepository agentChatRoomRepository;

    /**
     * 사용자가 대상을 신고합니다.
     */
    @Transactional
    public ReportDTO.ReportResponse submitReport(Long userId, ReportDTO.ReportRequest request) {
        User reporter = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("신고하는 사용자를 찾을 수 없습니다."));

        // 신고 대상의 유효성 검사
        if (request.getTargetType() == ReportTargetType.USER) {
            if (!userRepository.existsById(request.getTargetId())) {
                throw new IllegalArgumentException("신고 대상 사용자를 찾을 수 없습니다.");
            }
        } else if (request.getTargetType() == ReportTargetType.STUDY_GROUP) {
            if (!agentChatRoomRepository.existsById(request.getTargetId())) {
                throw new IllegalArgumentException("신고 대상 학습 그룹을 찾을 수 없습니다.");
            }
        }

        Report report = Report.builder()
                .reporter(reporter)
                .targetType(request.getTargetType())
                .targetId(request.getTargetId())
                .reason(request.getReason())
                .status(ReportStatus.PENDING)
                .build();

        Report savedReport = reportRepository.save(report);
        return convertToReportResponse(savedReport);
    }

    /**
     * 관리자가 모든 신고 목록을 조회합니다.
     */
    public List<ReportDTO.ReportResponse> getAllReports() {
        return reportRepository.findAll().stream()
                .map(this::convertToReportResponse)
                .collect(Collectors.toList());
    }

    /**
     * 관리자가 특정 상태의 신고 목록을 조회합니다.
     */
    public List<ReportDTO.ReportResponse> getReportsByStatus(ReportStatus status) {
        return reportRepository.findByStatus(status).stream()
                .map(this::convertToReportResponse)
                .collect(Collectors.toList());
    }

    /**
     * 관리자가 신고를 승인합니다.
     */
    @Transactional
    public ReportDTO.ReportResponse approveReport(Long reportId) {
        Report report = reportRepository.findById(reportId)
                .orElseThrow(() -> new IllegalArgumentException("신고를 찾을 수 없습니다."));
        
        if (report.getStatus() != ReportStatus.PENDING) {
            throw new IllegalStateException("이미 처리된 신고입니다.");
        }
        
        report.setStatus(ReportStatus.APPROVED);
        return convertToReportResponse(report);
    }

    /**
     * 관리자가 신고를 반려합니다.
     */
    @Transactional
    public ReportDTO.ReportResponse rejectReport(Long reportId) {
        Report report = reportRepository.findById(reportId)
                .orElseThrow(() -> new IllegalArgumentException("신고를 찾을 수 없습니다."));

        if (report.getStatus() != ReportStatus.PENDING) {
            throw new IllegalStateException("이미 처리된 신고입니다.");
        }

        report.setStatus(ReportStatus.REJECTED);
        return convertToReportResponse(report);
    }

    private ReportDTO.ReportResponse convertToReportResponse(Report report) {
        String targetContent = "N/A";
        String targetUrl = null;
        
        if (report.getTargetType() == ReportTargetType.USER) {
            User user = userRepository.findById(report.getTargetId())
                    .orElse(null); // 신고 대상이 삭제되었을 수도 있음
            if (user != null) {
                targetContent = user.getDisplayName() + " (" + user.getEmail() + ")";
            }
        } else if (report.getTargetType() == ReportTargetType.STUDY_GROUP) {
            AgentChatRoom room = agentChatRoomRepository.findById(report.getTargetId())
                    .orElse(null); // 신고 대상이 삭제되었을 수도 있음
            if (room != null) {
                targetContent = room.getRoomName() + " (개설자: " + room.getUser().getDisplayName() + ")";
            }
        }

        return ReportDTO.ReportResponse.builder()
                .reportId(report.getId())
                .reporterUserId(report.getReporter().getId())
                .reporterEmail(report.getReporter().getEmail())
                .targetType(report.getTargetType())
                .targetId(report.getTargetId())
                .targetContent(targetContent)
                .targetUrl(targetUrl)
                .reason(report.getReason())
                .status(report.getStatus())
                .reportedAt(report.getCreatedAt())
                .build();
    }
}
