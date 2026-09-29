package com.studybridge.api.repository;

import com.studybridge.api.entity.Blog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface BlogRepository extends JpaRepository<Blog, Long> {
    List<Blog> findAllByOrderByCreatedAtDesc();
    List<Blog> findByTitleContainingIgnoreCaseOrContentContainingIgnoreCaseOrAuthor_DisplayNameContainingIgnoreCaseOrderByCreatedAtDesc(
            String title, String content, String authorDisplayName);
}
