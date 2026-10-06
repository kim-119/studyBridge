package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudyInvitation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface GroupStudyInvitationRepository extends JpaRepository<GroupStudyInvitation, Long> {
    Optional<GroupStudyInvitation> findByToken(String token);
    List<GroupStudyInvitation> findByGroupStudyIdAndActiveTrueOrderByCreatedAtDesc(Long groupStudyId);
    boolean existsByToken(String token);
}
