package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyMemberRepository extends JpaRepository<GroupStudyMember, Long> {

    List<GroupStudyMember> findByGroupStudyIdAndStatus(Long groupStudyId, GroupStudyMemberStatus status);

    Optional<GroupStudyMember> findByGroupStudyIdAndUserId(Long groupStudyId, Long userId);

    Optional<GroupStudyMember> findByGroupStudyIdAndUserIdAndStatus(Long groupStudyId, Long userId, GroupStudyMemberStatus status);

    boolean existsByGroupStudyIdAndUserIdAndStatus(Long groupStudyId, Long userId, GroupStudyMemberStatus status);

    /** 통계용: 그룹 멤버 + 사용자(닉네임/표시명) fetch join — N+1 방지. */
    @org.springframework.data.jpa.repository.Query("SELECT m FROM GroupStudyMember m JOIN FETCH m.user WHERE m.groupStudy.id = :groupStudyId AND m.status = :status ORDER BY m.joinedAt")
    List<GroupStudyMember> findWithUserByGroupStudyIdAndStatus(@org.springframework.data.repository.query.Param("groupStudyId") Long groupStudyId,
                                                               @org.springframework.data.repository.query.Param("status") GroupStudyMemberStatus status);

    /** 카드 지표용: 여러 그룹의 현재 멤버 가입일만 [groupStudyId, joinedAt] 로 1회 조회. */
    @org.springframework.data.jpa.repository.Query("SELECT m.groupStudy.id, m.joinedAt FROM GroupStudyMember m WHERE m.groupStudy.id IN :groupIds AND m.status = 'JOINED'")
    List<Object[]> findJoinedAtByGroupIds(@org.springframework.data.repository.query.Param("groupIds") java.util.Collection<Long> groupIds);
}
