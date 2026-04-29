package com.studybridge.api.repository;

import com.studybridge.api.entity.Agent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AgentRepository extends JpaRepository<Agent, Long> {
    List<Agent> findByUserId(Long userId);
    int countByUserId(Long userId);
}
