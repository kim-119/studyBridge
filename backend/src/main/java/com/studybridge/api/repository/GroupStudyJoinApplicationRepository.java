package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyJoinApplication;
import com.studybridge.api.entity.GroupStudyJoinStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyJoinApplicationRepository extends JpaRepository<GroupStudyJoinApplication, Long> {

    List<GroupStudyJoinApplication> findByGroupStudyIdAndStatus(Long groupStudyId, GroupStudyJoinStatus status);

    Optional<GroupStudyJoinApplication> findByGroupStudyIdAndUserIdAndStatus(Long groupStudyId, Long userId, GroupStudyJoinStatus status);

    boolean existsByGroupStudyIdAndUserIdAndStatus(Long groupStudyId, Long userId, GroupStudyJoinStatus status);
}
