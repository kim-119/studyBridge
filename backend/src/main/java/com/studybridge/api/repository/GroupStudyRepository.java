package com.studybridge.api.repository;

import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface GroupStudyRepository extends JpaRepository<GroupStudy, Long> {
    List<GroupStudy> findByStatus(GroupStudyStatus status);

    @Query("SELECT g FROM GroupStudy g WHERE " +
           "LOWER(g.title) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
           "LOWER(g.goal) LIKE LOWER(CONCAT('%', :keyword, '%'))")
    List<GroupStudy> searchByKeyword(@Param("keyword") String keyword);
}

