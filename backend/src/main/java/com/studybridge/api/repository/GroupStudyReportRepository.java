package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyReport;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupStudyReportRepository extends JpaRepository<GroupStudyReport, Long> {
    List<GroupStudyReport> findByGroupStudyId(Long groupStudyId);
    List<GroupStudyReport> findAllByOrderByCreatedAtDesc();
}
