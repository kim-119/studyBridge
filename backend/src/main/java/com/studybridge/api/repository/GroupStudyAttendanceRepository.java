package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyAttendance;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyAttendanceRepository extends JpaRepository<GroupStudyAttendance, Long> {
    Optional<GroupStudyAttendance> findByGroupStudyIdAndUserIdAndDate(Long groupStudyId, Long userId, LocalDate date);
    List<GroupStudyAttendance> findByGroupStudyIdAndDate(Long groupStudyId, LocalDate date);
    List<GroupStudyAttendance> findByGroupStudyIdAndUserId(Long groupStudyId, Long userId);

    /** 그룹별 기간 집계(카드 지표용): [groupStudyId, 출석 행 수(=사용자·날짜 unique), 공부시간 합(초)]. 목록 1회 조회로 N+1 방지. */
    @Query("SELECT a.groupStudy.id, COUNT(a), COALESCE(SUM(a.studyDurationSeconds), 0) " +
           "FROM GroupStudyAttendance a " +
           "WHERE a.groupStudy.id IN :groupIds AND a.date BETWEEN :from AND :to AND a.status = 'PRESENT' " +
           "GROUP BY a.groupStudy.id")
    List<Object[]> aggregateByGroupIdsAndDateBetween(@Param("groupIds") Collection<Long> groupIds,
                                                     @Param("from") LocalDate from,
                                                     @Param("to") LocalDate to);
}
