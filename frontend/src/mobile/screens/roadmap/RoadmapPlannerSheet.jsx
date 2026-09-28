import React, { useEffect, useState } from 'react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import { plannerService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import { localIsoDate } from '../planner/plannerAdapter';
import { ROADMAP_TOTAL_DAYS, buildFromRoadmapRequest } from './roadmapModel';

const STEP = {
  START_DATE: 'start-date',
  CONFIRM_DUPLICATE: 'confirm-duplicate',
};

const DUPLICATE_FALLBACK_MESSAGE =
  '이미 이 로드맵으로 생성된 플래너가 있습니다. 다시 생성하면 기존 항목을 유지한 채 추가됩니다.';

export default function RoadmapPlannerSheet({ isOpen, onClose, materialId, materialTitle, roadmap, onCreated }) {
  const [startDate, setStartDate] = useState(localIsoDate());
  const [step, setStep] = useState(STEP.START_DATE);
  const [duplicateMessage, setDuplicateMessage] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setStartDate(localIsoDate());
    setStep(STEP.START_DATE);
    setDuplicateMessage('');
  }, [isOpen]);

  const createPlanners = useSubmit(async (force) => {
    const request = buildFromRoadmapRequest({ materialId, roadmap, materialTitle, startDate, force });
    const response = await plannerService.createFromRoadmap(request);

    if (response?.duplicate && !force) {
      setDuplicateMessage(response.message || DUPLICATE_FALLBACK_MESSAGE);
      setStep(STEP.CONFIRM_DUPLICATE);
      return;
    }

    onCreated({
      createdCount: response?.createdCount ?? request.items.length,
      message: response?.message || `${request.items.length}개의 플래너가 생성되었습니다.`,
    });
  });

  const closeUnlessBusy = () => {
    if (!createPlanners.isSubmitting) onClose();
  };

  return (
    <BottomSheet title="플래너 생성" isOpen={isOpen} onClose={closeUnlessBusy}>
      {step === STEP.START_DATE ? (
        <>
          <p className="mobile-sheet__note">
            {ROADMAP_TOTAL_DAYS}일 로드맵을 학습 플래너 {ROADMAP_TOTAL_DAYS}개로 만듭니다. 시작일을 선택하세요.
          </p>

          <TextField
            label="시작일"
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />

          <Button
            fullWidth
            isLoading={createPlanners.isSubmitting}
            disabled={!startDate}
            onClick={() => createPlanners.submit(false).catch(() => {})}
          >
            {ROADMAP_TOTAL_DAYS}개 플래너 생성
          </Button>
        </>
      ) : (
        <>
          <p className="mobile-sheet__note">
            {duplicateMessage} 계속하시겠습니까?
          </p>

          <div className="mobile-actions">
            <Button variant="ghost" disabled={createPlanners.isSubmitting} onClick={onClose}>
              취소
            </Button>
            <Button
              isLoading={createPlanners.isSubmitting}
              onClick={() => createPlanners.submit(true).catch(() => {})}
            >
              계속 생성
            </Button>
          </div>
        </>
      )}

      {createPlanners.errorMessage && <p className="mobile-auth__error">{createPlanners.errorMessage}</p>}
    </BottomSheet>
  );
}
