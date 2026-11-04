package com.studybridge.api.ai.training;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.repository.AiTrainingConsentRepository;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import java.util.List;
import org.junit.jupiter.api.Test;

/** 기본 OFF: 플래그가 꺼져 있으면 동의·승인이 있어도 저장소를 건드리지 않는다. */
class TrainingCollectionDefaultOffTest {

        @Test
        void defaultSettingsAreOff() {
                AiTrainingSettings s = new AiTrainingSettings(false, false, "tc-2026-11", "/c", "/w", "/d", 8, 20, 10000);
                TrainingConsentService consents = mock(TrainingConsentService.class);
                TrainingOutboxWriter writer = mock(TrainingOutboxWriter.class);
                AiTrainingOutboxRepository outbox = mock(AiTrainingOutboxRepository.class);
                TrainingCandidateCollector c = new TrainingCandidateCollector(s, consents, writer, mock(PseudonymousUserKeys.class), outbox,
                                mock(AiTrainingConsentRepository.class));
                GateDecision ok = new GateDecision(true, ResponseQualityV1.QualityStatus.APPROVED, 90.0, null, List.of(), "v", null, 1, 0);
                assertEquals(TrainingCandidateCollector.Status.SKIPPED_DISABLED, c.onApproved(new TrainingCandidateCollector.Candidate(1L,
                                ResponseQualityV1.TaskType.STUDYMATE_BASIC, "r", "q", "a", null, List.of(), ok, null, null)));
                verifyNoInteractions(consents, writer, outbox);
        }
}
