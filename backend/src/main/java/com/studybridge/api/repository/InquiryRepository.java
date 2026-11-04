package com.studybridge.api.repository;

import com.studybridge.api.entity.Inquiry;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface InquiryRepository extends JpaRepository<Inquiry, Long> {
    List<Inquiry> findAllByAuthorIdOrderByCreatedAtDesc(Long authorId);
    List<Inquiry> findAllByOrderByCreatedAtDesc();

    /** 같은 사용자의 가장 최근 문의(연속 클릭 중복 접수 방지용). */
    java.util.Optional<Inquiry> findFirstByAuthorIdOrderByCreatedAtDescIdDesc(Long authorId);
}
