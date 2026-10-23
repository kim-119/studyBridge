import React from 'react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import { agentService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import AgentDraftStep from './AgentDraftStep';
import RoomSetupStep from './RoomSetupStep';
import { MAX_AGENT_COUNT, MIN_CUSTOM_INSTRUCTION_LENGTH, findInvalidInstruction } from './agentDrafts';
import { useRoomDraft } from './useRoomDraft';

function stepTitleOf(step) {
  return step === 0 ? '새 스터디방' : `AI 학습메이트 #${step}`;
}

export default function CreateRoomSheet({ isOpen, onClose, onCreated, roomCount, roomLimit }) {
  const roomDraft = useRoomDraft();
  const { draft } = roomDraft;

  const createRoom = useSubmit(async () => {
    if (roomCount >= roomLimit) throw new Error(`생성된 학습방은 최대 ${roomLimit}개까지 가질 수 있습니다.`);
    if (findInvalidInstruction(draft.agentDrafts)) {
      throw new Error(`에이전트 추가 요청은 비워 두거나 최소 ${MIN_CUSTOM_INSTRUCTION_LENGTH}자 이상이어야 합니다.`);
    }

    const created = await agentService.createAgent(null, roomDraft.buildPayload());
    roomDraft.reset();
    onCreated(created);
  });

  const close = () => {
    createRoom.clearError();
    onClose();
  };

  const canGoNext = draft.step < MAX_AGENT_COUNT;

  return (
    <BottomSheet title={stepTitleOf(draft.step)} isOpen={isOpen} onClose={close}>
      {draft.step === 0 ? <RoomSetupStep roomDraft={roomDraft} /> : <AgentDraftStep roomDraft={roomDraft} index={draft.step - 1} />}

      {createRoom.errorMessage && <p className="mobile-auth__error">{createRoom.errorMessage}</p>}

      <div className="mobile-sheet-steps">
        <Button variant="ghost" disabled={draft.step === 0} onClick={roomDraft.goPrevious}>
          이전
        </Button>
        <Button variant="secondary" disabled={!canGoNext} onClick={roomDraft.goNext}>
          다음
        </Button>
      </div>

      <Button fullWidth isLoading={createRoom.isSubmitting} onClick={() => createRoom.submit().catch(() => {})}>
        스터디방 생성하기
      </Button>
    </BottomSheet>
  );
}
