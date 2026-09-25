package com.studybridge.api.exception;

import com.studybridge.api.service.StudyJournalValidationResult;
import lombok.Getter;

/**
 * 학습일지 검증 거절(REQUEST_REVISION/BLOCK). 저장하지 않고 사유/제안을 사용자에게 전달.
 * 원문을 담지 않는다.
 */
@Getter
public class StudyJournalRejectedException extends RuntimeException {

    private final transient StudyJournalValidationResult result;

    public StudyJournalRejectedException(StudyJournalValidationResult result) {
        super("study journal rejected: " + result.getDecision());
        this.result = result;
    }
}
