package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupStudyRepository extends JpaRepository<GroupStudy, Long> {
    List<GroupStudy> findByStatus(GroupStudyStatus status);
}
