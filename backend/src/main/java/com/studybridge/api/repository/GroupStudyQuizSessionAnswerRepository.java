package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyQuizSessionAnswer;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyQuizSessionAnswerRepository extends JpaRepository<GroupStudyQuizSessionAnswer, Long> {
    Optional<GroupStudyQuizSessionAnswer> findBySessionIdAndUserIdAndQuestionId(Long sessionId, Long userId, Long questionId);

    List<GroupStudyQuizSessionAnswer> findBySessionIdAndQuestionIdOrderBySubmittedAtAsc(Long sessionId, Long questionId);

    List<GroupStudyQuizSessionAnswer> findBySessionIdOrderBySubmittedAtAsc(Long sessionId);

    /**
     * 퀴즈 랭킹 SoT(RDS) 집계 — 그룹의 채점 완료(gradedAt not null) 답안을 사용자별로 합산.
     * [userId, SUM(pointsAwarded)]. Redis 랭킹 캐시 재구축(GroupRankingService.rebuild)의 유일한 원천. 그룹 단위 1회 조회.
     */
    @Query("SELECT a.userId, COALESCE(SUM(a.pointsAwarded), 0) " +
           "FROM GroupStudyQuizSessionAnswer a JOIN a.session s " +
           "WHERE s.groupStudy.id = :groupId AND a.gradedAt IS NOT NULL " +
           "GROUP BY a.userId")
    List<Object[]> aggregatePointsByUser(@Param("groupId") Long groupId);

    /**
     * 퀴즈 랭킹 상세 집계 — (세션, 사용자) 단위로 [sessionId, sessionStatus, questionOrderJson, userId,
     * 채점된 답안 수, 정답 수, 점수 합]. 세션 참여 횟수·정답률 계산용. 그룹 단위 1회 조회(N+1 없음).
     */
    @Query("SELECT s.id, s.status, s.questionOrderJson, a.userId, COUNT(a), " +
           "SUM(CASE WHEN a.isCorrect = true THEN 1 ELSE 0 END), COALESCE(SUM(a.pointsAwarded), 0) " +
           "FROM GroupStudyQuizSessionAnswer a JOIN a.session s " +
           "WHERE s.groupStudy.id = :groupId AND a.gradedAt IS NOT NULL " +
           "GROUP BY s.id, s.status, s.questionOrderJson, a.userId")
    List<Object[]> aggregateBySessionAndUser(@Param("groupId") Long groupId);

    /**
     * 세션별로 실제 정답 공개(채점)까지 진행된 문제 수 — [sessionId, COUNT(DISTINCT questionId)].
     * 중단(ABORTED)된 세션의 "출제된 문제 수" 하한으로 쓴다(완료 세션은 questionOrderJson 길이가 정본).
     */
    @Query("SELECT a.session.id, COUNT(DISTINCT a.questionId) " +
           "FROM GroupStudyQuizSessionAnswer a JOIN a.session s " +
           "WHERE s.groupStudy.id = :groupId AND a.gradedAt IS NOT NULL " +
           "GROUP BY a.session.id")
    List<Object[]> countGradedQuestionsBySession(@Param("groupId") Long groupId);

    // 그룹스터디 삭제 시 cascade가 없는 퀴즈 세션 답변을 세션 id 기준으로 일괄 정리.
    @Modifying
    @Query("delete from GroupStudyQuizSessionAnswer a where a.session.id in :sessionIds")
    void deleteBySessionIdIn(@Param("sessionIds") Collection<Long> sessionIds);
}
