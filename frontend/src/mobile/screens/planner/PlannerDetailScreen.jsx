import React from 'react';
import { CalendarPlus, CheckCircle2, Circle, Download, PencilLine, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService, todoService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import { extractDownloadUrl } from '../../platform/downloadUrl';
import { openExternalUrl } from '../../platform/externalLink';
import TimeTableGrid from './TimeTableGrid';
import { findLinkedSchedule, formatMinutes, toPlannerDetail } from './plannerAdapter';

export default function PlannerDetailScreen() {
  const { plannerId } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

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

  // 플래너의 "완료"는 등록된 주간일정(todo) 토글이 유일한 백엔드 계약이다.
  const toggleCompletion = useSubmit(async () => {
    await todoService.toggleTodo(linkedSchedule.id);
    await todos.reload();
  });

  const downloadPdf = useSubmit(async () => {
    const response = await plannerService.getDownloadUrl(plannerId);
    await openExternalUrl(extractDownloadUrl(response));
  });

  const removePlanner = useSubmit(async () => {
    await plannerService.deletePlanner(plannerId);
    navigate('/planner', { replace: true });
  });

  const data = planner.data;
  const actionError =
    registerSchedule.errorMessage ||
    toggleCompletion.errorMessage ||
    downloadPdf.errorMessage ||
    removePlanner.errorMessage;

  return (
    <MobileScreen title={data?.title || '플래너'} showBackButton>
      <ScreenState query={planner} loadingLabel="플래너를 불러오는 중입니다">
        <>
          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">
              {[data?.subject, data?.date, data?.term, data?.priority].filter(Boolean).join(' · ')}
            </p>

            {data?.goalTime && <p className="mobile-card__meta">목표 학습 시간 {data.goalTime}</p>}
            <p className="mobile-card__meta">계획한 학습량 {formatMinutes(data?.plannedMinutes ?? 0)}</p>

            {data?.content && <p className="mobile-paragraph">{data.content}</p>}
          </section>

          <section className="mobile-section">
            <h3 className="mobile-section__title">학습 시간표</h3>
            <TimeTableGrid timeTable={data?.timeTable || {}} />
          </section>

          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">주간일정 연동</p>

            {linkedSchedule ? (
              <button
                type="button"
                className="mobile-todo__toggle"
                onClick={() => toggleCompletion.submit().catch(() => {})}
              >
                {linkedSchedule.completed ? (
                  <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
                ) : (
                  <Circle size={20} className="mobile-roadmap__check" />
                )}
                <span className={linkedSchedule.completed ? 'is-completed' : ''}>
                  {linkedSchedule.text}
                </span>
              </button>
            ) : (
              <p className="mobile-card__meta">아직 주간일정에 등록되지 않았습니다.</p>
            )}
          </section>

          <div className="mobile-actions">
            <Button
              variant="secondary"
              isLoading={registerSchedule.isSubmitting}
              disabled={Boolean(linkedSchedule)}
              onClick={() => registerSchedule.submit().catch(() => {})}
            >
              <CalendarPlus size={16} />
              {linkedSchedule ? '일정 등록됨' : '일정 등록'}
            </Button>

            <Button variant="secondary" onClick={() => navigate(`/planner/${plannerId}/edit`)}>
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
              variant="ghost"
              isLoading={removePlanner.isSubmitting}
              onClick={() => removePlanner.submit().catch(() => {})}
            >
              <Trash2 size={16} />
              삭제
            </Button>
          </div>

          {actionError && <p className="mobile-auth__error">{actionError}</p>}
        </>
      </ScreenState>
    </MobileScreen>
  );
}
