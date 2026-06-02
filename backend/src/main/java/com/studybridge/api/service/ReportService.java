package com.studybridge.api.service;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.BlogRepository;
import com.studybridge.api.repository.ReportRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ReportService {

    private final ReportRepository reportRepository;
    private final UserRepository userRepository;
    private final BlogRepository blogRepository;

    // 유저 신고 등록
    @Transactional
    public ReportDTO.Response reportUser(Long reporterId, ReportDTO.UserReportRequest request) {
        if (reporterId.equals(request.getReportedUserId())) {
            throw new IllegalArgumentException("자기 자신을 신고할 수 없습니다.");
        }

        User reporter = userRepository.findById(reporterId)
                .orElseThrow(() -> new IllegalArgumentException("신고자를 찾을 수 없습니다."));
        User reportedUser = userRepository.findById(request.getReportedUserId())
                .orElseThrow(() -> new IllegalArgumentException("신고 대상 유저를 찾을 수 없습니다."));

        if (reportRepository.existsByReporter_IdAndReportedUser_Id(reporterId, request.getReportedUserId())) {
            throw new IllegalStateException("이미 해당 유저를 신고하셨습니다.");
        }

        Report report = Report.builder()
                .reporter(reporter)
                .reportedUser(reportedUser)
                .reportType(ReportType.USER)
                .reason(request.getReason())
                .details(request.getDetails())
                .build();

        Report savedReport = reportRepository.save(report);
        log.info("[유저 신고 완료] 신고자: {}, 피신고자: {}, 사유: {}", reporter.getDisplayName(), reportedUser.getDisplayName(), request.getReason());

        return convertToDTO(savedReport);
    }

    // 게시글 신고 등록
    @Transactional
    public ReportDTO.Response reportPost(Long reporterId, ReportDTO.PostReportRequest request) {
        User reporter = userRepository.findById(reporterId)
                .orElseThrow(() -> new IllegalArgumentException("신고자를 찾을 수 없습니다."));
        Blog reportedBlog = blogRepository.findById(request.getReportedBlogId())
                .orElseThrow(() -> new IllegalArgumentException("신고 대상 게시글을 찾을 수 없습니다."));

        if (reportedBlog.getAuthor().getId().equals(reporterId)) {
            throw new IllegalArgumentException("자신의 게시글은 신고할 수 없습니다.");
        }

        if (reportRepository.existsByReporter_IdAndReportedBlog_BlogId(reporterId, request.getReportedBlogId())) {
            throw new IllegalStateException("이미 해당 게시글을 신고하셨습니다.");
        }

        Report report = Report.builder()
                .reporter(reporter)
                .reportedBlog(reportedBlog)
                .reportType(ReportType.POST)
                .reason(request.getReason())
                .details(request.getDetails())
                .build();

        Report savedReport = reportRepository.save(report);
        log.info("[게시글 신고 완료] 신고자: {}, 게시글 ID: {}, 사유: {}", reporter.getDisplayName(), reportedBlog.getBlogId(), request.getReason());

        return convertToDTO(savedReport);
    }

    // 신고 내역 목록 조회
    public List<ReportDTO.Response> listReports() {
        return reportRepository.findAllByOrderByCreatedAtDesc().stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    // 신고 상태 처리 (RESOLVED / REJECTED)
    @Transactional
    public ReportDTO.Response resolveReport(Long reportId, ReportStatus status) {
        Report report = reportRepository.findById(reportId)
                .orElseThrow(() -> new IllegalArgumentException("신고 내역을 찾을 수 없습니다."));

        report.setStatus(status);
        Report updatedReport = reportRepository.save(report);
        log.info("[신고 처리 상태 변경] 신고 ID: {}, 상태: {}", reportId, status);

        return convertToDTO(updatedReport);
    }

    // Entity -> DTO 변환 헬퍼
    private ReportDTO.Response convertToDTO(Report report) {
        Long targetId = null;
        String targetTitleOrName = null;

        if (report.getReportType() == ReportType.USER && report.getReportedUser() != null) {
            targetId = report.getReportedUser().getId();
            targetTitleOrName = report.getReportedUser().getDisplayName();
        } else if (report.getReportType() == ReportType.POST && report.getReportedBlog() != null) {
            targetId = report.getReportedBlog().getBlogId();
            targetTitleOrName = report.getReportedBlog().getTitle();
        }

        return ReportDTO.Response.builder()
                .reportId(report.getReportId())
                .reporterId(report.getReporter().getId())
                .reporterNickname(report.getReporter().getDisplayName())
                .reportType(report.getReportType())
                .targetId(targetId)
                .targetTitleOrName(targetTitleOrName)
                .reason(report.getReason())
                .details(report.getDetails())
                .status(report.getStatus())
                .createdAt(report.getCreatedAt())
                .build();
    }
}
