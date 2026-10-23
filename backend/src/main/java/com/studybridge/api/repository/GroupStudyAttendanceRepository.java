package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyAttendance;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyAttendanceRepository extends JpaRepository<GroupStudyAttendance, Long> {
    Optional<GroupStudyAttendance> findByGroupStudyIdAndUserIdAndDate(Long groupStudyId, Long userId, LocalDate date);
    List<GroupStudyAttendance> findByGroupStudyIdAndDate(Long groupStudyId, LocalDate date);
    List<GroupStudyAttendance> findByGroupStudyIdAndUserId(Long groupStudyId, Long userId);
}
