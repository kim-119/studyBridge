package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuizQuestion;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupStudyQuizQuestionRepository extends JpaRepository<GroupStudyQuizQuestion, Long> {
    List<GroupStudyQuizQuestion> findByQuizId(Long quizId);
    List<GroupStudyQuizQuestion> findByQuizIdOrderByIdAsc(Long quizId);
}
