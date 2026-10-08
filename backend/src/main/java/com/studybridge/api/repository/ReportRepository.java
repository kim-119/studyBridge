package com.studybridge.api.repository;

import com.studybridge.api.entity.Report;
import com.studybridge.api.entity.ReportType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import org.springframework.data.domain.Pageable;

@Repository
public interface ReportRepository extends JpaRepository<Report, Long> {
    boolean existsByReporter_IdAndReportedUser_Id(Long reporterId, Long reportedUserId);
    boolean existsByReporter_IdAndReportedBlog_BlogId(Long reporterId, Long reportedBlogId);
    boolean existsByReporter_IdAndReportedComment_CommentId(Long reporterId, Long commentId);
    @org.springframework.data.jpa.repository.Modifying
    @org.springframework.data.jpa.repository.Query("update Report r set r.reportedComment = null where r.reportedComment.commentId = :id")
    void detachComment(@org.springframework.data.repository.query.Param("id") Long id);
    @org.springframework.data.jpa.repository.Modifying
    @org.springframework.data.jpa.repository.Query("update Report r set r.reportedBlog = null where r.reportedBlog.blogId = :id")
    void detachPost(@org.springframework.data.repository.query.Param("id") Long id);

    List<Report> findAllByOrderByCreatedAtDesc();
    List<Report> findByReportTypeOrderByCreatedAtDesc(ReportType reportType);
    // 내 신고 내역(신고자 기준, 최신순) — principal id 로만 호출한다.
    List<Report> findByReporter_IdOrderByCreatedAtDesc(Long reporterId, Pageable pageable);
}
