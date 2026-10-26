package com.studybridge.api.repository;

import com.studybridge.api.entity.Report;
import com.studybridge.api.entity.ReportType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ReportRepository extends JpaRepository<Report, Long> {
    boolean existsByReporter_IdAndReportedUser_Id(Long reporterId, Long reportedUserId);
    boolean existsByReporter_IdAndReportedBlog_BlogId(Long reporterId, Long reportedBlogId);
    boolean existsByReporter_IdAndReportedComment_CommentId(Long reporterId, Long commentId);
    void deleteByReportedComment_CommentId(Long commentId);
    List<Report> findAllByOrderByCreatedAtDesc();
    List<Report> findByReportTypeOrderByCreatedAtDesc(ReportType reportType);
}
