package com.studybridge.api.service;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.BlogCommentRepository;
import com.studybridge.api.repository.BlogRepository;
import com.studybridge.api.repository.GroupStudyReportRepository;
import com.studybridge.api.repository.ReportRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.function.Supplier;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ReportService {

    private final ReportRepository reportRepository;
    private final UserRepository userRepository;
    private final BlogRepository blogRepository;
    private final BlogCommentRepository blogCommentRepository;
    private final GroupStudyReportRepository groupStudyReportRepository;

    static final String SOURCE_KNOWLEDGE = "KNOWLEDGE";
    static final String SOURCE_GROUP = "GROUP";
    static final String LABEL_DELETED_POST = "삭제된 게시글";
    static final String LABEL_DELETED_COMMENT = "삭제된 댓글";
    static final String LABEL_WITHDRAWN_USER = "탈퇴한 사용자";
    static final String LABEL_UNKNOWN_GROUP = "삭제된 스터디";
    private static final int COMMENT_SNIPPET_LENGTH = 30;

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

    // 댓글 신고 등록
    @Transactional
    public ReportDTO.Response reportComment(Long reporterId, ReportDTO.CommentReportRequest request) {
        User reporter = userRepository.findById(reporterId)
                .orElseThrow(() -> new IllegalArgumentException("신고자를 찾을 수 없습니다."));
        BlogComment reportedComment = blogCommentRepository.findById(request.getReportedCommentId())
                .orElseThrow(() -> new IllegalArgumentException("신고 대상 댓글을 찾을 수 없습니다."));

        if (reportedComment.getAuthor() != null && reportedComment.getAuthor().getId().equals(reporterId)) {
            throw new IllegalArgumentException("자신의 댓글은 신고할 수 없습니다.");
        }

        if (reportRepository.existsByReporter_IdAndReportedComment_CommentId(reporterId, request.getReportedCommentId())) {
            throw new IllegalStateException("이미 해당 댓글을 신고하셨습니다.");
        }

        Report report = Report.builder()
                .reporter(reporter)
                .reportedComment(reportedComment)
                .reportType(ReportType.COMMENT)
                .reason(request.getReason())
                .details(request.getDetails())
                .build();

        Report savedReport = reportRepository.save(report);
        log.info("[댓글 신고 완료] 신고자: {}, 댓글 ID: {}, 사유: {}", reporter.getDisplayName(), reportedComment.getCommentId(), request.getReason());

        return convertToDTO(savedReport);
    }

    // 신고 내역 목록 조회
    public List<ReportDTO.Response> listReports() {
        return reportRepository.findAllByOrderByCreatedAtDesc().stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    // 내 신고 내역: 지식보드 신고(reports) + 그룹스터디 유저 신고(group_study_reports) 를 합쳐 최신순.
    //  reporterId 는 컨트롤러가 principal 에서 꺼낸 값만 들어온다(클라이언트 userId 미수용).
    public List<ReportDTO.MyReportResponse> getMyReports(Long reporterId, String source, int page, int size) {
        var pageable = org.springframework.data.domain.PageRequest.of(Math.max(0, page), Math.max(1, Math.min(50, size)));
        if ("GROUP".equals(source)) {
            return groupStudyReportRepository.findByReporter_IdOrderByCreatedAtDesc(reporterId, pageable)
                    .stream().map(this::toMyReport).toList();
        }
        return reportRepository.findByReporter_IdOrderByCreatedAtDesc(reporterId, pageable)
                .stream().map(this::toMyReport).toList();
    }

    // 지연 로딩 대상이 이미 삭제됐거나(EntityNotFound) null 이면 대체 라벨로 떨어뜨린다.
    private static String safeSummary(Supplier<String> supplier, String fallback) {
        try {
            String value = supplier.get();
            return (value == null || value.isBlank()) ? fallback : value;
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    private static Long safeId(Supplier<Long> supplier) {
        try {
            return supplier.get();
        } catch (RuntimeException e) {
            return null;
        }
    }

    static String commentSnippet(String content) {
        if (content == null) return null;
        String trimmed = content.strip();
        return trimmed.length() > COMMENT_SNIPPET_LENGTH ? trimmed.substring(0, COMMENT_SNIPPET_LENGTH) + "..." : trimmed;
    }

    private ReportDTO.MyReportResponse toMyReport(Report report) {
        ReportType type = report.getReportType();
        String summary;
        Long targetId;
        if (type == ReportType.USER) {
            targetId = report.getReportedUser() == null ? null : safeId(() -> report.getReportedUser().getId());
            summary = report.getReportedUser() == null ? LABEL_WITHDRAWN_USER
                    : safeSummary(() -> report.getReportedUser().getDisplayName(), LABEL_WITHDRAWN_USER);
        } else if (type == ReportType.POST) {
            targetId = report.getReportedBlog() == null ? null : safeId(() -> report.getReportedBlog().getBlogId());
            summary = report.getReportedBlog() == null ? LABEL_DELETED_POST
                    : safeSummary(() -> report.getReportedBlog().getTitle(), LABEL_DELETED_POST);
        } else {
            targetId = report.getReportedComment() == null ? null : safeId(() -> report.getReportedComment().getCommentId());
            summary = report.getReportedComment() == null ? LABEL_DELETED_COMMENT
                    : safeSummary(() -> commentSnippet(report.getReportedComment().getContent()), LABEL_DELETED_COMMENT);
        }
        boolean available = targetId != null
                && !LABEL_DELETED_POST.equals(summary) && !LABEL_DELETED_COMMENT.equals(summary) && !LABEL_WITHDRAWN_USER.equals(summary);
        return ReportDTO.MyReportResponse.builder()
                .reportId(report.getReportId())
                .source(SOURCE_KNOWLEDGE)
                .targetType(type == null ? null : type.name())
                .targetId(targetId)
                .targetSummary(summary)
                .targetAvailable(available)
                .reason(report.getReason())
                .details(report.getDetails())
                .status(report.getStatus())
                .createdAt(report.getCreatedAt())
                .build();
    }

    private ReportDTO.MyReportResponse toMyReport(GroupStudyReport report) {
        Long targetId = report.getReportedUser() == null ? null : safeId(() -> report.getReportedUser().getId());
        String summary = report.getReportedUser() == null ? LABEL_WITHDRAWN_USER
                : safeSummary(() -> report.getReportedUser().getDisplayName(), LABEL_WITHDRAWN_USER);
        Long groupId = report.getGroupStudy() == null ? null : safeId(() -> report.getGroupStudy().getId());
        String groupTitle = report.getGroupStudy() == null ? LABEL_UNKNOWN_GROUP
                : safeSummary(() -> report.getGroupStudy().getTitle(), LABEL_UNKNOWN_GROUP);
        return ReportDTO.MyReportResponse.builder()
                .reportId(report.getId())
                .source(SOURCE_GROUP)
                .targetType(ReportType.USER.name())
                .targetId(targetId)
                .targetSummary(summary)
                .targetAvailable(targetId != null && !LABEL_WITHDRAWN_USER.equals(summary))
                .groupId(groupId)
                .groupTitle(groupTitle)
                .reason(null)
                .details(report.getReason())
                .status(null)
                .createdAt(report.getCreatedAt())
                .build();
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
        } else if (report.getReportType() == ReportType.COMMENT && report.getReportedComment() != null) {
            targetId = report.getReportedComment().getCommentId();
            String content = report.getReportedComment().getContent();
            targetTitleOrName = content != null && content.length() > 30 ? content.substring(0, 30) + "..." : content;
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
