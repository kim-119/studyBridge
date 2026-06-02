package com.studybridge.api.repository;

import com.studybridge.api.entity.StudyGroup;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface StudyGroupRepository extends JpaRepository<StudyGroup, Long> {
    Optional<StudyGroup> findByStudyRecruitmentId(Long studyRecruitmentId);
}
