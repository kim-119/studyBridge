package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuiz;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupStudyQuizRepository extends JpaRepository<GroupStudyQuiz, Long> {
    List<GroupStudyQuiz> findByGroupStudyIdOrderByCreatedAtDesc(Long groupStudyId);
}
