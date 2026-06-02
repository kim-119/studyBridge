package com.studybridge.api.repository;

import com.studybridge.api.entity.StudyApplication;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface StudyApplicationRepository extends JpaRepository<StudyApplication, Long> {

    List<StudyApplication> findByStudyRecruitmentId(Long studyRecruitmentId);

    List<StudyApplication> findByStudyRecruitmentIdAndStatus(Long studyRecruitmentId, String status);

    List<StudyApplication> findByUserId(Long userId);

    Optional<StudyApplication> findByStudyRecruitmentIdAndUserId(Long studyRecruitmentId, Long userId);
}
