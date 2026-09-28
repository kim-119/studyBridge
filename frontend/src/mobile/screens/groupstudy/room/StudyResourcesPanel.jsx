import React, { useState } from 'react';
import { ClipboardList, ExternalLink, FileText, Play } from 'lucide-react';
import Button from '../../../components/Button';
import ListRow from '../../../components/ListRow';
import ScreenState from '../../../components/ScreenState';
import SubTabs from '../../../components/SubTabs';
import { groupService } from '../../../../services/api';
import { describeApiError, useSubmit } from '../../../data/useAsync';
import { extractDownloadUrl } from '../../../platform/downloadUrl';
import { openExternalUrl } from '../../../platform/externalLink';
import ConfirmAction from '../ConfirmAction';
import { isPdfMaterial } from '../groupStudyModel';
import {
  DEFAULT_QUIZ_OPTIONS,
  QUESTION_COUNT_OPTIONS,
  TIME_LIMIT_OPTIONS,
  describeQuizGenerationFailure,
  describeQuizGenerationSuccess,
  evaluateGeneratedQuiz,
  quizIdOf,
  serverReasonOf,
} from '../quizGenerationModel';
import { DELETE_CONFIRM_MESSAGE, RESOURCE_KIND } from '../resourceDeleteModel';
import RoomPanel from './RoomPanel';
import { ROOM_PANEL } from './useRoomOverlay';
import { useResourceDeletion } from './useResourceDeletion';

const RESOURCE_TABS = [
  { key: ROOM_PANEL.MATERIALS, label: '학습자료' },
  { key: ROOM_PANEL.QUIZ, label: '퀴즈' },
];

function formatQuizMeta(quiz) {
  return [quiz.creatorName, quiz.questionCount ? `${quiz.questionCount}문항` : null].filter(Boolean).join(' · ');
}

async function reloadQuizList(quizzes) {
  try {
    return { list: await quizzes.reload(), error: null };
  } catch (error) {
    return { list: null, error };
  }
}

function useMaterialQuizGeneration(groupId, quizzes) {
  const [generatingMaterialId, setGeneratingMaterialId] = useState(null);
  const [outcome, setOutcome] = useState(null);

  const generate = async (materialId, options) => {
    if (generatingMaterialId !== null) return;
    setGeneratingMaterialId(materialId);
    setOutcome(null);

    try {
      const response = await groupService.generateMaterialQuiz(groupId, materialId, options);
      const refreshed = await reloadQuizList(quizzes);

      if (refreshed.error) {
        setOutcome({ isSuccess: false, message: `퀴즈 목록을 새로고침하지 못했습니다. ${describeApiError(refreshed.error)}` });
        return;
      }

      const evaluation = evaluateGeneratedQuiz(response, refreshed.list);
      setOutcome(
        evaluation.ok
          ? { isSuccess: true, message: describeQuizGenerationSuccess(evaluation) }
          : { isSuccess: false, message: describeQuizGenerationFailure(evaluation.reason) }
      );
    } catch (error) {
      console.warn('자료 기반 퀴즈 생성에 실패했습니다.', error);
      const reason = serverReasonOf(error) || describeApiError(error);
      setOutcome({ isSuccess: false, message: describeQuizGenerationFailure(reason) });
    } finally {
      setGeneratingMaterialId(null);
    }
  };

  return { generatingMaterialId, outcome, generate };
}

function QuizOptionsPicker({ options, onChange }) {
  return (
    <div className="mobile-room-quiz-options">
      <select
        className="mobile-select"
        aria-label="문항 수"
        value={options.questionCount}
        onChange={(event) => onChange({ ...options, questionCount: Number(event.target.value) })}
      >
        {QUESTION_COUNT_OPTIONS.map((count) => (
          <option key={count} value={count}>
            {count}문항
          </option>
        ))}
      </select>
      <select
        className="mobile-select"
        aria-label="문항당 제한 시간"
        value={options.timeLimitSeconds}
        onChange={(event) => onChange({ ...options, timeLimitSeconds: Number(event.target.value) })}
      >
        {TIME_LIMIT_OPTIONS.map((seconds) => (
          <option key={seconds} value={seconds}>
            문항당 {seconds}초
          </option>
        ))}
      </select>
    </div>
  );
}

function LeaderDeleteAction({ kind, resourceId, deletion }) {
  return (
    <ConfirmAction
      label="삭제"
      confirmMessage={DELETE_CONFIRM_MESSAGE[kind]}
      confirmLabel="삭제"
      isLoading={deletion.deletingId === resourceId}
      onConfirm={() => deletion.remove(resourceId)}
    />
  );
}

function MaterialsList({ groupId, isLeader, materials, quizzes, onOpenViewer }) {
  const [quizOptions, setQuizOptions] = useState(DEFAULT_QUIZ_OPTIONS);
  const quizGeneration = useMaterialQuizGeneration(groupId, quizzes);
  const materialDeletion = useResourceDeletion(groupId, RESOURCE_KIND.MATERIAL, materials);
  const isGenerating = quizGeneration.generatingMaterialId !== null;

  const openExternally = useSubmit(async (materialId) => {
    const response = await groupService.getGroupMaterialDownloadUrl(materialId);
    const url = extractDownloadUrl(response);
    if (!url) throw new Error('다운로드 URL을 발급받지 못했습니다.');
    await openExternalUrl(url);
  });

  const openMaterial = (material) => {
    if (isPdfMaterial(material)) {
      onOpenViewer(material.id);
      return;
    }
    openExternally.submit(material.id).catch(() => {});
  };

  const hasPdfMaterial = (materials.data || []).some(isPdfMaterial);
  const outcome = quizGeneration.outcome;

  return (
    <ScreenState
      query={materials}
      loadingLabel="학습자료를 불러오는 중입니다"
      emptyWhen={(value) => !value || value.length === 0}
      emptyMessage="공유된 학습자료가 없습니다."
    >
      {hasPdfMaterial && <QuizOptionsPicker options={quizOptions} onChange={setQuizOptions} />}
      <ul className="mobile-list">
        {(materials.data || []).map((material) => (
          <li key={material.id} data-material-id={material.id}>
            <ListRow
              icon={<FileText size={20} />}
              title={material.title || material.originalFileName}
              subtitle={[material.originalFileName, material.uploaderName].filter(Boolean).join(' · ')}
              trailing={isPdfMaterial(material) ? null : <ExternalLink size={18} />}
              onClick={() => openMaterial(material)}
            />
            {(isPdfMaterial(material) || isLeader) && (
              <div className="mobile-card__actions mobile-room-resource__actions">
                {isPdfMaterial(material) && (
                  <Button
                    variant="ghost"
                    disabled={isGenerating && quizGeneration.generatingMaterialId !== material.id}
                    isLoading={quizGeneration.generatingMaterialId === material.id}
                    onClick={() => quizGeneration.generate(material.id, quizOptions)}
                  >
                    <ClipboardList size={16} />
                    이 자료로 퀴즈 만들기
                  </Button>
                )}
                {isLeader && (
                  <LeaderDeleteAction kind={RESOURCE_KIND.MATERIAL} resourceId={material.id} deletion={materialDeletion} />
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      {isGenerating && <p className="mobile-field__hint">AI가 PDF 내용을 읽고 퀴즈를 생성하는 중입니다…</p>}
      {outcome && (
        <p
          className={outcome.isSuccess ? 'mobile-room-quiz-result' : 'mobile-auth__error'}
          role={outcome.isSuccess ? 'status' : 'alert'}
          data-quiz-generation={outcome.isSuccess ? 'success' : 'failure'}
        >
          {outcome.message}
        </p>
      )}
      {openExternally.errorMessage && <p className="mobile-auth__error">{openExternally.errorMessage}</p>}
      {materialDeletion.errorMessage && (
        <p className="mobile-auth__error" role="alert">
          {materialDeletion.errorMessage}
        </p>
      )}
    </ScreenState>
  );
}

function QuizList({ groupId, isLeader, room, quizzes }) {
  const quizDeletion = useResourceDeletion(groupId, RESOURCE_KIND.QUIZ, quizzes);

  return (
    <ScreenState
      query={quizzes}
      loadingLabel="퀴즈를 불러오는 중입니다"
      emptyWhen={(value) => !value || value.length === 0}
      emptyMessage="생성된 퀴즈가 없습니다. 학습자료 탭에서 PDF로 퀴즈를 만들어보세요."
    >
      <>
        {!room.isSocketConnected && <p className="mobile-chat__status">실시간 연결을 준비하는 중입니다</p>}
        <ul className="mobile-list">
          {(quizzes.data || []).map((quiz) => (
            <li key={quizIdOf(quiz)} data-quiz-id={quizIdOf(quiz)}>
              <ListRow
                title={quiz.title || quiz.quizTitle || '그룹 퀴즈'}
                subtitle={formatQuizMeta(quiz)}
                trailing={
                  <Button
                    variant="ghost"
                    disabled={!room.isSocketConnected}
                    onClick={() => room.startQuiz(quizIdOf(quiz))}
                  >
                    <Play size={16} />
                    시작
                  </Button>
                }
              />
              {isLeader && (
                <div className="mobile-card__actions mobile-room-resource__actions">
                  <LeaderDeleteAction kind={RESOURCE_KIND.QUIZ} resourceId={quizIdOf(quiz)} deletion={quizDeletion} />
                </div>
              )}
            </li>
          ))}
        </ul>
        {room.quizError && <p className="mobile-auth__error">{room.quizError}</p>}
        {quizDeletion.errorMessage && (
          <p className="mobile-auth__error" role="alert">
            {quizDeletion.errorMessage}
          </p>
        )}
      </>
    </ScreenState>
  );
}

export default function StudyResourcesPanel({
  groupId,
  isLeader,
  activeTab,
  room,
  materials,
  quizzes,
  onChangeTab,
  onOpenViewer,
  onClose,
}) {
  return (
    <RoomPanel
      title="자료 / 퀴즈"
      onClose={onClose}
      tabs={<SubTabs tabs={RESOURCE_TABS} activeKey={activeTab} onChange={onChangeTab} />}
    >
      {activeTab === ROOM_PANEL.QUIZ ? (
        <QuizList groupId={groupId} isLeader={isLeader} room={room} quizzes={quizzes} />
      ) : (
        <MaterialsList
          groupId={groupId}
          isLeader={isLeader}
          materials={materials}
          quizzes={quizzes}
          onOpenViewer={onOpenViewer}
        />
      )}
    </RoomPanel>
  );
}
