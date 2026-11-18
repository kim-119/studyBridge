package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyReport;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import org.springframework.data.domain.Pageable;

@Repository
public interface GroupStudyReportRepository extends JpaRepository<GroupStudyReport, Long> {
    List<GroupStudyReport> findByGroupStudyId(Long groupStudyId);
    List<GroupStudyReport> findAllByOrderByCreatedAtDesc();
    // 내 신고 내역(신고자 기준, 최신순) — principal id 로만 호출한다.
    List<GroupStudyReport> findByReporter_IdOrderByCreatedAtDesc(Long reporterId, Pageable pageable);
}
