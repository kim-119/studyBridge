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
}
