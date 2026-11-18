import React, { useState } from 'react';
import { Archive, CalendarPlus, CheckCircle2, Circle, Download, PencilLine, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService, todoService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import { extractDownloadUrl } from '../../platform/downloadUrl';
import { openExternalUrl } from '../../platform/externalLink';
import TimeTableGrid from './TimeTableGrid';
import { materialDetailPath } from '../archive/archiveNavigation';
import {
  ARCHIVE_ERROR_MESSAGES,
  archiveActionLabel,
  archivedMaterialIdOf,
  findLinkedSchedule,
  formatMinutes,
  formatPlannerDate,
  toPlannerDetail,
} from './plannerAdapter';

function PlannerFields({ planner }) {
  const fields = [
    ['날짜', formatPlannerDate(planner)],
    ['학기 / 주차', planner.term],
    ['과목명', planner.subject],
    ['학습 유형', planner.studyType],
    ['우선순위', planner.priority],
    ['목표 학습 시간', planner.goalTime],
    ['실제 학습 시간', planner.netStudyTime],
    ['마감일 / 시험일', planner.dDay],
    ['기상 시간', planner.wakeUpTime],
  ].filter(([, value]) => Boolean(value));

  return (
    <dl className="mobile-planner-fields">
      {fields.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PlannerTextBlock({ label, text }) {
  if (!text) return null;

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">{label}</h3>
      <p className="mobile-paragraph">{text}</p>
    </section>
  );
}

function LinkedScheduleCard({ linkedSchedule, onToggle }) {
  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">주간일정 연동</p>

      {linkedSchedule ? (
        <button type="button" className="mobile-todo__toggle" onClick={onToggle}>
          {linkedSchedule.completed ? (
            <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
          ) : (
            <Circle size={20} className="mobile-roadmap__check" />
          )}
          <span className={linkedSchedule.completed ? 'is-completed' : ''}>{linkedSchedule.text}</span>
        </button>
      ) : (
        <p className="mobile-card__meta">아직 주간일정에 등록되지 않았습니다.</p>
      )}
    </section>
  );
}

export default function PlannerDetailScreen() {
  const { plannerId } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();
  const [isDeleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  const planner = useAsync(
    async () => toPlannerDetail(await plannerService.getPlanner(plannerId)),
    [plannerId]
  );

  const todos = useAsync(() => todoService.getTodos(userId), [userId]);
  const linkedSchedule = findLinkedSchedule(todos.data, plannerId);

  const registerSchedule = useSubmit(async () => {
    await plannerService.registerSchedule(plannerId);
    await todos.reload();
  });

  const toggleCompletion = useSubmit(async () => {
    await todoService.toggleTodo(linkedSchedule.id);
    await todos.reload();
  });

  const downloadPdf = useSubmit(async () => {
    const response = await plannerService.generatePdf(plannerId);
    const url = extractDownloadUrl(response);
    if (!url) throw new Error('PDF 다운로드 주소를 받지 못했습니다.');
    await openExternalUrl(url);
  });

  // 기존 서버 보관 API 재사용: 소유권 검증·중복 저장 시 같은 항목 갱신·미리보기 PDF 생성은 서버가 맡는다.
  const archivePlanner = useSubmit(
    async () => {
      const materialId = archivedMaterialIdOf(await plannerService.archive(plannerId));
      navigate(materialDetailPath(materialId), { state: { notice: '자료보관함에 저장했습니다.' } });
    },
    { errorMessages: ARCHIVE_ERROR_MESSAGES }
  );

  const removePlanner = useSubmit(async () => {
    await plannerService.deletePlanner(plannerId);
    navigate('/planner', { replace: true });
  });

  const data = planner.data;
  const actionError =
    registerSchedule.errorMessage ||
    toggleCompletion.errorMessage ||
    downloadPdf.errorMessage ||
    archivePlanner.errorMessage ||
    removePlanner.errorMessage;

  const renderPlannerContent = () => (
    <>
      <section className="mobile-card mobile-section">
        {data.roadmapLabel && <p className="mobile-card__meta">{data.roadmapLabel}</p>}
        <PlannerFields planner={data} />
        <p className="mobile-card__meta">계획한 학습량 {formatMinutes(data.plannedMinutes)}</p>
      </section>

      <PlannerTextBlock label="학습 목표" text={data.content} />
      <PlannerTextBlock label="세부 할 일" text={data.tmi} />

      <section className="mobile-section">
        <h3 className="mobile-section__title">시간 체크표</h3>
        <TimeTableGrid timeTable={data.timeTable} />
      </section>

      <LinkedScheduleCard
        linkedSchedule={linkedSchedule}
        onToggle={() => toggleCompletion.submit().catch(() => {})}
      />

      <div className="mobile-actions">
        <Button
          variant="secondary"
          isLoading={registerSchedule.isSubmitting}
          disabled={Boolean(linkedSchedule)}
          onClick={() => registerSchedule.submit().catch(() => {})}
        >
          <CalendarPlus size={16} />
          {linkedSchedule ? '일정 등록됨' : '주간일정 추가'}
        </Button>

        <Button variant="action" onClick={() => navigate(`/planner/${plannerId}/edit`)}>
          <PencilLine size={16} />
          수정
        </Button>

        <Button
          variant="secondary"
          isLoading={downloadPdf.isSubmitting}
          onClick={() => downloadPdf.submit().catch(() => {})}
        >
          <Download size={16} />
          PDF
        </Button>

        <Button
          variant="secondary"
          isLoading={archivePlanner.isSubmitting}
          onClick={() => archivePlanner.submit().catch(() => {})}
        >
          <Archive size={16} />
          {archiveActionLabel(data)}
        </Button>

        <Button variant="ghost" onClick={() => setDeleteConfirmOpen(true)}>
          <Trash2 size={16} />
          삭제
        </Button>
      </div>

      {actionError && <p className="mobile-auth__error mobile-roadmap__error">{actionError}</p>}
    </>
  );

  return (
    <MobileScreen title={data?.title || '플래너'} showBackButton>
      <ScreenState query={planner} loadingLabel="플래너를 불러오는 중입니다">
        {data && renderPlannerContent()}
      </ScreenState>

      <BottomSheet
        title="플래너 삭제"
        isOpen={isDeleteConfirmOpen}
        onClose={() => {
          if (!removePlanner.isSubmitting) setDeleteConfirmOpen(false);
        }}
      >
        <p className="mobile-sheet__note">
          이 플래너를 삭제할까요? (자료보관함에 저장한 항목은 그대로 유지됩니다)
        </p>
        <div className="mobile-actions">
          <Button variant="ghost" disabled={removePlanner.isSubmitting} onClick={() => setDeleteConfirmOpen(false)}>
            취소
          </Button>
          <Button
            variant="danger"
            isLoading={removePlanner.isSubmitting}
            onClick={() => removePlanner.submit().catch(() => setDeleteConfirmOpen(false))}
          >
            삭제
          </Button>
        </div>
      </BottomSheet>
    </MobileScreen>
  );
}
