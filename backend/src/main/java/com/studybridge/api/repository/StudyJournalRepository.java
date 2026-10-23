package com.studybridge.api.repository;

import com.studybridge.api.entity.StudyJournal;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface StudyJournalRepository extends JpaRepository<StudyJournal, Long> {

    List<StudyJournal> findByMaterialIdAndStatusOrderByCreatedAtDesc(
            Long materialId, StudyJournal.StudyJournalStatus status);

    Optional<StudyJournal> findByIdAndStatus(Long id, StudyJournal.StudyJournalStatus status);
}
