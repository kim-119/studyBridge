package com.studybridge.api.repository;

import com.studybridge.api.entity.StudyRecruitment;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface StudyRecruitmentRepository extends JpaRepository<StudyRecruitment, Long> {

    List<StudyRecruitment> findByLeaderId(Long leaderId);

    List<StudyRecruitment> findAllByOrderByCreatedAtDesc();

    @Query("SELECT s FROM StudyRecruitment s WHERE " +
           "LOWER(s.title) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
           "LOWER(s.objective) LIKE LOWER(CONCAT('%', :keyword, '%')) " +
           "ORDER BY s.createdAt DESC")
    List<StudyRecruitment> searchByKeyword(@Param("keyword") String keyword);
}
